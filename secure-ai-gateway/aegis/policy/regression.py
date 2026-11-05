"""Evaluation corpus runner and the policy regression gate.

Used three ways:
  * `make redteam`   -> precision / recall / FP / FN report over the red-team corpus
  * `make regression` -> fails the build if the current code + policy loses protection vs the baseline
  * PUT /admin/policies -> refuses to activate a policy that loses protection (409)
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aegis.classifier.types import SensitivityClassifier
from aegis.demo.fakes import expand
from aegis.dlp.engine import DLPEngine
from aegis.gateway.pipeline import classifier_view
from aegis.guard.injection import InjectionDetector
from aegis.guard.interceptor import RunState, ToolGuard, Verdict
from aegis.llm.base import ToolCall
from aegis.policy.engine import decide
from aegis.policy.schema import Policy, PolicyBundle
from aegis.types import EntityType, Route
from aegis.vault.backends import MemoryBackend
from aegis.vault.crypto import VaultCipher
from aegis.vault.vault import TokenVault, VaultContext

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
CASES_DIR = EVAL_DIR / "cases"
BASELINE = EVAL_DIR / "regression" / "baseline.json"
_VERDICT = {"allow": Verdict.ALLOW, "require_approval": Verdict.REQUIRE_APPROVAL, "block": Verdict.BLOCK}


def _expand_all(obj: Any) -> Any:
    """Fill {{FAKE_*}} markers after parsing, so values with newlines stay valid."""
    if isinstance(obj, str):
        return expand(obj)
    if isinstance(obj, list):
        return [_expand_all(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _expand_all(v) for k, v in obj.items()}
    return obj


def load_cases(paths: Iterable[Path] | None = None) -> list[dict[str, Any]]:
    files = list(paths) if paths else sorted(CASES_DIR.glob("*.jsonl"))
    cases: list[dict[str, Any]] = []
    for f in files:
        for line in f.read_text().splitlines():
            if line.strip():
                cases.append(_expand_all(json.loads(line)))
    ids = [c["id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate case ids: {sorted(dupes)}")
    return cases


@dataclass
class CaseResult:
    id: str
    category: str
    kind: str
    should_protect: bool
    outcome: str  # TP | FN | FP | TN
    detail: dict[str, Any] = field(default_factory=dict)
    entity_tp: int = 0
    entity_fn: int = 0
    entity_fp: int = 0

    @property
    def passed(self) -> bool:
        return self.outcome in ("TP", "TN")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class Evaluator:
    def __init__(
        self, dlp: DLPEngine, classifier: SensitivityClassifier | None, injection: InjectionDetector
    ) -> None:
        self.dlp = dlp
        self.classifier = classifier
        self.injection = injection

    def _vault(self) -> tuple[TokenVault, VaultContext]:
        vault = TokenVault(MemoryBackend(), VaultCipher({"eval": secrets.token_bytes(32)}, "eval"))
        ctx = VaultContext("eval", "u-eval", "sess-eval-0001", "eval")
        vault.open_session(ctx.tenant_id, ctx.user_id, ctx.session_id)
        return vault, ctx

    def evaluate(self, policy: Policy, cases: list[dict[str, Any]]) -> list[CaseResult]:
        out = []
        for c in cases:
            kind = c["kind"]
            if kind == "prompt":
                out.append(self._prompt(c, policy))
            elif kind == "tool":
                out.append(self._tool(c, policy))
            elif kind == "document":
                out.append(self._document(c, policy))
            else:
                raise ValueError(f"unknown case kind {kind!r} in {c['id']}")
        return out

    # ------------------------------------------------------------------ prompts

    def _prompt(self, c: dict[str, Any], policy: Policy) -> CaseResult:
        text: str = c["text"]
        expected = c.get("entities", [])
        exp = c.get("expect", {})
        vault, ctx = self._vault()
        scan = self.dlp.scan(text, policy)
        tokenized = vault.apply(scan, ctx)
        clf = None
        if self.classifier is not None and policy.classifier.enabled:
            clf = self.classifier.classify(classifier_view(tokenized), policy.classifier.min_confidence)
        d = decide(text=text, scan=scan, classification=clf, policy=policy, policy_version="eval")
        outbound = tokenized if d.route in (Route.ALLOW, Route.REDACT, Route.REQUIRE_APPROVAL) else None

        spans: list[tuple[int, int]] = []
        leaked: list[str] = []
        entity_tp = entity_fn = 0
        for e in expected:
            start = text.find(e["value"])
            end = start + len(e["value"])
            spans.append((start, end))
            covered = start >= 0 and any(f.start < end and start < f.end for f in scan.applied)
            raw_out = outbound is not None and (
                e["value"] in outbound
                or (
                    e["type"] in ("CREDIT_CARD", "SSN", "PHONE")
                    and len(_digits(e["value"])) >= 9
                    and _digits(e["value"]) in _digits(outbound)
                )
            )
            if covered and not raw_out:
                entity_tp += 1
            else:
                entity_fn += 1  # detection metric: missed even if routing kept it in
            if raw_out or (not covered and outbound is not None):
                leaked.append(e["type"])  # protection metric: the raw value would reach the third party
        entity_fp = sum(1 for f in scan.applied if not any(f.start < b and a < f.end for a, b in spans))

        min_route = Route(exp["min_route"]) if exp.get("min_route") else None
        max_route = Route(exp["max_route"]) if exp.get("max_route") else None
        route_ok = min_route is None or d.route.strictness >= min_route.strictness
        should_protect = bool(expected) or bool(c.get("sensitive")) or min_route is not None
        detail = {
            "route": d.route.value,
            "context_label": d.context_label.name,
            "rule_id": d.rule_id,
            "applied": [f.entity_type.value for f in scan.applied],
            "leaked_entities": leaked,
            "classifier": None
            if clf is None
            else {"label": clf.label.name, "confidence": round(clf.confidence, 3)},
        }
        if entity_fn and not leaked:
            detail["note"] = "protected by routing (not sent externally), but the entity was not detected"
        if should_protect:
            outcome = "TP" if not leaked and route_ok else "FN"
            if not route_ok:
                detail["reason"] = (
                    f"route {d.route.value} weaker than required {min_route.value if min_route else ''}"
                )
        else:
            over = bool(scan.applied) or (max_route is not None and d.route.strictness > max_route.strictness)
            outcome = "FP" if over else "TN"
            if over:
                detail["reason"] = (
                    "false redaction" if scan.applied else f"route {d.route.value} stricter than {max_route}"
                )
        return CaseResult(
            c["id"], c["category"], "prompt", should_protect, outcome, detail, entity_tp, entity_fn, entity_fp
        )

    # ------------------------------------------------------------------ tool calls

    def _tool(self, c: dict[str, Any], policy: Policy) -> CaseResult:
        vault, ctx = self._vault()
        for item in c.get("setup", []):
            vault.tokenize(item["value"], item["value"].lower(), EntityType(item["type"]), ctx)
        guard = ToolGuard(vault, self.dlp)
        state = RunState(tainted=bool(c.get("tainted")), taint_sources=["eval"])
        g = guard.check(ToolCall(c["tool"], dict(c["arguments"])), ctx, state, policy)
        expected = _VERDICT[c["expect"]["verdict"]]
        should_protect = expected is not Verdict.ALLOW
        detail = {
            "verdict": g.verdict.name.lower(),
            "expected": c["expect"]["verdict"],
            "rules": sorted({r["rule"] for r in g.reasons}),
        }
        if should_protect:
            outcome = "TP" if g.verdict >= expected else "FN"
        else:
            outcome = "FP" if g.verdict > Verdict.ALLOW else "TN"
        return CaseResult(c["id"], c["category"], "tool", should_protect, outcome, detail)

    # ------------------------------------------------------------------ documents

    def _document(self, c: dict[str, Any], policy: Policy) -> CaseResult:
        r = self.injection.scan(c["text"], policy.injection.threshold)
        should_protect = bool(c["expect"]["injection"])
        outcome = _outcome(should_protect, caught=r.flagged)
        return CaseResult(
            c["id"],
            c["category"],
            "document",
            should_protect,
            outcome,
            {"score": round(r.score, 3), "signals": [s["id"] for s in r.signals]},
        )


def _outcome(should_protect: bool, *, caught: bool) -> str:
    if should_protect:
        return "TP" if caught else "FN"
    return "FP" if caught else "TN"


# ---------------------------------------------------------------------- metrics


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    def block(rs: list[CaseResult]) -> dict[str, Any]:
        tp = sum(r.outcome == "TP" for r in rs)
        fn = sum(r.outcome == "FN" for r in rs)
        fp = sum(r.outcome == "FP" for r in rs)
        tn = sum(r.outcome == "TN" for r in rs)
        return {
            "cases": len(rs),
            "tp": tp,
            "fn": fn,
            "fp": fp,
            "tn": tn,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
        }

    cats: dict[str, list[CaseResult]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)
    etp = sum(r.entity_tp for r in results)
    efn = sum(r.entity_fn for r in results)
    efp = sum(r.entity_fp for r in results)
    return {
        "overall": block(results),
        "by_category": {k: block(v) for k, v in sorted(cats.items())},
        "entities": {
            "tp": etp,
            "fn": efn,
            "fp": efp,
            "recall": etp / (etp + efn) if etp + efn else None,
            "precision": etp / (etp + efp) if etp + efp else None,
        },
    }


# ---------------------------------------------------------------------- regression gate


@dataclass
class GateReport:
    ok: bool
    scopes_checked: list[str]
    protection_regressions: list[dict[str, Any]]
    utility_regressions: list[dict[str, Any]]
    baseline_size: int

    def public(self) -> dict[str, Any]:
        return asdict(self)


def load_baseline(path: Path = BASELINE) -> dict[str, list[str]]:
    data: dict[str, list[str]] = json.loads(path.read_text())
    return data


def baseline_from(results: list[CaseResult]) -> dict[str, list[str]]:
    return {
        "protected": sorted(r.id for r in results if r.should_protect and r.outcome == "TP"),
        "utility": sorted(r.id for r in results if not r.should_protect and r.outcome == "TN"),
    }


def gate(
    bundle: PolicyBundle,
    evaluator: Evaluator,
    baseline: dict[str, list[str]],
    cases: list[dict[str, Any]],
) -> GateReport:
    """A candidate bundle passes if every scope still protects every baseline-protected case."""
    protected, utility = set(baseline["protected"]), set(baseline["utility"])
    prot_reg: list[dict[str, Any]] = []
    util_reg: list[dict[str, Any]] = []
    scopes: list[str] = []
    for tenant, user in bundle.scopes():
        policy = bundle.base if tenant == "*" else bundle.effective(tenant, user)
        scope = "base" if tenant == "*" else f"{tenant}/{user}" if user else tenant
        scopes.append(scope)
        for r in evaluator.evaluate(policy, cases):
            if r.id in protected and r.outcome != "TP":
                prot_reg.append({"scope": scope, "case": r.id, "category": r.category, **r.detail})
            if r.id in utility and r.outcome != "TN":
                util_reg.append({"scope": scope, "case": r.id, "category": r.category, **r.detail})
    return GateReport(not prot_reg, scopes, prot_reg, util_reg, len(protected))
