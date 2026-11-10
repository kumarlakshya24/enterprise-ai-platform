# Failure modes

Each one is a hole in the current fixture, and the mitigation that is actually implemented.
"We would add a policy" is not a mitigation unless the gate fails when it is missing.

## The stub does not score hate, insults, or misconduct

The guardrail resource sets those three filters to HIGH. The stub has no classifier. `hate-unscored`
("you people are the worst") is `ALLOW`, tagged `content-filter`. The eval fails if that case starts
to intervene, and it fails if the case disappears. A green run cannot be described as "the guardrail
blocked toxic text".

Mitigation: the blind filters are metadata on the resource (`stubBlindFilters`) and a row in the
console. The enforced cases cover PII shapes, two topic phrases, and prompt-attack phrases. A phrase
list will miss a paraphrase and will fire on a sentence that quotes the phrase. That is the whole
stub.

What this does not fix: a production guardrail still depends on Bedrock's classifier for those three
filters. Skyline does not call it. The 25 ms figure in the report is a projection of that round trip,
not a measurement.

## IAM cannot prove the guardrail was applied

`AegisTaskRole` may call `bedrock:InvokeModel`. The endpoint policy allows the same role. Neither
statement's condition checks that `ApplyGuardrail` ran. A stolen task role can invoke the two fixture
model ARNs directly.

Mitigation that exists: the role is the only principal on the endpoint, Lumen and Switchboard deny
`bedrock:*`, the task is pinned to `GUARDRAIL_ID`, and deleting the guardrail resource fails
`guardrail-attached`. The network and the role list are enforced. The parameter is not.

What this does not fix: a VPC endpoint policy that conditions on a guardrail identifier, if the
service grows that condition key and we confirm it. Until then, do not tell a reviewer the template
makes an unguarded invoke impossible.

## Private endpoints cost more than a NAT gateway

Eighteen interface endpoints across two AZs are $8.64/day at the frozen rate. One NAT gateway is
$1.08/day. The byte savings on this mix do not pay the difference back below tens of millions of
requests/day. A dashboard that only showed the model savings would hide this.

Mitigation: the endpoint line and the NAT line are both on the unit-cost table, and
`endpoint_vs_nat_rpd` is in the eval output. ADR 0003 is the reason we pay it. ADR 0004 is the reason
we print it.

## Flow logs are not encrypted

Task log groups use an ops CMK. Flow log groups do not. A flow log is metadata, and it can still
carry an address you did not want in an unencrypted group.

Mitigation: none on the flow log group. Retention is 30 days. The gap is this paragraph. Encrypting
them means a key policy the logs delivery principal will accept, which is the next item.

## The ops key policy is the short form

CloudWatch Logs is particular about the encryption context and the caller. The fixture allows
`logs.<region>.amazonaws.com` with an `aws:logs:arn` condition. A real association can still fail
until the statement matches the current service principal and the log group's ARN exactly.

Mitigation: the policy is in the template so a reviewer can see the intent. It is not claimed to be
a paste from the console wizard. The tenant keys are held to a stricter rule because they are the
control. The ops keys are not.

## The organization trail is in the log-archive account

A real organization trail is created in the management account and delivered to log archive. This
fixture puts `AWS::CloudTrail::Trail` in log-archive, with validation and a customer key. There is
no management account in the six.

Mitigation: the rule checks that the trail validates, is logging, and is multi-region, and that it
lives in log-archive. It does not check for an account we did not model. Adding a management account
is a stack, not a comment. Until then the trail is the shape of the control, not a deployable org trail.

## The corporate network is a CIDR, not an attachment

Clients arrive from `10.8.0.0/16` over the transit gateway. The template does not contain the VPN,
Direct Connect, or the attachment in the corporate account. The hub routes `10.0.0.0/8` at the
gateway and trusts that the corporate side is attached.

Mitigation: the CIDR is data, and `0.0.0.0/0` fails the gate. The missing attachment is a gap. A
reviewer who asks "where is the VPN?" should hear "not in this fixture".

## Bucket per tenant, and a pinned role name

Three buckets is a clear key binding. A thousand tenants hits the bucket quota, and a pinned
`RoleName` makes the key policy readable and makes role replacement a name conflict.

Mitigation: three tenants, named. The architecture doc says what changes at a thousand. The role
name is a fixture choice so the golden JSON does not move. It is the wrong production default.

## Fixture model ids

`skyline.haiku` and `skyline.sonnet` are not Bedrock model ids. The prices in `eval/pricing.yaml`
are a frozen illustration of a Haiku-class and a Sonnet-class on-demand rate, not a pull from the
price list.

Mitigation: the README and the pricing file say so. The IAM resources are not `*`, which is the
property the gate checks. Swapping in real ids is a one-line change and a fixture update. Doing it
without updating the prices would make the bill lie. Do both in the same commit.

## The application can still log the prompt

Skyline ships a task definition and a log group. It does not ship Aegis. A container that logs the
raw prompt writes tenant data under the ops key, which is not the tenant CMK and is not covered by
the tenant rule.

Mitigation: none in the template. The log group is in the account that runs the task, retained 30
days, and encrypted with the ops key. The application standard, which lives in Aegis and not here,
is that the raw prompt is not a log line. This repo cannot enforce it.

## Keyword topics and the prompt-attack list

"buy the stock", "password is", "ignore previous instructions". A paraphrase walks through. A quote
of the phrase in a policy document trips it.

Mitigation: the cases are the list. Adding a phrase without a case is how the stub gets quieter or
louder without anyone noticing. Add the case in the same commit. Do not add a phrase because a demo
looked safer.

## Single region, two AZs, one transit gateway

The trail flag says multi-region. The VPCs do not exist in a second region. The transit gateway is
one control plane for every cross-account packet. Two tasks in two AZs do not help if the gateway
is the thing that failed.

Mitigation: the reliability pillar says this. There is no second gateway in the fixture, and adding
one without a test would be decoration. A second region is a new spec, not a checkbox.

## The gate does not know about resources it does not name

A new way to open the internet, a NAT gateway type we did not list, a principal star buried in a
policy document we do not walk, will pass. The rules walk security groups, routes, internet
gateways, key policies, the Bedrock endpoint, the hosted zone, IAM role statements, buckets, the
load balancer, and the trail.

Mitigation: the mutations are the regression suite for those walks. A new edge needs a new rule and
a mutation that fails it. Shipping the resource without the mutation is how this file grows a
paragraph you did not want.
