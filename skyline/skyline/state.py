"""One payload for the console, the report, and the tests."""

from __future__ import annotations

import json
import time
from typing import Any

from skyline.diffing import diff
from skyline.finops import PRESETS, project
from skyline.guardrail import bench, score_cases
from skyline.invariants import MUTATION_PRIMARY, evaluate
from skyline.load import load_cases
from skyline.mutations import mutate
from skyline.platform import assemble
from skyline.review import review
from skyline.synth import canonical, digest

# Projections. Not measurements. Kept next to the measured stub number so the
# report cannot blur them together.
PROJECTIONS = (
    {
        "basis": "Order of magnitude for a Bedrock Guardrails round trip. This demo does not call Bedrock.",
        "hop": "Bedrock guardrail round trip",
        "ms": 25,
    },
    {
        "basis": "A typical GenerateDataKey on a cache miss. The mix assumes a 1% miss.",
        "hop": "KMS GenerateDataKey, cache miss",
        "ms": 4,
    },
    {
        "basis": "The application cache. Not a resource in this synth.",
        "hop": "KMS, cache hit",
        "ms": 0,
    },
    {
        "basis": "Internet RTT the private endpoint removes. Not measured from this machine.",
        "hop": "Public internet RTT avoided",
        "ms": "20-40",
    },
)


def _clip(value: Any, limit: int = 240) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _accounts(assembly: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for account in assembly["manifest"]["accounts"]:
        resources = assembly["stacks"][account["name"]]["Resources"]
        endpoints = 0
        cmks = 0
        services = 0
        for resource in resources.values():
            if (
                resource["Type"] == "AWS::EC2::VPCEndpoint"
                and resource["Properties"].get("VpcEndpointType") == "Interface"
            ):
                endpoints += 1
            elif resource["Type"] == "AWS::KMS::Key":
                cmks += 1
            elif resource["Type"] == "AWS::ECS::Service":
                services += 1
        rows.append(
            {
                "blurb": account["blurb"],
                "cmks": cmks,
                "id": account["id"],
                "interfaceEndpoints": endpoints,
                "name": account["name"],
                "resources": len(resources),
                "services": services,
            }
        )
    return rows


def _kms_rows(assembly: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for tenant in assembly["manifest"]["tenants"]:
        rows.append(
            {
                "alias": f"alias/skyline/{tenant['id']}",
                "bucket": f"skyline-lumen-{tenant['id']}-docs",
                "context": f"tenant={tenant['id']}",
                "display": tenant["display"],
                "key": f"skyline-tenant-{tenant['id']}",
            }
        )
    return rows


def build_state(mutation: str = "clean", requests_per_day: int = 100_000) -> dict[str, Any]:
    started = time.perf_counter()
    clean = assemble()
    assembly = mutate(clean, mutation)
    synth_ms = (time.perf_counter() - started) * 1000
    text = canonical(assembly)
    clean_text = canonical(clean)
    changes = diff(clean, assembly) if mutation != "clean" else []
    rules = evaluate(assembly)
    cases = load_cases()
    scored = score_cases(cases)
    timing = bench(cases, rounds=30)
    pillars = review(clean)
    finops = project(clean, requests_per_day)
    presets = []
    for rpd in PRESETS:
        item = project(clean, rpd)
        presets.append(
            {
                "naive_total": item["naive_total"],
                "requests_per_day": rpd,
                "skyline_total": item["skyline_total"],
            }
        )
    return {
        "accounts": _accounts(assembly),
        "bench": timing,
        "cleanHash": digest(clean_text),
        "diff": {
            "changes": [
                {
                    "after": _clip(change["after"]),
                    "before": _clip(change["before"]),
                    "op": change["op"],
                    "path": change["path"],
                }
                for change in changes[:12]
            ],
            "count": len(changes),
        },
        "finops": finops,
        "guardrail": scored,
        "hash": digest(text),
        "invariants": rules,
        "kms": _kms_rows(clean),
        "manifest": clean["manifest"],
        "mutation": mutation,
        "mutations": [{"id": name, "rule": rule} for name, rule in MUTATION_PRIMARY.items()],
        "path": [
            "Corporate network",
            "Internal ALB",
            "Aegis",
            "Guardrail",
            "Switchboard",
            "Bedrock endpoint",
        ],
        "pillars": pillars,
        "presets": presets,
        "projections": list(PROJECTIONS),
        "region": clean["manifest"]["region"],
        "resourceCount": sum(len(stack["Resources"]) for stack in assembly["stacks"].values()),
        "shortHash": digest(text)[:12],
        "synthMs": round(synth_ms, 2),
        "violationCount": sum(1 for row in rules if not row["ok"]),
    }
