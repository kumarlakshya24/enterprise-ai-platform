"""Planted breaks. Each one is a mistake a platform change actually makes."""

from __future__ import annotations

import copy
from typing import Any


def mutation_names() -> tuple[str, ...]:
    return tuple(sorted(_MUTATIONS))


def mutate(assembly: dict[str, Any], name: str) -> dict[str, Any]:
    if name == "clean":
        return assembly
    mutated = copy.deepcopy(assembly)
    if name not in _MUTATIONS:
        known = ", ".join(sorted(_MUTATIONS))
        raise KeyError(f"unknown mutation {name!r}; expected {known}")
    _MUTATIONS[name](mutated)
    return mutated


def _open_sg(assembly: dict[str, Any]) -> None:
    group = assembly["stacks"]["security"]["Resources"]["AegisSecurityGroup"]
    group["Properties"]["SecurityGroupIngress"].append(
        {
            "CidrIp": "0.0.0.0/0",
            "Description": "opened during a demo",
            "FromPort": 8443,
            "IpProtocol": "tcp",
            "ToPort": 8443,
        }
    )


def _shared_cmk(assembly: dict[str, Any]) -> None:
    """Point Helix and Brightline at Northwind's key. One grant then reads both."""
    northwind = "arn:aws:kms:us-east-1:100000000020:key/skyline-tenant-northwind"
    for logical in ("DocBucketHelix", "DocBucketBrightline"):
        bucket = assembly["stacks"]["lumen"]["Resources"][logical]
        default = bucket["Properties"]["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
        default["ServerSideEncryptionByDefault"]["KMSMasterKeyID"] = northwind


def _drop_guardrail(assembly: dict[str, Any]) -> None:
    del assembly["stacks"]["security"]["Resources"]["Guardrail"]


def _public_route(assembly: dict[str, Any]) -> None:
    resources = assembly["stacks"]["security"]["Resources"]
    resources["InternetGateway"] = {
        "Properties": {"Tags": [{"Key": "Name", "Value": "skyline-igw"}]},
        "Type": "AWS::EC2::InternetGateway",
    }
    resources["GatewayAttachment"] = {
        "Properties": {"InternetGatewayId": {"Ref": "InternetGateway"}, "VpcId": {"Ref": "SecurityVpc"}},
        "Type": "AWS::EC2::VPCGatewayAttachment",
    }
    resources["SecurityRouteToInternetAz1"] = {
        "Properties": {
            "DestinationCidrBlock": "0.0.0.0/0",
            "GatewayId": {"Ref": "InternetGateway"},
            "RouteTableId": {"Ref": "SecurityRouteTableAz1"},
        },
        "Type": "AWS::EC2::Route",
    }


def _lumen_bedrock(assembly: dict[str, Any]) -> None:
    role = assembly["stacks"]["lumen"]["Resources"]["LumenTaskRole"]
    statements = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"] = [
        statement for statement in statements if statement.get("Sid") != "DenyBedrock"
    ]
    statements = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    statements.append(
        {
            "Action": "bedrock:InvokeModel",
            "Effect": "Allow",
            "Resource": "*",
            "Sid": "CallBedrockDirectly",
        }
    )


def _wildcard_kms(assembly: dict[str, Any]) -> None:
    key = assembly["stacks"]["security"]["Resources"]["TenantKeyHelix"]
    key["Properties"]["KeyPolicy"]["Statement"].append(
        {
            "Action": "kms:*",
            "Effect": "Allow",
            "Principal": "*",
            "Resource": "*",
            "Sid": "Anyone",
        }
    )


def _share_bedrock_dns(assembly: dict[str, Any]) -> None:
    zone = assembly["stacks"]["security"]["Resources"]["BedrockPrivateZone"]
    zone["Properties"]["VPCs"].append({"VPCId": {"Ref": "LumenVpc"}, "VPCRegion": "us-east-1"})


_MUTATIONS: dict[str, Any] = {
    "drop-guardrail": _drop_guardrail,
    "lumen-bedrock": _lumen_bedrock,
    "open-sg": _open_sg,
    "public-route": _public_route,
    "share-bedrock-dns": _share_bedrock_dns,
    "shared-cmk": _shared_cmk,
    "wildcard-kms": _wildcard_kms,
}
