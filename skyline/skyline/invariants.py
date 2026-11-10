"""Architecture gate. A clean synth passes. A mutation fails by name.

These rules read the CloudFormation properties, not the Skyline metadata, except
where the metadata is the only place a tenant id is recorded next to a key.
When metadata and properties disagree, the property check is the one that fails
the bucket rule.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from skyline.cfn import ACCOUNTS, GUARDRAIL_NAME
from skyline.walk import (
    actions,
    iter_resources,
    principal_is_wildcard,
    resources_of,
    role_statements,
    skyline_meta,
    statements_of,
)

Rule = Callable[[dict[str, Any]], list[str]]


def _props(resource: dict[str, Any]) -> dict[str, Any]:
    return resource["Properties"]


def no_internet_gateway(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] in {"AWS::EC2::InternetGateway", "AWS::EC2::VPCGatewayAttachment"}:
            bad.append(f"{stack}/{logical} is {resource['Type']}")
    return bad


def no_default_route(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::EC2::Route":
            continue
        dest = str(_props(resource).get("DestinationCidrBlock", ""))
        if dest in {"0.0.0.0/0", "::/0"}:
            bad.append(f"{stack}/{logical} routes {dest}")
    return bad


def private_subnets(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::EC2::Subnet":
            continue
        if _props(resource).get("MapPublicIpOnLaunch") is not False:
            bad.append(f"{stack}/{logical} is not a private subnet")
    return bad


def no_world_cidrs(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    corporate = str(assembly["manifest"].get("corporateCidr", ""))
    if corporate in {"0.0.0.0/0", "::/0"}:
        bad.append("corporate CIDR is the whole internet")
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::EC2::SecurityGroup":
            continue
        props = _props(resource)
        for direction in ("SecurityGroupIngress", "SecurityGroupEgress"):
            for index, rule in enumerate(props.get(direction, [])):
                for field in ("CidrIp", "CidrIpv6"):
                    if rule.get(field) in {"0.0.0.0/0", "::/0"}:
                        bad.append(f"{stack}/{logical} {direction}[{index}] {field} is {rule.get(field)}")
    return bad


def tasks_no_public_ip(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::ECS::Service":
            continue
        awsvpc = _props(resource).get("NetworkConfiguration", {}).get("AwsvpcConfiguration", {})
        if awsvpc.get("AssignPublicIp") != "DISABLED":
            bad.append(f"{stack}/{logical} AssignPublicIp is {awsvpc.get('AssignPublicIp')!r}")
    return bad


def tenant_bucket_key(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    seen: dict[str, str] = {}
    keys = {
        skyline_meta(resource).get("tenant"): f"{stack}/{logical}"
        for stack, logical, resource in iter_resources(assembly)
        if resource["Type"] == "AWS::KMS::Key" and skyline_meta(resource).get("kind") == "tenant-cmk"
    }
    for stack, logical, resource in iter_resources(assembly):
        if skyline_meta(resource).get("kind") != "tenant-bucket":
            continue
        tenant = str(skyline_meta(resource).get("tenant"))
        encryption = _props(resource)["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]
        default = encryption["ServerSideEncryptionByDefault"]
        key_id = str(default["KMSMasterKeyID"])
        if default["SSEAlgorithm"] != "aws:kms":
            bad.append(f"{stack}/{logical} is not SSE-KMS")
        expected = f"key/skyline-tenant-{tenant}"
        if expected not in key_id:
            bad.append(f"{stack}/{logical} key is {key_id}, expected {expected}")
        if tenant not in keys:
            bad.append(f"{stack}/{logical} has no tenant CMK for {tenant}")
        owner = seen.get(key_id)
        if owner and owner != tenant:
            bad.append(f"{stack}/{logical} reuses {owner}'s key")
        seen[key_id] = tenant
    expected_tenants = {item["id"] for item in assembly["manifest"]["tenants"]}
    if set(seen.values()) != expected_tenants:
        bad.append(f"bucket keys cover {sorted(seen.values())}, tenants are {sorted(expected_tenants)}")
    return bad


def kms_no_wildcard(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::KMS::Key":
            continue
        for statement in statements_of(_props(resource).get("KeyPolicy")):
            if principal_is_wildcard(statement.get("Principal")):
                bad.append(f"{stack}/{logical} statement {statement.get('Sid', '?')} allows Principal *")
    return bad


def kms_encryption_context(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    security_root = f"arn:aws:iam::{ACCOUNTS['security']['id']}:root"
    for stack, logical, resource in iter_resources(assembly):
        meta = skyline_meta(resource)
        if meta.get("kind") != "tenant-cmk":
            continue
        tenant = str(meta.get("tenant"))
        for statement in statements_of(_props(resource).get("KeyPolicy")):
            sid = str(statement.get("Sid", ""))
            if sid == "EnableRoot":
                principal = statement.get("Principal", {}).get("AWS")
                if principal != security_root:
                    bad.append(f"{stack}/{logical} root principal is {principal}")
                continue
            condition = statement.get("Condition", {}).get("StringEquals", {})
            if condition.get("kms:EncryptionContext:tenant") != tenant:
                bad.append(f"{stack}/{logical} {sid} is missing tenant={tenant}")
    return bad


def bedrock_only_in_security(assembly: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::EC2::VPCEndpoint":
            continue
        service = str(_props(resource).get("ServiceName", ""))
        if not service.endswith(".bedrock-runtime"):
            continue
        found.append(f"{stack}/{logical}")
        if stack != "security":
            return [f"Bedrock endpoint {stack}/{logical} is outside the security account"]
        if _props(resource).get("PrivateDnsEnabled") is not True:
            return [f"{stack}/{logical} does not enable private DNS"]
    if found != ["security/BedrockRuntimeEndpoint"]:
        return [f"expected one security Bedrock endpoint, found {found}"]
    return []


def bedrock_dns_not_shared(assembly: dict[str, Any]) -> list[str]:
    zones = [
        (stack, logical, resource)
        for stack, logical, resource in iter_resources(assembly)
        if resource["Type"] == "AWS::Route53::HostedZone"
        and str(_props(resource).get("Name", "")).startswith("bedrock-runtime.")
    ]
    if len(zones) != 1:
        return [f"expected one Bedrock private zone, found {len(zones)}"]
    stack, logical, resource = zones[0]
    if stack != "security":
        return [f"{stack}/{logical} publishes Bedrock DNS outside security"]
    vpcs = _props(resource).get("VPCs", [])
    if len(vpcs) != 1:
        return [f"{stack}/{logical} is associated with {len(vpcs)} VPCs"]
    ref = vpcs[0].get("VPCId", {}).get("Ref")
    if ref != "SecurityVpc":
        return [f"{stack}/{logical} is associated with {ref}"]
    return []


def bedrock_endpoint_principal(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    expected = f"arn:aws:iam::{ACCOUNTS['security']['id']}:role/AegisTaskRole"
    allowed = {"bedrock:ApplyGuardrail", "bedrock:InvokeModel"}
    for stack, logical, resource in iter_resources(assembly):
        if skyline_meta(resource).get("kind") != "bedrock-endpoint":
            continue
        for statement in statements_of(_props(resource).get("PolicyDocument")):
            principal = statement.get("Principal", {}).get("AWS")
            if principal != expected:
                bad.append(f"{stack}/{logical} principal is {principal}")
            extra = set(actions(statement)) - allowed
            if extra or statement.get("Effect") != "Allow":
                bad.append(f"{stack}/{logical} actions {actions(statement)}")
    if not bad and not any(
        skyline_meta(res).get("kind") == "bedrock-endpoint" for _, _, res in iter_resources(assembly)
    ):
        return ["no Bedrock endpoint policy"]
    return bad


def guardrail_attached(assembly: dict[str, Any]) -> list[str]:
    guardrails = [
        (stack, resource)
        for stack, _, resource in iter_resources(assembly)
        if resource["Type"] == "AWS::Bedrock::Guardrail"
    ]
    if len(guardrails) != 1 or guardrails[0][0] != "security":
        return ["the security account needs exactly one guardrail"]
    name = _props(guardrails[0][1]).get("Name")
    if name != GUARDRAIL_NAME:
        return [f"guardrail name is {name}"]
    pinned = False
    for _stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::ECS::TaskDefinition" or logical != "AegisTaskDefinition":
            continue
        for container in _props(resource).get("ContainerDefinitions", []):
            env = {item["Name"]: item["Value"] for item in container.get("Environment", [])}
            pinned = env.get("GUARDRAIL_ID") == GUARDRAIL_NAME
    if not pinned:
        return ["Aegis task is not pinned to the guardrail"]
    return []


def _mentions_bedrock(statement: dict[str, Any]) -> bool:
    return any(action == "bedrock:*" or action.startswith("bedrock:") for action in actions(statement))


def no_bedrock_outside_aegis(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    seen_deny = set()
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::IAM::Role" or logical not in {"LumenTaskRole", "SwitchboardTaskRole"}:
            continue
        for statement in role_statements(resource):
            if (
                statement.get("Sid") == "DenyBedrock"
                and statement.get("Effect") == "Deny"
                and "bedrock:*" in actions(statement)
            ):
                seen_deny.add(logical)
            if statement.get("Effect") == "Allow" and _mentions_bedrock(statement):
                bad.append(f"{stack}/{logical} allows Bedrock")
    for role in ("LumenTaskRole", "SwitchboardTaskRole"):
        if role not in seen_deny:
            bad.append(f"{role} is missing Deny bedrock:*")
    for stack, logical, resource in iter_resources(assembly):
        if logical != "AegisTaskRole":
            continue
        allows = [
            statement
            for statement in role_statements(resource)
            if statement.get("Effect") == "Allow" and _mentions_bedrock(statement)
        ]
        if not allows:
            bad.append("AegisTaskRole cannot invoke a model")
        for statement in allows:
            if "*" in resources_of(statement):
                bad.append(f"{stack}/{logical} Bedrock resource is *")
            if not any(":guardrail/" in item for item in resources_of(statement)):
                bad.append(f"{stack}/{logical} Bedrock resources omit the guardrail")
    return bad


def flow_logs_and_trail(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    vpcs: dict[str, int] = {}
    flows: dict[str, int] = {}
    trails: list[str] = []
    for stack, _, resource in iter_resources(assembly):
        if resource["Type"] == "AWS::EC2::VPC":
            vpcs[stack] = vpcs.get(stack, 0) + 1
        if resource["Type"] == "AWS::EC2::FlowLog" and _props(resource).get("TrafficType") == "ALL":
            flows[stack] = flows.get(stack, 0) + 1
        if resource["Type"] == "AWS::CloudTrail::Trail":
            props = _props(resource)
            trails.append(stack)
            if props.get("EnableLogFileValidation") is not True or props.get("IsLogging") is not True:
                bad.append(f"{stack} trail is not validating")
            if props.get("IsMultiRegionTrail") is not True:
                bad.append(f"{stack} trail is single-region")
    for stack in vpcs:
        if flows.get(stack, 0) < 1:
            bad.append(f"{stack} VPC has no flow log")
    if trails != ["log-archive"]:
        bad.append(f"expected the trail in log-archive, found {trails}")
    return bad


def multi_az(assembly: dict[str, Any]) -> list[str]:
    by_vpc: dict[str, set[str]] = {}
    for stack, _, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::EC2::Subnet":
            continue
        props = _props(resource)
        ref = str(props.get("VpcId", {}).get("Ref", stack))
        by_vpc.setdefault(f"{stack}/{ref}", set()).add(str(props.get("AvailabilityZone")))
    bad = [f"{vpc} spans {sorted(azs)}" for vpc, azs in sorted(by_vpc.items()) if len(azs) < 2]
    if len(by_vpc) < 4:
        bad.append(f"expected four VPCs, found {len(by_vpc)}")
    return bad


def buckets_locked(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    count = 0
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::S3::Bucket":
            continue
        count += 1
        props = _props(resource)
        block = props.get("PublicAccessBlockConfiguration", {})
        needed = ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets")
        if not all(block.get(flag) is True for flag in needed):
            bad.append(f"{stack}/{logical} public access block is incomplete")
        if props.get("VersioningConfiguration", {}).get("Status") != "Enabled":
            bad.append(f"{stack}/{logical} versioning is off")
        try:
            algo = props["BucketEncryption"]["ServerSideEncryptionConfiguration"][0][
                "ServerSideEncryptionByDefault"
            ]["SSEAlgorithm"]
        except (KeyError, IndexError):
            algo = ""
        if algo != "aws:kms":
            bad.append(f"{stack}/{logical} is not SSE-KMS")
    if count < 4:
        bad.append(f"expected tenant buckets plus the trail bucket, found {count}")
    return bad


def alb_internal(assembly: dict[str, Any]) -> list[str]:
    found = 0
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::ElasticLoadBalancingV2::LoadBalancer":
            continue
        found += 1
        if _props(resource).get("Scheme") != "internal":
            bad.append(f"{stack}/{logical} scheme is {_props(resource).get('Scheme')}")
    if found != 1:
        bad.append(f"expected one load balancer, found {found}")
    return bad


def budget_present(assembly: dict[str, Any]) -> list[str]:
    found = [
        stack for stack, _, resource in iter_resources(assembly) if resource["Type"] == "AWS::Budgets::Budget"
    ]
    if found != ["finops"]:
        return [f"expected the budget in finops, found {found}"]
    return []


def task_confused_deputy(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::IAM::Role":
            continue
        account = assembly["stacks"][stack]["Metadata"]["Skyline"]["accountId"]
        for statement in statements_of(_props(resource).get("AssumeRolePolicyDocument")):
            service = statement.get("Principal", {}).get("Service", "")
            services = [service] if isinstance(service, str) else list(service)
            if "ecs-tasks.amazonaws.com" not in services:
                continue
            source = statement.get("Condition", {}).get("StringEquals", {}).get("aws:SourceAccount")
            if source != account:
                bad.append(f"{stack}/{logical} source account is {source}")
    return bad


def iam_no_star_resource(assembly: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for stack, logical, resource in iter_resources(assembly):
        if resource["Type"] != "AWS::IAM::Role":
            continue
        for statement in role_statements(resource):
            if statement.get("Effect") != "Allow":
                continue
            if "*" not in resources_of(statement):
                continue
            if actions(statement) == ["ecr:GetAuthorizationToken"]:
                continue
            bad.append(f"{stack}/{logical} {statement.get('Sid', '?')} allows Resource *")
    return bad


RULES: tuple[tuple[str, str, Rule], ...] = (
    ("no-internet-gateway", "No internet gateway", no_internet_gateway),
    ("no-default-route", "No default route", no_default_route),
    ("private-subnets", "Every subnet is private", private_subnets),
    ("no-world-cidrs", "No security group opens the world", no_world_cidrs),
    ("tasks-no-public-ip", "Tasks have no public IP", tasks_no_public_ip),
    ("tenant-bucket-key", "Each tenant bucket uses that tenant's CMK", tenant_bucket_key),
    ("kms-no-wildcard", "No KMS principal is a star", kms_no_wildcard),
    ("kms-encryption-context", "Tenant keys require the tenant context", kms_encryption_context),
    ("bedrock-only-in-security", "Bedrock endpoint only in security", bedrock_only_in_security),
    ("bedrock-dns-not-shared", "Bedrock private DNS stays in the security VPC", bedrock_dns_not_shared),
    ("bedrock-endpoint-principal", "Only Aegis can use the Bedrock endpoint", bedrock_endpoint_principal),
    ("guardrail-attached", "Guardrail exists and Aegis is pinned to it", guardrail_attached),
    ("no-bedrock-outside-aegis", "Lumen and Switchboard cannot call Bedrock", no_bedrock_outside_aegis),
    ("flow-logs-and-trail", "Flow logs on every VPC, validating trail", flow_logs_and_trail),
    ("multi-az", "Every VPC spans two AZs", multi_az),
    ("buckets-locked", "Buckets are encrypted, versioned, and not public", buckets_locked),
    ("alb-internal", "The load balancer is internal", alb_internal),
    ("budget-present", "FinOps account holds the budget", budget_present),
    ("task-confused-deputy", "Task roles are bound to their account", task_confused_deputy),
    ("iam-no-star-resource", "IAM allows Resource * only for the ECR auth token", iam_no_star_resource),
)

MUTATION_PRIMARY: dict[str, str] = {
    "open-sg": "no-world-cidrs",
    "shared-cmk": "tenant-bucket-key",
    "drop-guardrail": "guardrail-attached",
    "public-route": "no-internet-gateway",
    "lumen-bedrock": "no-bedrock-outside-aegis",
    "wildcard-kms": "kms-no-wildcard",
    "share-bedrock-dns": "bedrock-dns-not-shared",
}


def evaluate(assembly: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule_id, title, fn in RULES:
        findings = fn(assembly)
        rows.append({"findings": findings, "ok": not findings, "rule": rule_id, "title": title})
    return rows


def failed_rules(assembly: dict[str, Any]) -> list[str]:
    return [row["rule"] for row in evaluate(assembly) if not row["ok"]]
