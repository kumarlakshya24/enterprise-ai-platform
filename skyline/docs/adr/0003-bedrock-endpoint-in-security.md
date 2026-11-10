# ADR 0003: Bedrock only in the security VPC, and no internet gateway

* Status: accepted
* Date: 2026-11-10

## Context

The model call is the packet that must not cross the internet, and must not be available to every
task that can open a socket. Two designs are common.

1. A NAT gateway, the public Bedrock endpoint, and a security group that "should" be tight.
2. Interface endpoints in every VPC, with one shared private hosted zone so the name resolves
   everywhere.

The first puts a default route in the subnet. The day the security group is wrong, the packet
leaves. The second is cheaper on endpoint hours and makes the Bedrock name resolvable from Lumen,
which is the bypass.

ECR, logs, and STS have the same boot problem: without a NAT, a task cannot pull an image or write
a log line. Those endpoints are not the trust boundary. Bedrock is.

## Decision

No internet gateway anywhere in the assembly. No `0.0.0.0/0` route. No public IP on a task.

Each VPC that runs a task gets its own interface endpoints for logs, STS, ECR API, ECR DKR, and
monitoring, plus a free S3 gateway endpoint. Security and Lumen also get KMS, because they call it.
Only the security VPC gets `bedrock-runtime`.

The endpoint policy allows `bedrock:InvokeModel` and `bedrock:ApplyGuardrail` for `AegisTaskRole`,
on two fixture model ARNs and the guardrail ARN. It does not use `Principal: "*"`.

`BedrockPrivateZone` is associated with `SecurityVpc` only. That resource exists so "who can resolve
Bedrock" is a list the gate can count. `share-bedrock-dns` adds the Lumen VPC. `bedrock-dns-not-shared`
fails.

Lumen and Switchboard task roles deny `bedrock:*`. Aegis is the only allow, and the allow does not
use `Resource: "*"`. The task definition sets `GUARDRAIL_ID` to the guardrail's name. Removing the
guardrail resource fails `guardrail-attached` even though the environment variable is still there.

Security groups have no world CIDR in ingress or egress. Egress from Aegis is the endpoint security
group on 443, and the Lumen and Switchboard CIDRs on 8443.

## Consequences

Good:

* A wrong security group and a shared DNS name are different diffs, and both fail closed.
* There is no NAT to grow a default route later. `public-route` has to add the gateway, the
  attachment, and the route. Two rules fire.

Bad:

* Eighteen interface endpoints, two AZs each, is $8.64/day at the frozen rate before a single
  request. One NAT gateway is $1.08/day. ADR 0004 requires the console to show that, because this
  ADR will otherwise be sold as a saving.
* Centralizing ECR and logs in the hub would cut the hourly bill and would also be the natural
  place to attach the Bedrock zone to every VPC. We kept the duplication so that mistake stays
  explicit.
* The endpoint policy does not prove the caller passed a guardrail id. IAM allows `InvokeModel`.
  The compensating controls are the pinned environment variable, the guardrail resource, and the
  fact that only one role can call. A stolen Aegis role can still invoke without the guardrail.
  The failure mode says that plainly.
* Fixture model ids (`skyline.haiku`, `skyline.sonnet`) are not Bedrock model ids. A real deploy
  replaces them. The rule is "not a star", not "this string exists in the model catalog".

What breaks at 10× services in 10× VPCs: the endpoint hourly cost scales with VPCs, not with
requests. That is the moment to centralize the boot endpoints and to keep Bedrock's zone on its
own resource with its own rule. Do not fold Bedrock into the shared zone to save a diagram.
