"""Load the YAML inputs. The files are the control plane; code is the synth."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict, cast

import yaml

from skyline.paths import EVAL


class TenantSpec(TypedDict):
    id: str
    display: str


class VpcSpec(TypedDict):
    cidr: str
    subnets: list[str]


class PlatformSpec(TypedDict):
    region: str
    corporate_cidr: str
    azs: list[str]
    tenants: list[TenantSpec]
    vpcs: dict[str, VpcSpec]


class WorkItem(TypedDict):
    id: str
    label: str
    count: int
    skyline_model: str
    naive_model: str
    input_tokens: int
    output_tokens: int
    user_chars: int
    tgw_crossings: int


class Workload(TypedDict):
    name: str
    description: str
    requests: list[WorkItem]


def _read(name: str) -> Any:
    return yaml.safe_load((EVAL / name).read_text(encoding="utf-8"))


def load_platform() -> PlatformSpec:
    raw = cast(dict[str, Any], _read("platform.yaml"))
    tenants = [TenantSpec(id=str(item["id"]), display=str(item["display"])) for item in raw["tenants"]]
    vpcs: dict[str, VpcSpec] = {}
    for name, body in raw["vpcs"].items():
        vpcs[str(name)] = VpcSpec(cidr=str(body["cidr"]), subnets=[str(item) for item in body["subnets"]])
    azs = [str(item) for item in raw["azs"]]
    for vpc in vpcs.values():
        if len(vpc["subnets"]) != len(azs):
            raise ValueError("each VPC needs one subnet per AZ")
    if len(azs) < 2:
        raise ValueError("the platform needs two AZs")
    return PlatformSpec(
        region=str(raw["region"]),
        corporate_cidr=str(raw["corporate_cidr"]),
        azs=azs,
        tenants=tenants,
        vpcs=vpcs,
    )


def load_workload() -> Workload:
    raw = cast(dict[str, Any], _read("workload.yaml"))
    items = [
        WorkItem(
            id=str(item["id"]),
            label=str(item["label"]),
            count=int(item["count"]),
            skyline_model=str(item["skyline_model"]),
            naive_model=str(item["naive_model"]),
            input_tokens=int(item["input_tokens"]),
            output_tokens=int(item["output_tokens"]),
            user_chars=int(item["user_chars"]),
            tgw_crossings=int(item["tgw_crossings"]),
        )
        for item in raw["requests"]
    ]
    return Workload(name=str(raw["name"]), description=str(raw["description"]), requests=items)


def load_pricing() -> dict[str, Any]:
    raw = cast(dict[str, Any], _read("pricing.yaml"))
    rates = {str(key): Decimal(str(value)) for key, value in raw["rates"].items()}
    models: dict[str, dict[str, Any]] = {}
    for name, body in raw["models"].items():
        models[str(name)] = {
            "label": str(body["label"]),
            "input_per_mtok": Decimal(str(body["input_per_mtok"])),
            "output_per_mtok": Decimal(str(body["output_per_mtok"])),
        }
    return {
        "currency": str(raw["currency"]),
        "bytes_per_token": int(raw["bytes_per_token"]),
        "text_unit_chars": int(raw["text_unit_chars"]),
        "hours_per_day": int(raw["hours_per_day"]),
        "days_per_month": int(raw["days_per_month"]),
        "assumed_lcus": int(raw["assumed_lcus"]),
        "data_keys_per_request": Decimal(str(raw["data_keys_per_request"])),
        "rates": rates,
        "models": models,
        "naive": {
            "nat_gateways": int(raw["naive"]["nat_gateways"]),
            "cmks": int(raw["naive"]["cmks"]),
            "guardrail": bool(raw["naive"]["guardrail"]),
        },
    }


def load_cases() -> list[dict[str, Any]]:
    raw = cast(dict[str, Any], _read("guardrail_cases.yaml"))
    cases: list[dict[str, Any]] = []
    for item in raw["cases"]:
        cases.append(
            {
                "id": str(item["id"]),
                "text": str(item["text"]),
                "expect": str(item["expect"]),
                "filter": str(item.get("filter", "")),
                "gap": str(item.get("gap", "")),
            }
        )
    return cases
