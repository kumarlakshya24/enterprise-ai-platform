"""Small CloudFormation-shaped builders. Not aws-cdk-lib.

Templates are plain dicts so a diff is a diff of JSON, with no asset hashes
and no account lookups. See ADR 0001.
"""

from __future__ import annotations

from typing import Any

TGW_ID = "tgw-skyline0001"
GUARDRAIL_NAME = "skyline-platform"
SYNTH = "fixture-cdk"

ACCOUNTS: dict[str, dict[str, str]] = {
    "network": {
        "id": "100000000010",
        "blurb": "Transit gateway. No tasks, no Bedrock, no keys.",
    },
    "security": {
        "id": "100000000020",
        "blurb": "Aegis, the guardrail, tenant keys, the internal load balancer.",
    },
    "lumen": {
        "id": "100000000030",
        "blurb": "Knowledge assistant and one document bucket per tenant.",
    },
    "switchboard": {
        "id": "100000000040",
        "blurb": "Model router. No Bedrock permission and no data bucket.",
    },
    "log-archive": {
        "id": "100000000050",
        "blurb": "Organization trail, with file validation.",
    },
    "finops": {
        "id": "100000000060",
        "blurb": "The monthly budget the console is priced against.",
    },
}


def tags(**names: str) -> list[dict[str, str]]:
    merged = {"Project": "skyline", **names}
    return [{"Key": key, "Value": value} for key, value in sorted(merged.items())]


def policy(statements: list[dict[str, Any]]) -> dict[str, Any]:
    return {"Version": "2012-10-17", "Statement": statements}


def key_arn(region: str, account_id: str, key_id: str) -> str:
    return f"arn:aws:kms:{region}:{account_id}:key/{key_id}"


def role_arn(account_id: str, role_name: str) -> str:
    return f"arn:aws:iam::{account_id}:role/{role_name}"


def bucket_arn(name: str) -> str:
    return f"arn:aws:s3:::{name}"


class Stack:
    """One account's template. Logical ids are the API of the diff."""

    def __init__(self, account: str, region: str, description: str) -> None:
        meta = ACCOUNTS[account]
        self.account = account
        self.account_id = meta["id"]
        self.region = region
        self.description = description
        self.resources: dict[str, dict[str, Any]] = {}
        self.outputs: dict[str, dict[str, Any]] = {}

    def add(
        self,
        logical_id: str,
        type_name: str,
        properties: dict[str, Any],
        *,
        meta: dict[str, Any] | None = None,
        retain: bool = False,
    ) -> str:
        if logical_id in self.resources:
            raise ValueError(f"duplicate logical id {logical_id} in {self.account}")
        body: dict[str, Any] = {"Type": type_name, "Properties": properties}
        if meta:
            body["Metadata"] = {"Skyline": meta}
        if retain:
            body["DeletionPolicy"] = "Retain"
        self.resources[logical_id] = body
        return logical_id

    def output(self, name: str, value: Any, description: str) -> None:
        self.outputs[name] = {"Description": description, "Value": value}

    def to_dict(self) -> dict[str, Any]:
        return {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": self.description,
            "Metadata": {
                "Skyline": {
                    "account": self.account,
                    "accountId": self.account_id,
                    "region": self.region,
                    "synth": SYNTH,
                    "version": 1,
                }
            },
            "Outputs": self.outputs,
            "Resources": self.resources,
        }


def assume_ecs(account_id: str) -> dict[str, Any]:
    """Task roles trust ecs-tasks, and only from this account.

    The source-account condition is the confused-deputy control. A role without
    it can be assumed by a task in another account that can pass the name.
    """
    return policy(
        [
            {
                "Sid": "EcsFromThisAccount",
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "ArnLike": {"aws:SourceArn": f"arn:aws:ecs:*:{account_id}:task/*"},
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            }
        ]
    )


def deny_bedrock() -> dict[str, Any]:
    return {
        "Sid": "DenyBedrock",
        "Effect": "Deny",
        "Action": "bedrock:*",
        "Resource": "*",
    }
