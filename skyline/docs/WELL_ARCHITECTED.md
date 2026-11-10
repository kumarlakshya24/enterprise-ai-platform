# Well-Architected notes

This is a design review of the fixture, not an AWS Well-Architected tool run. Each pillar names the
resource a reviewer can open in `fixtures/assembly.json` and the gap the fixture does not close.
The console renders the same six notes from `skyline/review.py`, and the test fails if a cited
logical id disappears.

## Operational excellence

**How do you know a change is the one you reviewed?**

The synth is deterministic. `make diff` compares it to the fixture. `make gate` runs twenty rules.
`make gate-seeded` opens Aegis to `0.0.0.0/0` and must exit 1. The rule id is the review comment.

Evidence: `log-archive/OrgTrail`, `finops/PlatformBudget`. The trail is the record of API calls once
this is a real organization. The budget is the ceiling, not the forecast.

Gap: the gate reviews a template. It does not watch a running account. Drift after deploy is
invisible here.

## Security

**What may reach a model, and with whose key?**

Workload subnets are private. There is no internet gateway. The Bedrock endpoint is in the security
VPC, its policy names `AegisTaskRole`, and the private zone is not associated with Lumen.
Lumen and Switchboard deny `bedrock:*`. Each tenant bucket uses that tenant's CMK, and the key
requires `kms:EncryptionContext:tenant`.

Evidence: `security/TenantKeyNorthwind`, `security/BedrockRuntimeEndpoint`,
`security/BedrockPrivateZone`, `security/Guardrail`.

Gap: the template cannot prove `ApplyGuardrail` ran. A stolen Aegis role can invoke the named models.
See [FAILURE_MODES.md](FAILURE_MODES.md).

## Reliability

**What is still a single point after two AZs?**

Each VPC has two private subnets. Each service asks for two tasks. The model path does not depend
on a NAT gateway. The transit gateway is still one attachment point for every account.

Evidence: `security/AegisService` (desired count 2, private subnets), `network/TransitGateway`.

Gap: losing the transit gateway stops Aegis from reaching Lumen and Switchboard. There is no second
gateway and no region pair.

## Performance efficiency

**Where does a request spend time, and what did we refuse to measure?**

Switchboard still chooses the model. The Bedrock call, when the route is not local, stays on the
interface endpoint. This repo measures the time to synth and the time to run the stub. It does not
measure Bedrock, KMS, or the transit gateway.

Evidence: `switchboard/SwitchboardService`, `security/BedrockRuntimeEndpoint`.

Gap: the 25 ms guardrail figure, the 4 ms KMS miss, and the 20–40 ms of internet RTT the endpoint
removes are projections in the eval output. They are labeled. They are not SLOs.

## Cost optimization

**What does a thousand requests cost, once the platform is included?**

Model mix is the large saving, about $5.98 per thousand requests on this mix. The guardrail, scanning
the user turn and the output, is about $2.91. Scanning retrieved context as well would be about
$14.89 and is not what the template does. Endpoints are $8.64/day against $1.08/day for one NAT.
Skyline's fully loaded unit cost crosses under the naive path at a few thousand requests/day and is
the more expensive one below that.

Evidence: `finops/PlatformBudget`, `security/Guardrail`. The budget resource is an illustrative $250
monthly ceiling. The forecast is the console, not that resource.

Gap: `eval/pricing.yaml` is a frozen list, not the Price List API and not an invoice. CloudWatch
ingestion, inter-AZ transfer, and data events are omitted and listed in the architecture doc.

## Sustainability

**Which requests never needed the largest model?**

The mix sends FAQ and cited answers to a Haiku-class model and pins confidential text to a local
model. The agent step stays on a Sonnet-class model. That is the only sustainability control this
platform has. It is a token reduction.

Evidence: `switchboard/SwitchboardService`, `security/AegisTaskDefinition`. The task is where the
route is consumed. The mix itself is `eval/workload.yaml`.

Gap: no carbon number is claimed. A smaller model is not a footprint audit.

## How this maps to the tool

The Well-Architected tool asks for evidence from a running workload: alarms, game days, recovery
tests. This repo's evidence is a fixture, a gate, and a price model. Using the tool's icons on a
diagram without those operational artifacts would over-claim. The six sections above are the review
we can stand behind.
