"""Synthetic CDC. Every name, address, and number in here is fictional."""

from __future__ import annotations

from conduit.models import Incoming

POISON = "[[REDACTOR_UNAVAILABLE]]"


def _event(
    event_id: str,
    op: str,
    doc_id: str,
    version: int,
    title: str,
    text: str,
    subjects: tuple[str, ...] = (),
    source_ts: str = "2026-11-02T15:00:00+00:00",
) -> Incoming:
    return Incoming(event_id, op, doc_id, version, title, text, subjects, source_ts)


def _paragraph(seed: str, width: int = 200) -> str:
    """Pad with a token derived from the seed, not a shared filler.

    A repeated shared filler dominates the hash embedder and collides with
    the one word a query is looking for. A per-paragraph pad stays out of
    every other document.
    """
    text = seed.strip()
    while text and len(text) < width:
        text = f"{text} {seed.strip()}"
    return text[:width]


def demo_events() -> list[Incoming]:
    """A short script the UI replays. Paragraphs are long enough to stay one chunk each."""
    leave_p1 = (
        "Northwind annual leave. Full-time staff accrue 20 days of paid leave each calendar year. "
        "Requests go in the scheduling tool five working days ahead, and the manager confirms cover."
    )
    leave_p2 = (
        "Carryover. Staff may carry 5 unused days into the next year. Carried days expire on 31 March. "
        "Days above that cap are forfeited and are not paid out at year end."
    )
    leave_p3 = (
        "Parental leave sits outside the annual cap. Managers record the return date before leave starts, "
        "and the team rota names the person covering the role."
    )
    leave_p2_v2 = (
        "Carryover. Staff may carry 8 unused days into the next year. Carried days expire on 30 June. "
        "The old March expiry no longer applies to this edition of the handbook."
    )
    expenses = "\n\n".join(
        [
            (
                "Expense reimbursement. Submit mileage reimbursement with a receipt within 45 days of travel. "
                "The trip id is written on the receipt before it is scanned."
            ),
            (
                "Mileage is paid at the posted rate. A missing receipt delays reimbursement until the copy arrives "
                "from the traveller, and the Friday run will skip that line."
            ),
            (
                "The finance desk matches each receipt to the trip id before the Friday payment run. "
                "Unmatched receipts stay in the holding queue over the weekend."
            ),
        ]
    )
    ticket_ava = "\n\n".join(
        [
            (
                "Ava Chen (ava.chen@northwind.example) called about invoice 441. "
                "Phone 415-555-0148. Card on file 4111 1111 1111 1111. "
                "She asked for the receipt to be sent again."
            ),
            (
                "The invoice covers a replacement headset shipped to the Austin desk in October, "
                "after the previous unit failed during a site visit."
            ),
        ]
    )
    ticket_leo = (
        "Leo Martinez (leo.martinez@northwind.example) asked when the Thursday deploy window opens "
        "and whether the canary still takes ten percent of read traffic."
    )
    incident = (
        "Mina Okonkwo (mina.okonkwo@northwind.example) held the incident bridge for the paging delay "
        "and wrote the timeline into the handoff note before the next shift."
    )
    runbook = "\n\n".join(
        [
            (
                "Deploy runbook. Freeze merges at 16:00 local. Roll forward only with the on-call acknowledgement, "
                "and do not bypass the canary because a ticket is loud."
            ),
            (
                "The canary takes ten percent of read traffic for twenty minutes before the rest of the fleet moves. "
                "Abort if error budget burn pages during that window."
            ),
        ]
    )
    mixed = "\n\n".join(
        [
            (
                "Ava Chen (ava.chen@northwind.example) asked for an access review of the finance folder "
                "before the quarter close, and she wants the extra grants listed."
            ),
            (
                "Leo Martinez (leo.martinez@northwind.example) still needs a badge for the Austin desk. "
                "The badge office can print it once the photo on file is current."
            ),
        ]
    )
    jonas = (
        "Jonas Berg (jonas.berg@northwind.example) filed a benefits form. "
        "Reference 219-09-9999 is synthetic and should never be embedded in the clear."
    )
    return [
        _event(
            "demo-leave-1",
            "upsert",
            "handbook-leave",
            1,
            "Annual leave",
            "\n\n".join([leave_p1, leave_p2, leave_p3]),
            source_ts="2026-11-02T15:00:00+00:00",
        ),
        _event(
            "demo-exp-1",
            "upsert",
            "handbook-expenses",
            1,
            "Expenses",
            expenses,
            source_ts="2026-11-02T15:00:01+00:00",
        ),
        _event(
            "demo-441",
            "upsert",
            "ticket-441",
            1,
            "Ticket 441",
            ticket_ava,
            ("subj-ava-chen",),
            source_ts="2026-11-02T15:00:02+00:00",
        ),
        _event(
            "demo-442",
            "upsert",
            "ticket-442",
            1,
            "Ticket 442",
            ticket_leo,
            ("subj-leo-martinez",),
            source_ts="2026-11-02T15:00:03+00:00",
        ),
        _event(
            "demo-inc",
            "upsert",
            "incident-17",
            1,
            "Incident 17",
            incident,
            ("subj-mina-okonkwo",),
            source_ts="2026-11-02T15:00:04+00:00",
        ),
        _event(
            "demo-run",
            "upsert",
            "runbook-deploy",
            1,
            "Deploy runbook",
            runbook,
            source_ts="2026-11-02T15:00:05+00:00",
        ),
        _event(
            "demo-443",
            "upsert",
            "ticket-443",
            1,
            "Ticket 443",
            mixed,
            ("subj-ava-chen", "subj-leo-martinez"),
            source_ts="2026-11-02T15:00:06+00:00",
        ),
        _event(
            "demo-jonas",
            "upsert",
            "note-jonas",
            1,
            "Benefits note",
            jonas,
            ("subj-jonas-berg",),
            source_ts="2026-11-02T15:00:07+00:00",
        ),
        _event(
            "demo-leave-2",
            "upsert",
            "handbook-leave",
            2,
            "Annual leave",
            "\n\n".join([leave_p1, leave_p2_v2, leave_p3]),
            source_ts="2026-11-02T15:04:00+00:00",
        ),
        _event(
            "demo-poison",
            "upsert",
            "poison-1",
            1,
            "Unreadable",
            f"This page could not be redacted. {POISON}",
            source_ts="2026-11-02T15:04:01+00:00",
        ),
    ]


def eval_phases(seed: int = 17, docs: int = 180) -> dict[str, list[Incoming]]:
    """Deterministic phases. Recall docs, updates, deletes, and a few people."""
    del seed  # the generator is deterministic without drawing from a PRNG
    initial: list[Incoming] = []
    for index in range(docs):
        keyword = f"kwdoc{index}"
        paragraphs = [
            _paragraph(f"{keyword} is the routing key for document {index}. {keyword} {keyword} {keyword}"),
            _paragraph(
                f"Background for document {index} covers ordinary field procedure and nothing personal."
            ),
            _paragraph(
                f"Closing note for document {index} records the review date and the desk that owns it."
            ),
        ]
        subjects: tuple[str, ...] = ()
        if index == 20:
            paragraphs[0] = _paragraph(
                "Ava Chen (ava.chen@northwind.example) is the only person on the Austin headset invoice."
            )
            subjects = ("subj-ava-chen",)
        elif index == 21:
            paragraphs[0] = _paragraph(
                "Leo Martinez (leo.martinez@northwind.example) owns the Thursday deploy question and nothing else."
            )
            subjects = ("subj-leo-martinez",)
        elif index == 22:
            paragraphs[0] = _paragraph(
                "Mina Okonkwo (mina.okonkwo@northwind.example) ran the paging bridge and wrote the timeline."
            )
            subjects = ("subj-mina-okonkwo",)
        elif index == 23:
            paragraphs[0] = _paragraph(
                "Ava Chen (ava.chen@northwind.example) asked for a finance-folder access review on this ticket."
            )
            paragraphs[1] = _paragraph(
                "Leo Martinez (leo.martinez@northwind.example) still needs a badge for the same Austin desk."
            )
            subjects = ("subj-ava-chen", "subj-leo-martinez")
        initial.append(
            _event(
                f"eval-{index}-v1",
                "upsert",
                f"doc-{index}",
                1,
                f"Document {index}",
                "\n\n".join(paragraphs),
                subjects,
                source_ts=f"2026-11-01T12:{index % 60:02d}:{index % 60:02d}+00:00",
            )
        )

    updates: list[Incoming] = []
    for index in range(30, 60):
        keyword = f"kwdoc{index}"
        paragraphs = [
            _paragraph(f"{keyword} is the routing key for document {index}. {keyword} {keyword} {keyword}"),
            _paragraph(
                f"Background for document {index} covers ordinary field procedure and nothing personal."
            ),
            _paragraph(
                f"Revised closing note for document {index}. The March expiry language no longer applies."
            ),
        ]
        updates.append(
            _event(
                f"eval-{index}-v2",
                "upsert",
                f"doc-{index}",
                2,
                f"Document {index}",
                "\n\n".join(paragraphs),
                source_ts="2026-11-03T09:00:00+00:00",
            )
        )

    deletes = [
        _event(
            f"eval-del-{index}",
            "delete",
            f"doc-{index}",
            2,
            f"Document {index}",
            "",
            source_ts="2026-11-03T10:00:00+00:00",
        )
        for index in range(60, 68)
    ]
    poison = [
        _event(
            f"eval-poison-{index}",
            "upsert",
            f"poison-{index}",
            1,
            "Unreadable",
            f"detector down {POISON}",
            source_ts="2026-11-03T11:00:00+00:00",
        )
        for index in range(3)
    ]
    return {"initial": initial, "updates": updates, "deletes": deletes, "poison": poison}


def recall_queries(n: int = 20) -> list[tuple[str, str]]:
    """Query, expected doc id. The keyword is unique to that document."""
    return [(f"kwdoc{index}", f"doc-{index}") for index in range(n)]
