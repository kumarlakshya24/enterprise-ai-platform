"""Dollars per thousand requests.

Variable cost is computed on the 1,000-request mix in eval/workload.yaml.
Fixed cost (endpoint hours, NAT hours, keys, tasks, the load balancer, transit
gateway attachments) is smeared across the requests/day you pass in. The two
are not the same number, and the console shows both.

Prices come from eval/pricing.yaml. Quantities come from the synth, so a new
endpoint shows up on the bill without a second edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from skyline.load import load_pricing, load_workload
from skyline.walk import iter_resources

MILLION = Decimal(1_000_000)
THOUSAND = Decimal(1000)
ZERO = Decimal(0)
PRESETS = (1_000, 10_000, 100_000, 1_000_000)


@dataclass(frozen=True)
class Qty:
    interface_az: int
    interface_endpoints: int
    cmks: int
    tgw_attachments: int
    task_vcpus: Decimal
    task_memory_gb: Decimal
    load_balancers: int
    guardrails: int


def quantities(assembly: dict[str, Any]) -> Qty:
    interface_az = 0
    interface_endpoints = 0
    cmks = 0
    attachments = 0
    load_balancers = 0
    guardrails = 0
    task_defs: dict[str, tuple[Decimal, Decimal]] = {}
    for stack, logical, resource in iter_resources(assembly):
        kind = resource["Type"]
        props = resource["Properties"]
        if kind == "AWS::EC2::VPCEndpoint" and props.get("VpcEndpointType") == "Interface":
            interface_endpoints += 1
            interface_az += len(props.get("SubnetIds", []))
        elif kind == "AWS::KMS::Key":
            cmks += 1
        elif kind == "AWS::EC2::TransitGatewayAttachment":
            attachments += 1
        elif kind == "AWS::ElasticLoadBalancingV2::LoadBalancer":
            load_balancers += 1
        elif kind == "AWS::Bedrock::Guardrail":
            guardrails += 1
        elif kind == "AWS::ECS::TaskDefinition":
            task_defs[f"{stack}/{logical}"] = (
                Decimal(int(props["Cpu"])) / Decimal(1024),
                Decimal(int(props["Memory"])) / Decimal(1024),
            )
    vcpu = ZERO
    memory = ZERO
    for stack, _logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::ECS::Service":
            continue
        ref = resource["Properties"]["TaskDefinition"]["Ref"]
        cpu, mem = task_defs[f"{stack}/{ref}"]
        count = Decimal(int(resource["Properties"]["DesiredCount"]))
        vcpu += cpu * count
        memory += mem * count
    return Qty(
        interface_az=interface_az,
        interface_endpoints=interface_endpoints,
        cmks=cmks,
        tgw_attachments=attachments,
        task_vcpus=vcpu,
        task_memory_gb=memory,
        load_balancers=load_balancers,
        guardrails=guardrails,
    )


def _model_cost(count: int, tokens_in: int, tokens_out: int, model: dict[str, Any]) -> Decimal:
    inputs = Decimal(count * tokens_in) / MILLION * model["input_per_mtok"]
    outputs = Decimal(count * tokens_out) / MILLION * model["output_per_mtok"]
    return inputs + outputs


def _qdec(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _q(value: Decimal) -> str:
    return f"{_qdec(value):.6f}"


def network_crossover_rpd(
    endpoint_daily: Decimal,
    nat_daily: Decimal,
    endpoint_per_1k: Decimal,
    nat_per_1k: Decimal,
) -> int | None:
    """Requests/day where endpoint hours plus bytes cost less than one NAT.

    None means the per-GB savings never pay the hourly premium back.
    """
    fixed_gap = endpoint_daily - nat_daily
    byte_savings = nat_per_1k - endpoint_per_1k
    if byte_savings <= 0:
        return None
    if fixed_gap <= 0:
        return 0
    raw = fixed_gap * THOUSAND / byte_savings
    return int(raw.to_integral_value(rounding=ROUND_HALF_UP))


def unit_crossover_rpd(
    skyline_variable: Decimal,
    naive_variable: Decimal,
    skyline_fixed_daily: Decimal,
    naive_fixed_daily: Decimal,
) -> int | None:
    """Requests/day above which Skyline's fully loaded unit cost is lower."""
    advantage = naive_variable - skyline_variable
    penalty = skyline_fixed_daily - naive_fixed_daily
    if advantage <= 0:
        return None
    if penalty <= 0:
        return 0
    raw = penalty * THOUSAND / advantage
    return int(raw.to_integral_value(rounding=ROUND_HALF_UP))


def project(assembly: dict[str, Any], requests_per_day: int) -> dict[str, Any]:
    if requests_per_day < 1:
        raise ValueError("requests_per_day must be positive")
    pricing = load_pricing()
    workload = load_workload()
    rates = pricing["rates"]
    qty = quantities(assembly)
    counts = [item["count"] for item in workload["requests"]]
    if sum(counts) != 1000:
        raise ValueError(f"the FinOps unit is 1,000 requests, the mix sums to {sum(counts)}")

    skyline_model = ZERO
    naive_model = ZERO
    payload_bytes = 0
    scanned_chars = 0
    full_chars = 0
    tgw_bytes = 0
    by_class: list[dict[str, Any]] = []
    for item in workload["requests"]:
        sky = _model_cost(
            item["count"],
            item["input_tokens"],
            item["output_tokens"],
            pricing["models"][item["skyline_model"]],
        )
        naive = _model_cost(
            item["count"], item["input_tokens"], item["output_tokens"], pricing["models"][item["naive_model"]]
        )
        skyline_model += sky
        naive_model += naive
        tokens = item["count"] * (item["input_tokens"] + item["output_tokens"])
        payload_bytes += tokens * pricing["bytes_per_token"]
        scanned_chars += item["count"] * item["user_chars"]
        scanned_chars += item["count"] * item["output_tokens"] * pricing["bytes_per_token"]
        full_chars += tokens * pricing["bytes_per_token"]
        tgw_bytes += tokens * pricing["bytes_per_token"] * item["tgw_crossings"]
        by_class.append(
            {
                "count": item["count"],
                "id": item["id"],
                "label": item["label"],
                "naive_model": item["naive_model"],
                "naive_usd": _q(naive),
                "skyline_model": item["skyline_model"],
                "skyline_usd": _q(sky),
            }
        )

    hours = Decimal(pricing["hours_per_day"])
    days = Decimal(pricing["days_per_month"])
    gb = Decimal(1024**3)
    payload_gb = Decimal(payload_bytes) / gb
    tgw_gb = Decimal(tgw_bytes) / gb

    endpoint_daily = Decimal(qty.interface_az) * rates["interface_endpoint_az_hour"] * hours
    nat_gateways = Decimal(pricing["naive"]["nat_gateways"])
    nat_daily = nat_gateways * rates["nat_gateway_hour"] * hours
    endpoint_data = payload_gb * rates["interface_endpoint_gb"]
    nat_data = payload_gb * rates["nat_gb"]
    tgw_data = tgw_gb * rates["tgw_gb"]
    tgw_daily = Decimal(qty.tgw_attachments) * rates["tgw_attachment_hour"] * hours

    text_units = Decimal(scanned_chars) / Decimal(pricing["text_unit_chars"])
    per_unit = (
        rates["guardrail_content_per_1k_units"]
        + rates["guardrail_topic_per_1k_units"]
        + rates["guardrail_pii_per_1k_units"]
    ) / THOUSAND
    guardrail = text_units * per_unit if qty.guardrails else ZERO
    full_units = Decimal(full_chars) / Decimal(pricing["text_unit_chars"])
    guardrail_full = full_units * per_unit

    kms_requests = Decimal(1000) * pricing["data_keys_per_request"]
    kms_request_cost = kms_requests / Decimal(10_000) * rates["kms_per_10k_requests"]
    skyline_keys_daily = Decimal(qty.cmks) * rates["cmk_month"] / days
    naive_keys_daily = Decimal(pricing["naive"]["cmks"]) * rates["cmk_month"] / days

    compute_daily = (
        qty.task_vcpus * rates["fargate_vcpu_hour"] + qty.task_memory_gb * rates["fargate_gb_hour"]
    ) * hours
    lcus = Decimal(pricing["assumed_lcus"])
    alb_daily = Decimal(qty.load_balancers) * (rates["alb_hour"] + lcus * rates["alb_lcu_hour"]) * hours

    rpd = Decimal(requests_per_day)

    def smear(daily: Decimal) -> Decimal:
        return daily * THOUSAND / rpd

    lines = [
        ("model", "Model tokens", skyline_model, naive_model, "variable"),
        ("guardrail", "Guardrail, user turn and output", guardrail, ZERO, "variable"),
        ("network-data", "Network bytes", endpoint_data, nat_data, "variable"),
        ("tgw-data", "Transit gateway bytes", tgw_data, ZERO, "variable"),
        ("kms-requests", "KMS data keys, 1% cache miss", kms_request_cost, kms_request_cost, "variable"),
        ("network-fixed", "Endpoint hours or NAT hours", smear(endpoint_daily), smear(nat_daily), "fixed"),
        ("tgw-fixed", "Transit gateway attachments", smear(tgw_daily), ZERO, "fixed"),
        ("kms-keys", "CMK months, smeared", smear(skyline_keys_daily), smear(naive_keys_daily), "fixed"),
        ("compute", "Fargate, same three services", smear(compute_daily), smear(compute_daily), "fixed"),
        ("alb", "Internal load balancer", smear(alb_daily), smear(alb_daily), "fixed"),
    ]
    quantized = [
        (line_id, label, _qdec(sky), _qdec(naive), kind) for line_id, label, sky, naive, kind in lines
    ]
    rendered = [
        {
            "id": line_id,
            "kind": kind,
            "label": label,
            "naive_usd": _q(naive),
            "skyline_usd": _q(sky),
        }
        for line_id, label, sky, naive, kind in quantized
    ]
    # Totals are the sum of the rounded lines, so the table adds up.
    skyline_total = sum((sky for _, _, sky, _, _ in quantized), start=ZERO)
    naive_total = sum((naive for _, _, _, naive, _ in quantized), start=ZERO)
    skyline_variable = sum((sky for _, _, sky, _, kind in lines if kind == "variable"), start=ZERO)
    naive_variable = sum((naive for _, _, _, naive, kind in lines if kind == "variable"), start=ZERO)
    skyline_fixed_daily = endpoint_daily + tgw_daily + skyline_keys_daily + compute_daily + alb_daily
    naive_fixed_daily = nat_daily + naive_keys_daily + compute_daily + alb_daily

    def share(value: Decimal, total: Decimal) -> float:
        if total <= 0:
            return 0.0
        return float(value / total)

    groups = {
        "model": ("model",),
        "guardrail": ("guardrail",),
        "network": ("network-data", "network-fixed", "tgw-data", "tgw-fixed"),
        "platform": ("kms-requests", "kms-keys", "compute", "alb"),
    }
    bars = []
    for name, ids in groups.items():
        sky = sum((sky for line_id, _, sky, _, _ in lines if line_id in ids), start=ZERO)
        naive = sum((naive for line_id, _, _, naive, _ in lines if line_id in ids), start=ZERO)
        bars.append({"id": name, "naive_usd": _q(naive), "skyline_usd": _q(sky)})

    return {
        "bars": bars,
        "bytes_per_1k": payload_bytes,
        "classes": by_class,
        "crossover_rpd": unit_crossover_rpd(
            skyline_variable, naive_variable, skyline_fixed_daily, naive_fixed_daily
        ),
        "endpoint_vs_nat_rpd": network_crossover_rpd(endpoint_daily, nat_daily, endpoint_data, nat_data),
        "guardrail_full_prompt_per_1k": _q(guardrail_full),
        "guardrail_per_1k": _q(guardrail),
        "lines": rendered,
        "model_savings_per_1k": _q(naive_model - skyline_model),
        "naive_fixed_daily": _q(naive_fixed_daily),
        "naive_total": _q(naive_total),
        "naive_variable": _q(naive_variable),
        "quantities": {
            "cmks": qty.cmks,
            "guardrails": qty.guardrails,
            "interface_az": qty.interface_az,
            "interface_endpoints": qty.interface_endpoints,
            "load_balancers": qty.load_balancers,
            "task_memory_gb": _q(qty.task_memory_gb),
            "task_vcpus": _q(qty.task_vcpus),
            "tgw_attachments": qty.tgw_attachments,
        },
        "requests_per_day": requests_per_day,
        "skyline_fixed_daily": _q(skyline_fixed_daily),
        "skyline_total": _q(skyline_total),
        "skyline_variable": _q(skyline_variable),
        "endpoint_daily": _q(endpoint_daily),
        "nat_daily": _q(nat_daily),
        "shares": {
            "naive_model": share(naive_model, naive_total),
            "skyline_model": share(skyline_model, skyline_total),
        },
    }
