"""Consume the log into versioned indexes, swap them, and prove an erasure."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from conduit.chunker import chunk_document
from conduit.embedder import FakeEmbedder, build_embedder, cosine
from conduit.errors import ConduitError, EmbedderError, RedactorError
from conduit.metrics import lag_summary, tokens_from_chars, usd_per_million_docs
from conduit.models import Event, Generation, Incoming, Preview, Subject
from conduit.redact import build_redactor, scrub_body
from conduit.store import Store
from conduit.subjects import BY_ID, SUBJECTS
from conduit.synthetic import demo_events

ROOT = Path(__file__).resolve().parents[1]
PRICING_PATH = ROOT / "eval" / "pricing.yaml"


def _score(hit: dict[str, object]) -> float:
    value = hit["score"]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Conduit:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        embedder: object | None = None,
        redactor: object | None = None,
        subjects: tuple[Subject, ...] = SUBJECTS,
    ) -> None:
        path = Path(db_path) if db_path is not None else ROOT / "var" / "conduit.db"
        self.store = Store(path)
        self.embedder = embedder if embedder is not None else build_embedder()
        self.redactor = redactor if redactor is not None else build_redactor()
        self.subjects = subjects
        self._lock = threading.RLock()
        self.preview: Preview | None = None
        self.hold_preview_clear = False

    def close(self) -> None:
        self.store.close()

    def reset(self) -> dict[str, object]:
        with self._lock:
            spec = self.embedder.spec("emb-v1")  # type: ignore[attr-defined]
            self.store.reset(model_version=spec.version, model_id=spec.model_id, dim=spec.dim, at=_now())
            self.preview = None
            self.hold_preview_clear = False
            return self.status()

    def ingest_script(self, name: str) -> dict[str, object]:
        if name != "demo":
            raise ConduitError(f"unknown script {name!r}")
        return self.ingest(demo_events())

    def ingest(self, events: list[Incoming]) -> dict[str, object]:
        with self._lock, self.store.transaction():
            accepted = 0
            for event in events:
                if event.op not in {"upsert", "delete"}:
                    raise ConduitError(f"unsupported op {event.op!r}")
                try:
                    self.store.append(event)
                except sqlite3.IntegrityError as exc:
                    raise ConduitError(f"duplicate event_id {event.event_id}", 409) from exc
                accepted += 1
        return {"accepted": accepted, **self._public_status()}

    def consume(self, limit: int | None = None) -> dict[str, object]:
        with self._lock:
            done = 0
            while limit is None or done < limit:
                event = self.store.next_event(self.store.offset())
                if event is None:
                    break
                targets = self._targets_for(event.seq)
                with self.store.transaction():
                    self._apply(event, targets, record_lag=True)
                    self.store.set_offset("indexer", event.seq)
                done += 1
            self._refresh_migration()
            body = self.status()
            body["consumed"] = done
            return body

    def start_migration(self, model_version: str) -> dict[str, object]:
        with self._lock:
            migration = self.store.migration()
            if migration.state != "idle":
                raise ConduitError(f"migration is {migration.state}", 409)
            try:
                spec = self.embedder.spec(model_version)  # type: ignore[attr-defined]
            except EmbedderError as exc:
                raise ConduitError(str(exc), 400) from exc
            active = self.store.active()
            if spec.version == active.model_version:
                raise ConduitError(f"the read alias is already {spec.version}", 409)
            other = "green" if active.name == "blue" else "blue"
            existing = self.store.generation_by_name(other)
            if existing is not None and existing.state == "building":
                raise ConduitError(f"{other} is already building", 409)
            if existing is not None and existing.state == "active":
                raise ConduitError(f"{other} is the active generation", 409)
            with self.store.transaction():
                if existing is not None and existing.state == "retired":
                    self.store.purge_generation(existing.id)
                target_id = self.store.insert_generation(
                    name=other,
                    model_id=spec.model_id,
                    model_version=spec.version,
                    dim=spec.dim,
                    state="building",
                    at=_now(),
                )
                self.store.set_migration("dual_writing", active.id, target_id, _now())
            self._refresh_migration()
            return self.status()

    def migration_step(self, limit: int = 20) -> dict[str, object]:
        with self._lock:
            migration = self.store.migration()
            if (
                migration.state != "dual_writing"
                or migration.source_id is None
                or migration.target_id is None
            ):
                raise ConduitError("no dual-write is in progress", 409)
            source = self.store.generation(migration.source_id)
            applied = 0
            events = self.store.events_between(
                self.store.generation(migration.target_id).high_water, source.high_water, limit
            )
            for event in events:
                with self.store.transaction():
                    self._apply(event, [self.store.generation(migration.target_id)], record_lag=False)
                applied += 1
            self._refresh_migration()
            body = self.status()
            body["backfilled"] = applied
            return body

    def swap(self) -> dict[str, object]:
        with self._lock:
            self._refresh_migration()
            migration = self.store.migration()
            if (
                migration.state != "ready_to_swap"
                or migration.target_id is None
                or migration.source_id is None
            ):
                raise ConduitError("shadow generation is not caught up", 409)
            target = self.store.generation(migration.target_id)
            self._assert_one_space(target)
            with self.store.transaction():
                self.store.set_state(migration.source_id, "retired")
                self.store.set_state(migration.target_id, "active")
                self.store.set_alias(migration.target_id, _now())
                self.store.set_migration("idle", None, None, None)
            return self.status()

    def rollback(self) -> dict[str, object]:
        with self._lock:
            if self.store.migration().state != "idle":
                raise ConduitError("finish or leave the migration before rolling back", 409)
            current = self.store.active()
            previous_id: int | None = None
            for generation_id in reversed(self.store.history()):
                if generation_id == current.id:
                    continue
                try:
                    self.store.generation(generation_id)
                except KeyError:
                    continue
                previous_id = generation_id
                break
            if previous_id is None:
                raise ConduitError("nothing to roll back to", 409)
            with self.store.transaction():
                self.store.set_state(current.id, "retired")
                self.store.set_state(previous_id, "active")
                self.store.set_alias(previous_id, _now())
            return self.status()

    def forget(self, subject_id: str) -> dict[str, object]:
        with self._lock:
            existing = self.store.proof_for(subject_id)
            if existing is not None and existing.get("verified") is True:
                return existing
            subject = BY_ID.get(subject_id) or Subject(subject_id, "", "")
            with self.store.transaction():
                before = self.store.subject_chunk_count(subject_id)
                self.store.add_tombstone(subject_id, _now())
                rows = self.store.chunks_for_subject(subject_id)
                hashes = {str(row["content_hash"]) for row in rows}
                generations = sorted({int(row["generation_id"]) for row in rows})
                removed = self.store.delete_subject_chunks(subject_id)
                cache_dropped = self.store.drop_unused_hashes(hashes)
                if subject.name or subject.email:
                    for event in self.store.events_touching(subject_id, subject.name, subject.email):
                        declared = set(event.subject_ids)
                        new_text = scrub_body(event.text, subject, declared, self.subjects)
                        new_title = (
                            scrub_body(event.title, subject, set(), self.subjects)
                            if subject.name
                            else event.title
                        )
                        if subject.name and subject.name.lower() in new_title.lower():
                            new_title = "[erased]"
                        if subject.email and subject.email.lower() in new_title.lower():
                            new_title = "[erased]"
                        self.store.update_event_text(event.seq, new_text, new_title)
                        if declared and declared <= self.store.tombstone_ids():
                            for generation in self.store.generations():
                                self.store.delete_doc(generation.id, event.doc_id)
                self.store.scrub_doc_titles(subject.name, subject.email)
                name_hits = (
                    self.store.count_like(subject.name)
                    if subject.name
                    else {"chunks": 0, "events": 0, "docs": 0}
                )
                email_hits = (
                    self.store.count_like(subject.email)
                    if subject.email
                    else {"chunks": 0, "events": 0, "docs": 0}
                )
                remaining = self.store.subject_chunk_count(subject_id)
                verified = (
                    remaining == 0
                    and name_hits["chunks"] == 0
                    and name_hits["events"] == 0
                    and name_hits["docs"] == 0
                    and email_hits["chunks"] == 0
                    and email_hits["events"] == 0
                    and email_hits["docs"] == 0
                )
                if not verified:
                    raise ConduitError("erasure could not prove the subject was gone", 500)
                proof: dict[str, object] = {
                    "subject_id": subject_id,
                    "display_name": subject.name or subject_id,
                    "chunks_before": before,
                    "chunks_removed": removed,
                    "generations_swept": generations,
                    "remaining_chunks": remaining,
                    "remaining_subject_links": remaining,
                    "name_in_chunks": name_hits["chunks"],
                    "name_in_log": name_hits["events"],
                    "email_in_chunks": email_hits["chunks"],
                    "email_in_log": email_hits["events"],
                    "name_in_docs": name_hits["docs"],
                    "email_in_docs": email_hits["docs"],
                    "cache_entries_dropped": cache_dropped,
                    "verified": True,
                }
                self.store.finish_tombstone(subject_id, _now(), removed, proof)
            self._drop_preview(subject)
            return proof

    def replay(self) -> dict[str, object]:
        """Re-read the log from offset 0. Tombstones and versions make this safe."""
        with self._lock:
            with self.store.transaction():
                self.store.set_offset("indexer", 0)
            return self.consume()

    def retry_quarantine(self) -> dict[str, object]:
        with self._lock:
            cleared = 0
            for row in self.store.quarantine_rows():
                event = self.store.event_by_seq(int(row["seq"]))
                if event is None:
                    continue
                try:
                    self.redactor.redact(event.text, self.subjects)  # type: ignore[attr-defined]
                except RedactorError:
                    continue
                targets = [self.store.active()]
                migration = self.store.migration()
                if migration.target_id is not None and migration.state in {"dual_writing", "ready_to_swap"}:
                    shadow = self.store.generation(migration.target_id)
                    if shadow.high_water >= event.seq:
                        targets.append(shadow)
                with self.store.transaction():
                    self._apply(event, targets, record_lag=False)
                    self.store.clear_quarantine(event.seq)
                cleared += 1
            body = self.status()
            body["retried"] = cleared
            return body

    def search(self, query: str, k: int = 5) -> dict[str, object]:
        with self._lock:
            if k < 1:
                raise ConduitError("k must be at least 1")
            generation = self.store.active()
            self._assert_one_space(generation)
            try:
                redacted = self.redactor.redact(query, self.subjects)  # type: ignore[attr-defined]
                vector = self.embedder.embed(redacted.text, generation.model_version)  # type: ignore[attr-defined]
            except (RedactorError, EmbedderError) as exc:
                raise ConduitError(str(exc), 503) from exc
            if len(vector) != generation.dim:
                raise ConduitError(
                    f"query vector dim {len(vector)} does not match generation {generation.model_version} dim {generation.dim}",
                    500,
                )
            scored: list[dict[str, object]] = []
            for doc_id, text, index, _embed, stored in self.store.iter_vectors(generation.id):
                scored.append(
                    {
                        "doc_id": doc_id,
                        "chunk_index": index,
                        "text": text,
                        "score": round(cosine(vector, stored), 6),
                    }
                )
            scored.sort(key=lambda hit: _score(hit), reverse=True)
            # Below 0.25 the hash embedder is returning a shared function word or a
            # one-bucket collision, not the query. A forgotten subject scores 0.
            scored = [hit for hit in scored if _score(hit) >= 0.25]
            return {
                "generation": generation.name,
                "model_version": generation.model_version,
                "query_redacted": redacted.text,
                "hits": scored[:k],
            }

    def status(self) -> dict[str, object]:
        with self._lock:
            return self._public_status()

    def projection(self) -> dict[str, object]:
        with self._lock:
            return self._projection(self.store.active())

    def _public_status(self) -> dict[str, object]:
        active = self.store.active()
        migration = self.store.migration()
        calls, reused = self.store.embed_totals()
        generations = []
        for generation in self.store.generations():
            chunks, docs = self.store.generation_counts(generation.id)
            generations.append(
                {
                    "id": generation.id,
                    "name": generation.name,
                    "state": generation.state,
                    "model_id": generation.model_id,
                    "model_version": generation.model_version,
                    "dim": generation.dim,
                    "high_water": generation.high_water,
                    "chunks": chunks,
                    "docs": docs,
                    "read": generation.id == active.id,
                }
            )
        source_hw = None
        target_hw = None
        source_name = None
        target_name = None
        if migration.source_id is not None:
            source = self.store.generation(migration.source_id)
            source_hw = source.high_water
            source_name = source.name
        if migration.target_id is not None:
            try:
                target = self.store.generation(migration.target_id)
            except KeyError:
                target = None
            if target is not None:
                target_hw = target.high_water
                target_name = target.name
        head = self.store.log_head()
        offset = self.store.offset()
        subjects = []
        tombs = self.store.tombstone_ids()
        for subject in self.subjects:
            subjects.append(
                {
                    "id": subject.id,
                    "name": subject.name,
                    "email": subject.email,
                    "chunks": self.store.subject_chunk_count(subject.id, active.id),
                    "tombstoned": subject.id in tombs,
                }
            )
        preview = None
        if self.preview is not None:
            preview = {
                "doc_id": self.preview.doc_id,
                "title": self.preview.title,
                "raw": self.preview.raw,
                "redacted": self.preview.redacted,
                "findings": list(self.preview.findings),
            }
        return {
            "offline": True,
            "embedder": active.model_id,
            "log_head": head,
            "consumer_offset": offset,
            "lag_events": max(0, head - offset),
            "lag_ms": lag_summary(self.store.lag_values()),
            "embed_calls": calls,
            "embed_reused": reused,
            "quarantine": len(self.store.quarantine_rows()),
            "alias": {
                "name": active.name,
                "model_version": active.model_version,
                "generation_id": active.id,
                "dim": active.dim,
            },
            "migration": {
                "state": migration.state,
                "source": source_name,
                "target": target_name,
                "source_high_water": source_hw,
                "target_high_water": target_hw,
            },
            "generations": generations,
            "subjects": subjects,
            "events": [_event_view(event) for event in self.store.recent_events(14)],
            "preview": preview,
            "proof": self.store.latest_proof(),
            "projection": self._projection(active),
            "models": _known_models(self.embedder),
        }

    def _drop_preview(self, subject: Subject) -> None:
        if self.preview is None:
            return
        blob = f"{self.preview.raw}\n{self.preview.redacted}".lower()
        needles = [subject.id.lower()]
        if subject.name:
            needles.append(subject.name.lower())
        if subject.email:
            needles.append(subject.email.lower())
        if any(needle and needle in blob for needle in needles):
            self.preview = None
            self.hold_preview_clear = True

    def _projection(self, generation: Generation) -> dict[str, object]:
        chars, docs = self.store.embedded_chars(generation.id)
        prices, chars_per_token, scaled = _load_prices()
        tokens_per_doc = tokens_from_chars(chars / docs, chars_per_token) if docs else 0.0
        measured = {
            name: round(usd_per_million_docs(tokens_per_doc, price), 4) if docs else None
            for name, price in prices.items()
        }
        examples = {
            label: {name: round(usd_per_million_docs(tokens, price), 2) for name, price in prices.items()}
            for label, tokens in scaled.items()
        }
        return {
            "label": "illustrative list price, not an invoice",
            "docs": docs,
            "embedded_chars": chars,
            "tokens_per_doc": round(tokens_per_doc, 2),
            "usd_per_million_docs": measured,
            "scaled_usd_per_million_docs": examples,
        }

    def _targets_for(self, seq: int) -> list[Generation]:
        active = self.store.active()
        targets = [active]
        migration = self.store.migration()
        if migration.state in {"dual_writing", "ready_to_swap"} and migration.target_id is not None:
            shadow = self.store.generation(migration.target_id)
            if shadow.high_water + 1 == seq:
                targets.append(shadow)
        return targets

    def _apply(self, event: Event, targets: list[Generation], *, record_lag: bool) -> None:
        started = time.perf_counter()
        tombs = self.store.tombstone_ids()
        declared = set(event.subject_ids)
        if event.op == "delete":
            for generation in targets:
                self.store.delete_doc(generation.id, event.doc_id)
                self.store.set_high_water(generation.id, event.seq)
                self.store.record_apply(event.seq, generation.id, 0, 0, 0, "delete")
            self._lag(event.seq, started, "delete", record_lag)
            return
        if declared and declared <= tombs:
            for generation in targets:
                self.store.delete_doc(generation.id, event.doc_id)
                self.store.set_high_water(generation.id, event.seq)
                self.store.record_apply(event.seq, generation.id, 0, 0, 0, "suppressed")
            self._lag(event.seq, started, "suppressed", record_lag)
            return
        try:
            redacted = self.redactor.redact(event.text, self.subjects)  # type: ignore[attr-defined]
        except RedactorError as exc:
            self.store.quarantine(event, str(exc))
            for generation in targets:
                self.store.set_high_water(generation.id, event.seq)
                self.store.record_apply(event.seq, generation.id, 0, 0, 0, "quarantined")
            self._lag(event.seq, started, "quarantined", record_lag)
            return
        kinds = sorted({finding.kind for finding in redacted.findings})
        if (
            kinds
            and not self.hold_preview_clear
            and (self.preview is None or len(kinds) > len(self.preview.findings))
        ):
            self.preview = Preview(
                doc_id=event.doc_id,
                title=event.title,
                raw=event.text,
                redacted=redacted.text,
                findings=kinds,
            )
        chunks = [
            chunk for chunk in chunk_document(event.title, redacted.text) if not (set(chunk.subjects) & tombs)
        ]
        for generation in targets:
            current = self.store.doc_version(generation.id, event.doc_id)
            if current is not None and event.doc_version <= current:
                self.store.set_high_water(generation.id, event.seq)
                self.store.record_apply(event.seq, generation.id, 0, 0, 0, "stale")
                continue
            calls = 0
            reused = 0
            rows: list[tuple[int, str, str, str, tuple[str, ...], tuple[float, ...]]] = []
            for chunk in chunks:
                cached = self.store.cache_get(generation.model_version, chunk.content_hash)
                if cached is not None and len(cached) == generation.dim:
                    vector = cached
                    reused += 1
                else:
                    vector = self.embedder.embed(chunk.embed_text, generation.model_version)  # type: ignore[attr-defined]
                    if len(vector) != generation.dim:
                        raise ConduitError(
                            f"{generation.model_version} returned dim {len(vector)}, generation expects {generation.dim}",
                            500,
                        )
                    self.store.cache_put(generation.model_version, chunk.content_hash, vector)
                    calls += 1
                rows.append(
                    (chunk.index, chunk.text, chunk.embed_text, chunk.content_hash, chunk.subjects, vector)
                )
            self.store.write_doc(
                generation_id=generation.id,
                doc_id=event.doc_id,
                doc_version=event.doc_version,
                title=event.title,
                model_version=generation.model_version,
                rows=rows,
            )
            self.store.set_high_water(generation.id, event.seq)
            self.store.record_apply(event.seq, generation.id, calls, reused, len(rows), "applied")
        self._lag(event.seq, started, "applied", record_lag)

    def _lag(self, seq: int, started: float, outcome: str, record: bool) -> None:
        if record:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.store.record_lag(seq, elapsed_ms, outcome)

    def _refresh_migration(self) -> None:
        migration = self.store.migration()
        if migration.state not in {"dual_writing", "ready_to_swap"}:
            return
        if migration.source_id is None or migration.target_id is None:
            return
        source = self.store.generation(migration.source_id)
        target = self.store.generation(migration.target_id)
        caught_up = target.high_water >= source.high_water and self.store.offset() >= self.store.log_head()
        state = "ready_to_swap" if caught_up else "dual_writing"
        self.store.set_migration(state, source.id, target.id, migration.started_at)

    def _assert_one_space(self, generation: Generation) -> None:
        versions = self.store.model_versions(generation.id)
        foreign = versions - {generation.model_version}
        if foreign:
            raise ConduitError(
                f"generation {generation.name} mixes {sorted(versions)}",
                500,
            )


def _event_view(event: Event) -> dict[str, object]:
    return {
        "seq": event.seq,
        "op": event.op,
        "doc_id": event.doc_id,
        "doc_version": event.doc_version,
        "title": event.title,
        "subject_ids": list(event.subject_ids),
        "source_ts": event.source_ts,
    }


def _known_models(embedder: object) -> list[str]:
    if isinstance(embedder, FakeEmbedder):
        from conduit.embedder import FAKE_MODELS

        return list(FAKE_MODELS)
    return []


def _load_prices() -> tuple[dict[str, float], float, dict[str, float]]:
    import yaml

    raw = yaml.safe_load(PRICING_PATH.read_text(encoding="utf-8"))
    prices = {str(key): float(value) for key, value in raw["usd_per_million_tokens"].items()}
    chars_per_token = float(raw["chars_per_token"])
    scaled = {str(key): float(value) for key, value in raw["scaled_tokens_per_doc"].items()}
    return prices, chars_per_token, scaled
