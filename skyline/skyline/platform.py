"""Assemble the six-account platform.

The request path is: corporate CIDR, internal ALB, Aegis, guardrail, then
Switchboard's route, then Bedrock. Bedrock has an interface endpoint in the
security VPC only. Lumen and Switchboard carry an explicit Deny on bedrock:*.
Each tenant's documents sit in their own bucket, encrypted with their own CMK.
"""

from __future__ import annotations

from typing import Any

from skyline.cfn import (
    ACCOUNTS,
    GUARDRAIL_NAME,
    TGW_ID,
    Stack,
    assume_ecs,
    bucket_arn,
    deny_bedrock,
    key_arn,
    policy,
    role_arn,
    tags,
)
from skyline.guardrail import guardrail_meta, guardrail_properties
from skyline.load import PlatformSpec, load_platform

# Interface endpoints a task VPC needs so it can boot and log with no NAT.
# Bedrock is added only in security. ECR is per VPC on purpose: a shared
# private zone is how Bedrock DNS would leak into Lumen. See ADR 0003.
COMMON_ENDPOINTS = ("logs", "sts", "ecr.api", "ecr.dkr", "monitoring")
BEDROCK_SERVICE = "bedrock-runtime"

MODEL_ARNS = (
    "arn:aws:bedrock:{region}::foundation-model/skyline.haiku",
    "arn:aws:bedrock:{region}::foundation-model/skyline.sonnet",
)


def _pascal(value: str) -> str:
    return "".join(part.capitalize() for part in value.replace(".", " ").replace("-", " ").split())


def _endpoint_logical(service: str) -> str:
    return f"{_pascal(service)}Endpoint"


class Platform:
    def __init__(self, spec: PlatformSpec | None = None) -> None:
        self.spec = spec if spec is not None else load_platform()
        self.region = self.spec["region"]
        self.stacks: dict[str, Stack] = {
            name: Stack(name, self.region, ACCOUNTS[name]["blurb"]) for name in ACCOUNTS
        }

    def assemble(self) -> dict[str, Any]:
        self._network()
        self._security()
        self._lumen()
        self._switchboard()
        self._log_archive()
        self._finops()
        spec = self.spec
        return {
            "manifest": {
                "accounts": [
                    {
                        "blurb": ACCOUNTS[name]["blurb"],
                        "id": ACCOUNTS[name]["id"],
                        "name": name,
                    }
                    for name in ACCOUNTS
                ],
                "corporateCidr": spec["corporate_cidr"],
                "disclaimer": "Synthetic account ids. This file is a fixture, not a live deployment.",
                "name": "skyline",
                "region": self.region,
                "synth": "fixture-cdk",
                "tenants": [{"display": item["display"], "id": item["id"]} for item in spec["tenants"]],
                "tgwId": TGW_ID,
            },
            "stacks": {name: stack.to_dict() for name, stack in self.stacks.items()},
        }

    def stack(self, name: str) -> Stack:
        return self.stacks[name]

    def _vpc(self, account: str, prefix: str) -> dict[str, Any]:
        spec = self.spec["vpcs"][account]
        stack = self.stack(account)
        vpc_id = f"{prefix}Vpc"
        stack.add(
            vpc_id,
            "AWS::EC2::VPC",
            {
                "CidrBlock": spec["cidr"],
                "EnableDnsHostnames": True,
                "EnableDnsSupport": True,
                "InstanceTenancy": "default",
                "Tags": tags(Name=f"skyline-{account}"),
            },
            meta={"kind": "vpc"},
        )
        subnets: list[str] = []
        route_tables: list[str] = []
        for index, (cidr, az) in enumerate(zip(spec["subnets"], self.spec["azs"], strict=True), start=1):
            subnet = f"{prefix}PrivateSubnetAz{index}"
            stack.add(
                subnet,
                "AWS::EC2::Subnet",
                {
                    "AvailabilityZone": az,
                    "CidrBlock": cidr,
                    "MapPublicIpOnLaunch": False,
                    "Tags": tags(Name=f"skyline-{account}-private-{index}", Tier="private"),
                    "VpcId": {"Ref": vpc_id},
                },
                meta={"kind": "private-subnet"},
            )
            table = f"{prefix}RouteTableAz{index}"
            stack.add(
                table,
                "AWS::EC2::RouteTable",
                {"Tags": tags(Name=f"skyline-{account}-rt-{index}"), "VpcId": {"Ref": vpc_id}},
            )
            stack.add(
                f"{prefix}RouteAssocAz{index}",
                "AWS::EC2::SubnetRouteTableAssociation",
                {"RouteTableId": {"Ref": table}, "SubnetId": {"Ref": subnet}},
            )
            # /8 covers every platform VPC and the corporate aggregate.
            # The local route is more specific, so a VPC does not hairpin its own traffic.
            stack.add(
                f"{prefix}RouteToPlatformAz{index}",
                "AWS::EC2::Route",
                {
                    "DestinationCidrBlock": "10.0.0.0/8",
                    "RouteTableId": {"Ref": table},
                    "TransitGatewayId": TGW_ID,
                },
                meta={"kind": "platform-route"},
            )
            subnets.append(subnet)
            route_tables.append(table)
        stack.add(
            f"{prefix}FlowLogGroup",
            "AWS::Logs::LogGroup",
            {"LogGroupName": f"/skyline/flow/{account}", "RetentionInDays": 30},
        )
        stack.add(
            f"{prefix}FlowLogRole",
            "AWS::IAM::Role",
            {
                "AssumeRolePolicyDocument": policy(
                    [
                        {
                            "Action": "sts:AssumeRole",
                            "Effect": "Allow",
                            "Principal": {"Service": "vpc-flow-logs.amazonaws.com"},
                        }
                    ]
                ),
                "Policies": [
                    {
                        "PolicyDocument": policy(
                            [
                                {
                                    "Action": [
                                        "logs:CreateLogStream",
                                        "logs:PutLogEvents",
                                        "logs:DescribeLogStreams",
                                    ],
                                    "Effect": "Allow",
                                    "Resource": f"arn:aws:logs:{self.region}:{stack.account_id}:log-group:/skyline/flow/{account}:*",
                                }
                            ]
                        ),
                        "PolicyName": "flow-logs",
                    }
                ],
                "RoleName": f"{prefix}FlowLogRole",
            },
        )
        stack.add(
            f"{prefix}FlowLog",
            "AWS::EC2::FlowLog",
            {
                "DeliverLogsPermissionArn": {"Fn::GetAtt": [f"{prefix}FlowLogRole", "Arn"]},
                "LogGroupName": {"Ref": f"{prefix}FlowLogGroup"},
                "ResourceId": {"Ref": vpc_id},
                "ResourceType": "VPC",
                "TrafficType": "ALL",
            },
            meta={"kind": "flow-log"},
        )
        stack.add(
            f"{prefix}S3Endpoint",
            "AWS::EC2::VPCEndpoint",
            {
                "RouteTableIds": [{"Ref": table} for table in route_tables],
                "ServiceName": f"com.amazonaws.{self.region}.s3",
                "VpcEndpointType": "Gateway",
                "VpcId": {"Ref": vpc_id},
            },
            meta={"kind": "gateway-endpoint", "service": "s3"},
        )
        stack.add(
            f"{prefix}TgwAttachment",
            "AWS::EC2::TransitGatewayAttachment",
            {
                "SubnetIds": [{"Ref": subnet} for subnet in subnets],
                "TransitGatewayId": TGW_ID,
                "VpcId": {"Ref": vpc_id},
            },
            meta={"kind": "tgw-attachment"},
        )
        return {"cidr": spec["cidr"], "route_tables": route_tables, "subnets": subnets, "vpc": vpc_id}

    def _interface_endpoints(
        self,
        account: str,
        prefix: str,
        vpc: dict[str, Any],
        services: tuple[str, ...],
        source_sg: str,
    ) -> None:
        stack = self.stack(account)
        stack.add(
            f"{prefix}EndpointSecurityGroup",
            "AWS::EC2::SecurityGroup",
            {
                "GroupDescription": f"{account} interface endpoints",
                "SecurityGroupEgress": [],
                "SecurityGroupIngress": [
                    {
                        "Description": "tasks in this VPC",
                        "FromPort": 443,
                        "IpProtocol": "tcp",
                        "SourceSecurityGroupId": {"Ref": source_sg},
                        "ToPort": 443,
                    }
                ],
                "VpcId": {"Ref": vpc["vpc"]},
            },
            meta={"kind": "endpoint-sg"},
        )
        for service in services:
            properties: dict[str, Any] = {
                "PrivateDnsEnabled": True,
                "SecurityGroupIds": [{"Ref": f"{prefix}EndpointSecurityGroup"}],
                "ServiceName": f"com.amazonaws.{self.region}.{service}",
                "SubnetIds": [{"Ref": subnet} for subnet in vpc["subnets"]],
                "VpcEndpointType": "Interface",
                "VpcId": {"Ref": vpc["vpc"]},
            }
            meta: dict[str, Any] = {"kind": "interface-endpoint", "service": service}
            if service == BEDROCK_SERVICE:
                properties["PolicyDocument"] = self._bedrock_endpoint_policy()
                meta["kind"] = "bedrock-endpoint"
            stack.add(
                _endpoint_logical(service)
                if account == "security"
                else f"{prefix}{_endpoint_logical(service)}",
                "AWS::EC2::VPCEndpoint",
                properties,
                meta=meta,
            )

    def _bedrock_endpoint_policy(self) -> dict[str, Any]:
        security = ACCOUNTS["security"]["id"]
        resources = [arn.format(region=self.region) for arn in MODEL_ARNS]
        resources.append(f"arn:aws:bedrock:{self.region}:{security}:guardrail/{GUARDRAIL_NAME}")
        return policy(
            [
                {
                    "Action": ["bedrock:ApplyGuardrail", "bedrock:InvokeModel"],
                    "Effect": "Allow",
                    "Principal": {"AWS": role_arn(security, "AegisTaskRole")},
                    "Resource": resources,
                    "Sid": "AegisOnly",
                }
            ]
        )

    def _network(self) -> None:
        stack = self.stack("network")
        stack.add(
            "TransitGateway",
            "AWS::EC2::TransitGateway",
            {
                "AmazonSideAsn": 64512,
                "AutoAcceptSharedAttachments": "disable",
                "DefaultRouteTableAssociation": "enable",
                "DefaultRouteTablePropagation": "enable",
                "DnsSupport": "enable",
                "Tags": tags(Name="skyline-hub"),
                "VpnEcmpSupport": "enable",
            },
            meta={
                "corporateCidr": self.spec["corporate_cidr"],
                "fixtureId": TGW_ID,
                "kind": "tgw",
            },
        )
        stack.output(
            "TransitGatewayId", TGW_ID, "Stable fixture id. Real TGW ids are assigned at create time."
        )
        self._vpc("network", "Hub")

    def _log_group(self, stack: Stack, logical: str, name: str, key: str) -> None:
        stack.add(
            logical,
            "AWS::Logs::LogGroup",
            {
                "KmsKeyId": key,
                "LogGroupName": name,
                "RetentionInDays": 30,
            },
            retain=True,
        )

    def _execution_role(self, stack: Stack, logical: str, log_group: str) -> None:
        stack.add(
            logical,
            "AWS::IAM::Role",
            {
                "AssumeRolePolicyDocument": assume_ecs(stack.account_id),
                "Policies": [
                    {
                        "PolicyDocument": policy(
                            [
                                {
                                    "Action": "ecr:GetAuthorizationToken",
                                    "Effect": "Allow",
                                    "Resource": "*",
                                    "Sid": "EcrAuthToken",
                                },
                                {
                                    "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                                    "Effect": "Allow",
                                    "Resource": f"arn:aws:ecr:{self.region}:{stack.account_id}:repository/skyline/*",
                                    "Sid": "EcrPull",
                                },
                                {
                                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                                    "Effect": "Allow",
                                    "Resource": (
                                        f"arn:aws:logs:{self.region}:{stack.account_id}:log-group:{log_group}:*"
                                    ),
                                    "Sid": "Logs",
                                },
                            ]
                        ),
                        "PolicyName": "execute",
                    }
                ],
                "RoleName": logical,
            },
        )

    def _service(
        self,
        stack: Stack,
        *,
        name: str,
        image: str,
        subnets: list[str],
        sg: str,
        task_policy: list[dict[str, Any]],
        environment: list[dict[str, str]],
        log_key: str,
    ) -> None:
        family = name.lower()
        self._log_group(stack, f"{name}LogGroup", f"/skyline/{family}", log_key)
        self._execution_role(stack, f"{name}ExecutionRole", f"/skyline/{family}")
        stack.add(
            f"{name}TaskRole",
            "AWS::IAM::Role",
            {
                "AssumeRolePolicyDocument": assume_ecs(stack.account_id),
                "Policies": [{"PolicyDocument": policy(task_policy), "PolicyName": family}],
                "RoleName": f"{name}TaskRole",
            },
        )
        stack.add(
            f"{name}TaskDefinition",
            "AWS::ECS::TaskDefinition",
            {
                "ContainerDefinitions": [
                    {
                        "Environment": environment,
                        "Essential": True,
                        "Image": image,
                        "LogConfiguration": {
                            "LogDriver": "awslogs",
                            "Options": {
                                "awslogs-group": {"Ref": f"{name}LogGroup"},
                                "awslogs-region": self.region,
                                "awslogs-stream-prefix": family,
                            },
                        },
                        "Name": family,
                        "PortMappings": [{"ContainerPort": 8443, "Protocol": "tcp"}],
                    }
                ],
                "Cpu": "256",
                "ExecutionRoleArn": {"Fn::GetAtt": [f"{name}ExecutionRole", "Arn"]},
                "Family": f"skyline-{family}",
                "Memory": "512",
                "NetworkMode": "awsvpc",
                "RequiresCompatibilities": ["FARGATE"],
                "TaskRoleArn": {"Fn::GetAtt": [f"{name}TaskRole", "Arn"]},
            },
        )
        stack.add(f"{name}Cluster", "AWS::ECS::Cluster", {"ClusterName": f"skyline-{family}"})
        stack.add(
            f"{name}Service",
            "AWS::ECS::Service",
            {
                "Cluster": {"Ref": f"{name}Cluster"},
                "DesiredCount": 2,
                "LaunchType": "FARGATE",
                "NetworkConfiguration": {
                    "AwsvpcConfiguration": {
                        "AssignPublicIp": "DISABLED",
                        "SecurityGroups": [{"Ref": sg}],
                        "Subnets": [{"Ref": subnet} for subnet in subnets],
                    }
                },
                "TaskDefinition": {"Ref": f"{name}TaskDefinition"},
            },
            meta={"kind": "service"},
        )

    def _tenant_key(self, tenant_id: str, display: str) -> str:
        stack = self.stack("security")
        logical = f"TenantKey{_pascal(tenant_id)}"
        key_id = f"skyline-tenant-{tenant_id}"
        admin = ACCOUNTS["security"]["id"]
        lumen = ACCOUNTS["lumen"]["id"]
        stack.add(
            logical,
            "AWS::KMS::Key",
            {
                "Description": f"Tenant CMK for {display}. Encryption context tenant={tenant_id}.",
                "EnableKeyRotation": True,
                "KeyPolicy": policy(
                    [
                        {
                            "Action": "kms:*",
                            "Effect": "Allow",
                            "Principal": {"AWS": f"arn:aws:iam::{admin}:root"},
                            "Resource": "*",
                            "Sid": "EnableRoot",
                        },
                        {
                            "Action": [
                                "kms:Decrypt",
                                "kms:DescribeKey",
                                "kms:Encrypt",
                                "kms:GenerateDataKey",
                            ],
                            "Condition": {"StringEquals": {"kms:EncryptionContext:tenant": tenant_id}},
                            "Effect": "Allow",
                            "Principal": {
                                "AWS": [
                                    role_arn(admin, "AegisTaskRole"),
                                    role_arn(lumen, "LumenTaskRole"),
                                ]
                            },
                            "Resource": "*",
                            "Sid": "UseWithTenantContext",
                        },
                    ]
                ),
                "KeySpec": "SYMMETRIC_DEFAULT",
                "KeyUsage": "ENCRYPT_DECRYPT",
                "Tags": tags(Name=f"alias/skyline/{tenant_id}", Tenant=tenant_id),
            },
            meta={"fixtureKeyId": key_id, "kind": "tenant-cmk", "tenant": tenant_id},
            retain=True,
        )
        stack.add(
            f"TenantAlias{_pascal(tenant_id)}",
            "AWS::KMS::Alias",
            {"AliasName": f"alias/skyline/{tenant_id}", "TargetKeyId": {"Ref": logical}},
        )
        return key_arn(self.region, admin, key_id)

    def _ops_key(self, stack: Stack) -> str:
        account = stack.account_id
        key_id = f"skyline-ops-{stack.account}"
        stack.add(
            "OpsKey",
            "AWS::KMS::Key",
            {
                "Description": "Operational logs only. Not a tenant data key.",
                "EnableKeyRotation": True,
                "KeyPolicy": policy(
                    [
                        {
                            "Action": "kms:*",
                            "Effect": "Allow",
                            "Principal": {"AWS": f"arn:aws:iam::{account}:root"},
                            "Resource": "*",
                            "Sid": "EnableRoot",
                        },
                        {
                            "Action": [
                                "kms:Decrypt",
                                "kms:DescribeKey",
                                "kms:Encrypt",
                                "kms:GenerateDataKey",
                                "kms:ReEncrypt*",
                            ],
                            "Condition": {
                                "ArnLike": {
                                    "kms:EncryptionContext:aws:logs:arn": f"arn:aws:logs:{self.region}:{account}:*"
                                }
                            },
                            "Effect": "Allow",
                            "Principal": {"Service": f"logs.{self.region}.amazonaws.com"},
                            "Resource": "*",
                            "Sid": "AllowCloudWatchLogs",
                        },
                    ]
                ),
                "KeySpec": "SYMMETRIC_DEFAULT",
                "KeyUsage": "ENCRYPT_DECRYPT",
            },
            meta={"fixtureKeyId": key_id, "kind": "ops-cmk"},
            retain=True,
        )
        return key_arn(self.region, account, key_id)

    def _security(self) -> None:
        vpc = self._vpc("security", "Security")
        stack = self.stack("security")
        ops = self._ops_key(stack)
        tenant_arns = {
            tenant["id"]: self._tenant_key(tenant["id"], tenant["display"]) for tenant in self.spec["tenants"]
        }
        corporate = self.spec["corporate_cidr"]
        lumen_cidr = self.spec["vpcs"]["lumen"]["cidr"]
        switch_cidr = self.spec["vpcs"]["switchboard"]["cidr"]
        stack.add(
            "AlbSecurityGroup",
            "AWS::EC2::SecurityGroup",
            {
                "GroupDescription": "Internal ALB. Corporate clients only.",
                "SecurityGroupEgress": [
                    {
                        "Description": "Aegis tasks",
                        "DestinationSecurityGroupId": {"Ref": "AegisSecurityGroup"},
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    }
                ],
                "SecurityGroupIngress": [
                    {
                        "CidrIp": corporate,
                        "Description": "corporate aggregate over the transit gateway",
                        "FromPort": 443,
                        "IpProtocol": "tcp",
                        "ToPort": 443,
                    }
                ],
                "VpcId": {"Ref": vpc["vpc"]},
            },
            meta={"kind": "alb-sg"},
        )
        stack.add(
            "AegisSecurityGroup",
            "AWS::EC2::SecurityGroup",
            {
                "GroupDescription": "Aegis tasks. No path from the internet.",
                "SecurityGroupEgress": [
                    {
                        "Description": "interface endpoints, including Bedrock",
                        "DestinationSecurityGroupId": {"Ref": "SecurityEndpointSecurityGroup"},
                        "FromPort": 443,
                        "IpProtocol": "tcp",
                        "ToPort": 443,
                    },
                    {
                        "CidrIp": lumen_cidr,
                        "Description": "Lumen",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    },
                    {
                        "CidrIp": switch_cidr,
                        "Description": "Switchboard",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    },
                ],
                "SecurityGroupIngress": [
                    {
                        "Description": "internal ALB",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "SourceSecurityGroupId": {"Ref": "AlbSecurityGroup"},
                        "ToPort": 8443,
                    },
                    {
                        "CidrIp": lumen_cidr,
                        "Description": "Lumen calls Aegis, not Bedrock",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    },
                    {
                        "CidrIp": switch_cidr,
                        "Description": "Switchboard calls Aegis",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    },
                ],
                "VpcId": {"Ref": vpc["vpc"]},
            },
            meta={"kind": "task-sg"},
        )
        self._interface_endpoints(
            "security",
            "Security",
            vpc,
            (*COMMON_ENDPOINTS, "kms", BEDROCK_SERVICE),
            "AegisSecurityGroup",
        )
        stack.add(
            "BedrockPrivateZone",
            "AWS::Route53::HostedZone",
            {
                "HostedZoneConfig": {"Comment": "Bedrock private DNS. Security VPC only."},
                "Name": f"bedrock-runtime.{self.region}.amazonaws.com.",
                "VPCs": [{"VPCId": {"Ref": vpc["vpc"]}, "VPCRegion": self.region}],
            },
            meta={"kind": "bedrock-private-zone"},
        )
        security_id = stack.account_id
        model_resources = [arn.format(region=self.region) for arn in MODEL_ARNS]
        guardrail_arn = f"arn:aws:bedrock:{self.region}:{security_id}:guardrail/{GUARDRAIL_NAME}"
        self._service(
            stack,
            name="Aegis",
            image=f"{security_id}.dkr.ecr.{self.region}.amazonaws.com/skyline/aegis:fixture",
            subnets=vpc["subnets"],
            sg="AegisSecurityGroup",
            log_key=ops,
            environment=[
                {"Name": "GUARDRAIL_ID", "Value": GUARDRAIL_NAME},
                {"Name": "SKYLINE_PROVIDER", "Value": "fixture"},
                {"Name": "SWITCHBOARD_URL", "Value": "https://switchboard.switchboard.skyline.internal:8443"},
                {"Name": "LUMEN_URL", "Value": "https://lumen.lumen.skyline.internal:8443"},
            ],
            task_policy=[
                {
                    "Action": ["bedrock:ApplyGuardrail", "bedrock:InvokeModel"],
                    "Effect": "Allow",
                    "Resource": [*model_resources, guardrail_arn],
                    "Sid": "InvokeWithNamedModels",
                },
                {
                    "Action": ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey"],
                    "Condition": {"StringEquals": {"kms:EncryptionContext:tenant": list(tenant_arns)}},
                    "Effect": "Allow",
                    "Resource": list(tenant_arns.values()),
                    "Sid": "TenantKeys",
                },
                {
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Effect": "Allow",
                    "Resource": f"arn:aws:logs:{self.region}:{security_id}:log-group:/skyline/aegis:*",
                    "Sid": "Logs",
                },
            ],
        )
        stack.add(
            "Guardrail",
            "AWS::Bedrock::Guardrail",
            guardrail_properties(self.region),
            meta=guardrail_meta(),
        )
        stack.add(
            "InternalAlb",
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
            {
                "Name": "skyline-aegis",
                "Scheme": "internal",
                "SecurityGroups": [{"Ref": "AlbSecurityGroup"}],
                "Subnets": [{"Ref": subnet} for subnet in vpc["subnets"]],
                "Type": "application",
            },
            meta={"kind": "internal-alb"},
        )
        stack.add(
            "AegisTargetGroup",
            "AWS::ElasticLoadBalancingV2::TargetGroup",
            {
                "HealthCheckPath": "/healthz",
                "Port": 8443,
                "Protocol": "HTTPS",
                "TargetType": "ip",
                "VpcId": {"Ref": vpc["vpc"]},
            },
        )
        stack.add(
            "HttpsListener",
            "AWS::ElasticLoadBalancingV2::Listener",
            {
                "DefaultActions": [{"TargetGroupArn": {"Ref": "AegisTargetGroup"}, "Type": "forward"}],
                "LoadBalancerArn": {"Ref": "InternalAlb"},
                "Port": 443,
                "Protocol": "HTTPS",
            },
        )
        for tenant_id, arn in tenant_arns.items():
            stack.output(f"TenantKey{_pascal(tenant_id)}", arn, f"CMK for {tenant_id}")
        stack.output("GuardrailName", GUARDRAIL_NAME, "Guardrail the Aegis task is pinned to")

    def _bucket(self, stack: Stack, logical: str, name: str, key_arn_value: str, tenant: str) -> None:
        stack.add(
            logical,
            "AWS::S3::Bucket",
            {
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {
                            "BucketKeyEnabled": True,
                            "ServerSideEncryptionByDefault": {
                                "KMSMasterKeyID": key_arn_value,
                                "SSEAlgorithm": "aws:kms",
                            },
                        }
                    ]
                },
                "BucketName": name,
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
                "Tags": tags(Tenant=tenant),
                "VersioningConfiguration": {"Status": "Enabled"},
            },
            meta={"kind": "tenant-bucket", "tenant": tenant},
            retain=True,
        )

    def _lumen(self) -> None:
        stack = self.stack("lumen")
        ops = self._ops_key(stack)
        vpc = self._vpc("lumen", "Lumen")
        security_id = ACCOUNTS["security"]["id"]
        stack.add(
            "LumenSecurityGroup",
            "AWS::EC2::SecurityGroup",
            {
                "GroupDescription": "Lumen tasks. Egress to Aegis and to this VPC's endpoints.",
                "SecurityGroupEgress": [
                    {
                        "CidrIp": self.spec["vpcs"]["security"]["cidr"],
                        "Description": "Aegis over the transit gateway",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    },
                    {
                        "Description": "local interface endpoints",
                        "DestinationSecurityGroupId": {"Ref": "LumenEndpointSecurityGroup"},
                        "FromPort": 443,
                        "IpProtocol": "tcp",
                        "ToPort": 443,
                    },
                ],
                "SecurityGroupIngress": [
                    {
                        "CidrIp": self.spec["vpcs"]["security"]["cidr"],
                        "Description": "Aegis",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    }
                ],
                "VpcId": {"Ref": vpc["vpc"]},
            },
            meta={"kind": "task-sg"},
        )
        self._interface_endpoints("lumen", "Lumen", vpc, (*COMMON_ENDPOINTS, "kms"), "LumenSecurityGroup")
        tenant_key_arns = [
            key_arn(self.region, security_id, f"skyline-tenant-{tenant['id']}")
            for tenant in self.spec["tenants"]
        ]
        bucket_arns = [bucket_arn(f"skyline-lumen-{tenant['id']}-docs") for tenant in self.spec["tenants"]]
        self._service(
            stack,
            name="Lumen",
            image=f"{stack.account_id}.dkr.ecr.{self.region}.amazonaws.com/skyline/lumen:fixture",
            subnets=vpc["subnets"],
            sg="LumenSecurityGroup",
            log_key=ops,
            environment=[
                {"Name": "AEGIS_URL", "Value": "https://aegis.security.skyline.internal:8443"},
                {"Name": "SKYLINE_PROVIDER", "Value": "fixture"},
            ],
            task_policy=[
                deny_bedrock(),
                {
                    "Action": ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey"],
                    "Condition": {
                        "StringEquals": {
                            "kms:EncryptionContext:tenant": [tenant["id"] for tenant in self.spec["tenants"]]
                        }
                    },
                    "Effect": "Allow",
                    "Resource": tenant_key_arns,
                    "Sid": "TenantKeys",
                },
                {
                    "Action": ["s3:GetObject", "s3:PutObject"],
                    "Effect": "Allow",
                    "Resource": [f"{arn}/*" for arn in bucket_arns],
                    "Sid": "TenantDocs",
                },
            ],
        )
        for tenant in self.spec["tenants"]:
            self._bucket(
                stack,
                f"DocBucket{_pascal(tenant['id'])}",
                f"skyline-lumen-{tenant['id']}-docs",
                key_arn(self.region, security_id, f"skyline-tenant-{tenant['id']}"),
                tenant["id"],
            )

    def _switchboard(self) -> None:
        stack = self.stack("switchboard")
        ops = self._ops_key(stack)
        vpc = self._vpc("switchboard", "Switchboard")
        stack.add(
            "SwitchboardSecurityGroup",
            "AWS::EC2::SecurityGroup",
            {
                "GroupDescription": "Switchboard tasks. They choose a model. They do not call it.",
                "SecurityGroupEgress": [
                    {
                        "CidrIp": self.spec["vpcs"]["security"]["cidr"],
                        "Description": "Aegis",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    },
                    {
                        "Description": "local interface endpoints",
                        "DestinationSecurityGroupId": {"Ref": "SwitchboardEndpointSecurityGroup"},
                        "FromPort": 443,
                        "IpProtocol": "tcp",
                        "ToPort": 443,
                    },
                ],
                "SecurityGroupIngress": [
                    {
                        "CidrIp": self.spec["vpcs"]["security"]["cidr"],
                        "Description": "Aegis asks for a route",
                        "FromPort": 8443,
                        "IpProtocol": "tcp",
                        "ToPort": 8443,
                    }
                ],
                "VpcId": {"Ref": vpc["vpc"]},
            },
            meta={"kind": "task-sg"},
        )
        self._interface_endpoints(
            "switchboard", "Switchboard", vpc, COMMON_ENDPOINTS, "SwitchboardSecurityGroup"
        )
        self._service(
            stack,
            name="Switchboard",
            image=f"{stack.account_id}.dkr.ecr.{self.region}.amazonaws.com/skyline/switchboard:fixture",
            subnets=vpc["subnets"],
            sg="SwitchboardSecurityGroup",
            log_key=ops,
            environment=[
                {"Name": "AEGIS_URL", "Value": "https://aegis.security.skyline.internal:8443"},
                {"Name": "SKYLINE_PROVIDER", "Value": "fixture"},
            ],
            task_policy=[
                deny_bedrock(),
                {
                    "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                    "Effect": "Allow",
                    "Resource": (
                        f"arn:aws:logs:{self.region}:{stack.account_id}:log-group:/skyline/switchboard:*"
                    ),
                    "Sid": "Logs",
                },
            ],
        )

    def _log_archive(self) -> None:
        stack = self.stack("log-archive")
        account = stack.account_id
        key_id = "skyline-trail"
        trail_arn = f"arn:aws:cloudtrail:{self.region}:{account}:trail/skyline-org"
        stack.add(
            "TrailKey",
            "AWS::KMS::Key",
            {
                "Description": "CloudTrail log encryption. Not a tenant key.",
                "EnableKeyRotation": True,
                "KeyPolicy": policy(
                    [
                        {
                            "Action": "kms:*",
                            "Effect": "Allow",
                            "Principal": {"AWS": f"arn:aws:iam::{account}:root"},
                            "Resource": "*",
                            "Sid": "EnableRoot",
                        },
                        {
                            "Action": ["kms:DescribeKey", "kms:GenerateDataKey*"],
                            "Condition": {
                                "StringEquals": {"aws:SourceArn": trail_arn},
                                "StringLike": {
                                    "kms:EncryptionContext:aws:cloudtrail:arn": (
                                        f"arn:aws:cloudtrail:*:{account}:trail/*"
                                    )
                                },
                            },
                            "Effect": "Allow",
                            "Principal": {"Service": "cloudtrail.amazonaws.com"},
                            "Resource": "*",
                            "Sid": "AllowCloudTrail",
                        },
                    ]
                ),
                "KeySpec": "SYMMETRIC_DEFAULT",
                "KeyUsage": "ENCRYPT_DECRYPT",
            },
            meta={"fixtureKeyId": key_id, "kind": "trail-cmk"},
            retain=True,
        )
        stack.add(
            "TrailBucket",
            "AWS::S3::Bucket",
            {
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {
                            "BucketKeyEnabled": True,
                            "ServerSideEncryptionByDefault": {
                                "KMSMasterKeyID": key_arn(self.region, account, key_id),
                                "SSEAlgorithm": "aws:kms",
                            },
                        }
                    ]
                },
                "BucketName": "skyline-log-archive-trail",
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
                "VersioningConfiguration": {"Status": "Enabled"},
            },
            meta={"kind": "trail-bucket"},
            retain=True,
        )
        stack.add(
            "TrailBucketPolicy",
            "AWS::S3::BucketPolicy",
            {
                "Bucket": {"Ref": "TrailBucket"},
                "PolicyDocument": policy(
                    [
                        {
                            "Action": "s3:GetBucketAcl",
                            "Effect": "Allow",
                            "Principal": {"Service": "cloudtrail.amazonaws.com"},
                            "Resource": bucket_arn("skyline-log-archive-trail"),
                            "Sid": "CloudTrailAcl",
                        },
                        {
                            "Action": "s3:PutObject",
                            "Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}},
                            "Effect": "Allow",
                            "Principal": {"Service": "cloudtrail.amazonaws.com"},
                            "Resource": f"{bucket_arn('skyline-log-archive-trail')}/AWSLogs/*",
                            "Sid": "CloudTrailWrite",
                        },
                    ]
                ),
            },
        )
        stack.add(
            "OrgTrail",
            "AWS::CloudTrail::Trail",
            {
                "EnableLogFileValidation": True,
                "IncludeGlobalServiceEvents": True,
                "IsLogging": True,
                "IsMultiRegionTrail": True,
                "IsOrganizationTrail": True,
                "KMSKeyId": {"Ref": "TrailKey"},
                "S3BucketName": {"Ref": "TrailBucket"},
                "TrailName": "skyline-org",
            },
            meta={"kind": "org-trail"},
        )

    def _finops(self) -> None:
        stack = self.stack("finops")
        stack.add(
            "PlatformBudget",
            "AWS::Budgets::Budget",
            {
                "Budget": {
                    "BudgetLimit": {"Amount": "250", "Unit": "USD"},
                    "BudgetName": "skyline-platform-monthly",
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                }
            },
            meta={"kind": "budget", "note": "Illustrative ceiling, not a forecast."},
        )


def assemble(spec: PlatformSpec | None = None) -> dict[str, Any]:
    return Platform(spec).assemble()
