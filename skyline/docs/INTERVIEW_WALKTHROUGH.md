# Interview walkthrough

`make interview` prints this file. Dollar figures are from the saved eval (fixture hash `b36ea7aef3257f13`,
the mix in `eval/workload.yaml`, the rates in `eval/pricing.yaml`). Synth time and the stub's mean are
measured on each run and are not pinned. The committed eval bounds them at 50 ms and 100 µs. Nothing
here is a bill, and nothing here called AWS.

## 1. Thirty-second pitch

Aegis, Lumen, and Switchboard each run on a laptop. The day they share a cloud, the tutorial shape
shows up: a public load balancer, one KMS key, and a NAT gateway in front of the model. Skyline is the
platform definition that refuses that shape. It synthesizes six accounts as CloudFormation-shaped JSON,
diffs the bytes against a fixture, and fails a named rule if a change opens the world, shares a tenant
key, drops the guardrail, or lets Lumen call Bedrock. The same run prices a thousand requests, including
the part where private endpoints cost more than a NAT gateway. No AWS account and no API key.

## 2. Who it is for

The platform team that already has Aegis, Lumen, and Switchboard as products and does not yet have an
account layout they can review. Not the employee asking the question. They should not wait on a synth.

The concrete job: someone wants to "just add a public load balancer for the demo" or "just use one key
so the policy is shorter". You want a deterministic no, with the resource path, before that template
is the one people copy. And you want the cost of the private path on the same page, so the security
decision is not smuggled in as a saving.

## 3. Architecture tour

Stay on the diagrams in [ARCHITECTURE.md](../ARCHITECTURE.md). Five beats.

1. **Six accounts, one packet.** Corporate CIDR, transit gateway, internal ALB, Aegis, guardrail,
   Switchboard for the route, Bedrock only if the route is not local. Lumen is off to the side with
   the documents. Log archive and FinOps do not sit on the request path.
2. **The controls have to agree.** No internet gateway. The Bedrock endpoint is in the security VPC
   and its policy names `AegisTaskRole`. Lumen and Switchboard deny `bedrock:*`. The private zone is
   not associated with Lumen. Each tenant bucket uses that tenant's CMK, and the key requires the
   encryption context.
3. **Decisions at a glance.** Fixture JSON instead of live CDK. A key per tenant instead of one
   platform key. Endpoints instead of a NAT, knowing the endpoints cost more per day. Guardrail on
   the user turn and the output, not on the retrieved context.
4. **Happy path, then the two failure paths.** The sequence diagram is the request. The other failure
   path is a template change: synth, diff against the fixture, twenty rules. A guardrail `INTERVENE`
   is the request-path failure. An insult staying `ALLOW` is the honest gap, and the eval locks it open.
5. **The unit cost has a volume knob.** Fixed cost smeared over 1,000 requests/day is a different
   number from the same cost smeared over 100,000. The console makes you pick.

## 4. Deep dive: private is not cheaper, and that is the point

The hard decision is ADR 0003 together with ADR 0004.

Eighteen interface endpoints, two AZs each, are **$8.64/day** at the frozen rate. One NAT gateway is
**$1.08/day**. The requests in this mix are kilobytes. Per-GB savings do not pay the hourly gap back
below about **28.8 million requests/day**. I will not tell you the private network saves money. It
removes the internet from the trust boundary. A NAT "just for ECR" becomes a default route the moment
a subnet is wrong, so the template has no NAT at all.

What I rejected:

* A shared private zone for every endpoint, Bedrock included. That is how Lumen starts resolving the
  model. `share-bedrock-dns` is that mistake, and `bedrock-dns-not-shared` fails it.
* Hiding the endpoint line inside the model savings. At 100,000 requests/day the model mix saves
  **$5.98** per thousand requests and the guardrail puts **$2.91** back. Net, Skyline is **$6.26**
  per thousand against **$9.20** for always-Sonnet plus one NAT. At 1,000 requests/day Skyline is
  **$22.28** against **$12.79**. The crossing is **4,094 requests/day**. Below it you are paying for
  the platform. Above it the model mix pays for the platform and the guardrail.
* Scanning retrieved context. That prices the guardrail at **$14.89** per thousand, which is more than
  the routing saves. Lumen already decides which document you may read. The guardrail sees the user
  turn and the model output.

The key decision is the same shape. Three tenant CMKs are about a dollar a month each. They are not
on the bill because they are expensive. They are on the bill so nobody deletes them to save three
dollars. `shared-cmk` points Helix and Brightline at Northwind's key and fails `tenant-bucket-key`.

## 5. Demo script

From `skyline/`:

```bash
make test
make eval
make gate
make gate-seeded ; echo "exit $?"
make up
```

What you should see:

* `make test` green. Twenty rules on the clean synth, seven mutations, the unit-cost arithmetic, the
  guardrail cases, the console.
* `make eval` prints the hash and `20/20`, and rewrites the README between the markers. It also prints
  a synth time and a stub mean. Those two move. The dollars do not.
* `make gate` exits 0.
* `make gate-seeded` exits 1. The finding names `AegisSecurityGroup` and `0.0.0.0/0`.

Then the console at <http://127.0.0.1:8099>:

* Skyline of six accounts. Security is the tallest, because that is where Aegis, the keys, the
  guardrail, and the only Bedrock endpoint sit.
* Volume at 100,000/day, then 1,000/day. The headline flips from cheaper to more expensive.
* **Open the security group.** The rule `no-world-cidrs` goes red and the diff is on the page.
  **Clean** puts it back.
* The guardrail list. A card and a prompt attack intervene. "you people are the worst" stays allowed
  and is tagged as a gap.

`make interview` prints this file. It does not start a server.

## 6. What the numbers prove, and what they do not

Prove:

* The clean template satisfies the twenty rules, and each planted break fails the rule it was written
  for. That is a regression suite, not a penetration test.
* On this mix and this price list, routing is worth $5.98 per thousand requests before the platform.
  The guardrail we actually scan is $2.91. The guardrail we refused to scan would be $14.89.
* Fully loaded, Skyline is the expensive unit at 1,000 requests/day and the cheap one at 10,000 and
  above, crossing at 4,094. Endpoints versus one NAT do not cross inside the presets.
* The stub agrees with the enforced cases: card, email, phone, access-key shape, two topic phrases,
  one prompt attack. The insult is allowed, and the suite fails if that stops being true.
* The synth matches `fixtures/assembly.json` byte for byte. Hash `b36ea7aef3257f13`.

Do not prove:

* That AWS would accept every property. There is no `cfn-lint` and no CDK schema in the loop.
* That Bedrock's classifier would block the insult. The filters are HIGH on the resource. The stub
  does not score them. The 25 ms, the 4 ms KMS miss, and the 20–40 ms of avoided internet RTT are
  projections.
* That the prices are this month's list. They are a frozen illustration. Replace the file before a
  budget meeting, and change the model ids in the same commit.
* That a running account still matches the fixture. The gate does not watch drift after deploy.
* That Aegis actually calls `ApplyGuardrail`. The template pins an environment variable and a role.
  A stolen role can still `InvokeModel`.

## 7. What I would do next

* A management account that owns the organization trail, and a real corporate attachment instead of
  a CIDR comment.
* Confirm the CloudWatch Logs key policy against the current service principal, and encrypt the flow
  logs with it.
* Replace `skyline.haiku` and `skyline.sonnet` with the model ids the account has enabled, and
  replace the rates in the same commit.
* If the endpoint bill ever matters more than the isolation, centralize ECR, logs, and STS in the hub.
  Leave `BedrockPrivateZone` as its own resource. Do not fold Bedrock into the shared zone to save
  a diagram.

## 8. Questions worth asking

**Why not CDK?** Because a diff that moves with the CLI version is not a review. The tradeoff is that
our JSON is not schema-validated. ADR 0001.

**Why can the security account root still use every tenant key?** That is the recovery statement.
Every other statement requires the tenant context. A root that is compromised is a different incident
from a tenant role that is confused.

**Why is the guardrail not on the retrieved passages?** Because at these rates that scan costs more
than the routing saves, and Lumen already filtered the corpus by who is asking. ADR 0004.

**What if I need a NAT for a vendor that has no endpoint?** Then it gets its own route table, not the
workload default, and a rule that fails when `0.0.0.0/0` shows up on a task subnet. Today the answer
is that the vendor is not in this fixture, and there is no NAT to grow the wrong route from.
