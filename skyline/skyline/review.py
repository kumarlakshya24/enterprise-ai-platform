"""Well-Architected notes tied to resources that actually exist in the synth."""

from __future__ import annotations

from typing import Any

from skyline.walk import iter_resources

PILLARS: tuple[dict[str, Any], ...] = (
    {
        "evidence": ["log-archive/OrgTrail", "finops/PlatformBudget"],
        "gap": "The gate reviews the template. It does not watch a running account.",
        "id": "operational-excellence",
        "question": "How do you know a platform change is the one you reviewed?",
        "summary": (
            "The synth is deterministic. CI diffs it against the fixture and runs the "
            "named invariant gate. A security group opened to the world fails no-world-cidrs "
            "and names the resource."
        ),
        "title": "Operational excellence",
    },
    {
        "evidence": [
            "security/TenantKeyNorthwind",
            "security/BedrockRuntimeEndpoint",
            "security/BedrockPrivateZone",
            "security/Guardrail",
        ],
        "gap": "IAM cannot prove the task called ApplyGuardrail. The endpoint policy limits who may call.",
        "id": "security",
        "question": "What is allowed to reach a model, and with whose key?",
        "summary": (
            "Workload subnets have no internet route. Only the Aegis task role is on the "
            "Bedrock endpoint policy. Lumen and Switchboard deny bedrock:*. Each tenant "
            "bucket uses its own CMK, and the key refuses a call without that tenant's "
            "encryption context. The guardrail is a resource the task is pinned to."
        ),
        "title": "Security",
    },
    {
        "evidence": ["security/AegisService", "network/TransitGateway"],
        "gap": "The transit gateway is a hub. Losing it stops every cross-account call.",
        "id": "reliability",
        "question": "What happens to a single bad AZ, and what is still a single point?",
        "summary": (
            "Each VPC has two private subnets and each service asks for two tasks. The "
            "model path does not depend on a NAT gateway. The transit gateway still is one "
            "control plane for every account-to-account packet."
        ),
        "title": "Reliability",
    },
    {
        "evidence": ["switchboard/SwitchboardService", "security/BedrockRuntimeEndpoint"],
        "gap": "The latency numbers for Bedrock and KMS in the report are projections.",
        "id": "performance",
        "question": "Where does the request spend time, and what did we refuse to guess?",
        "summary": (
            "Switchboard still chooses the model. The Bedrock call stays on an interface "
            "endpoint in the security VPC, so it does not cross the public internet. This "
            "repo measures synth time and the local guardrail stub. It does not measure "
            "a live Bedrock round trip."
        ),
        "title": "Performance efficiency",
    },
    {
        "evidence": ["finops/PlatformBudget", "security/Guardrail"],
        "gap": "The prices are a frozen list, not the AWS Price List API and not an invoice.",
        "id": "cost",
        "question": "What does a thousand requests cost, and which line is the platform?",
        "summary": (
            "Model mix is the large line. The guardrail is the next one, because it is "
            "priced per text unit, so the design scans the user turn and the output and "
            "not the retrieved context. Private endpoints cost more per day than one NAT "
            "gateway. The console shows that premium instead of folding it into a single "
            "savings number. A budget resource in the finops account is the ceiling, "
            "not the forecast."
        ),
        "title": "Cost optimization",
    },
    {
        "evidence": ["switchboard/SwitchboardService", "security/AegisTaskDefinition"],
        "gap": "No carbon number is claimed. Smaller models are a token reduction, not a footprint audit.",
        "id": "sustainability",
        "question": "Which requests never needed the largest model?",
        "summary": (
            "The mix sends FAQ and cited answers to a Haiku-class model and pins "
            "confidential text to a local model. The agent step still uses a Sonnet-class "
            "model. That split is the sustainability control this platform actually has."
        ),
        "title": "Sustainability",
    },
)


def review(assembly: dict[str, Any]) -> list[dict[str, Any]]:
    known = {f"{stack}/{logical}" for stack, logical, _resource in iter_resources(assembly)}
    rows: list[dict[str, Any]] = []
    for pillar in PILLARS:
        missing = [item for item in pillar["evidence"] if item not in known]
        rows.append({**pillar, "missing": missing, "ok": not missing})
    return rows
