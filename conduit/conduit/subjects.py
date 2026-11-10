"""Synthetic subject directory. These people are not real."""

from __future__ import annotations

from conduit.models import Subject

# Control-plane list the redactor and the demo UI share. Erasure removes a
# subject from the log and the indexes; it does not edit this source file.
SUBJECTS: tuple[Subject, ...] = (
    Subject("subj-ava-chen", "Ava Chen", "ava.chen@northwind.example"),
    Subject("subj-leo-martinez", "Leo Martinez", "leo.martinez@northwind.example"),
    Subject("subj-mina-okonkwo", "Mina Okonkwo", "mina.okonkwo@northwind.example"),
    Subject("subj-jonas-berg", "Jonas Berg", "jonas.berg@northwind.example"),
)

BY_ID: dict[str, Subject] = {subject.id: subject for subject in SUBJECTS}
