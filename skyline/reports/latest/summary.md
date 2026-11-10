Synth `fixture-cdk` in us-east-1. Hash `b36ea7aef3257f13`. 6 accounts, 122 resources. Invariants 20/20. Guardrail stub 10/10 enforced cases, 1 known unscored gap.

Fully loaded USD per 1,000 requests of the mix in `eval/workload.yaml`. Fixed cost is smeared across the stated requests/day. Prices are the frozen list in `eval/pricing.yaml`, not an invoice.

| Requests/day | Skyline | Always Sonnet-class + one NAT | Skyline cheaper by |
|---:|---:|---:|---:|
| 1,000 | $22.28 | $12.79 | -$9.49 |
| 10,000 | $7.71 | $9.53 | $1.81 |
| 100,000 | $6.26 | $9.20 | $2.94 |
| 1,000,000 | $6.11 | $9.17 | $3.06 |

At 100,000 requests/day the lines are:

| Line | Skyline | Naive |
|---|---:|---:|
| Model tokens | $3.18 | $9.16 |
| Guardrail, user turn and output | $2.91 | $0.00 |
| Network bytes | $0.000075 | $0.000337 |
| Transit gateway bytes | $0.000288 | $0.00 |
| KMS data keys, 1% cache miss | $0.000030 | $0.000030 |
| Endpoint hours or NAT hours | $0.0864 | $0.0108 |
| Transit gateway attachments | $0.0480 | $0.00 |
| CMK months, smeared | $0.002333 | $0.000333 |
| Fargate, same three services | $0.0178 | $0.0178 |
| Internal load balancer | $0.007320 | $0.007320 |

Model routing saves $5.98 per 1,000 requests before the platform. The guardrail, scanning the user turn and the model output, adds $2.91. Scanning the full prompt, retrieved context included, would add $14.89 and is not what the template does.

Skyline's fully loaded unit cost drops below the naive path above **4,094 requests/day**.

Interface endpoints are $8.64/day against $1.08/day for the single NAT in the counterfactual. Per-GB savings would not pay that premium back below about 28,810,961 requests/day.

Measured bounds. A run that takes longer fails `make eval`. The exact sample is printed by the command and is not pinned, because it moves with the machine.

| Measurement | Bound |
|---|---:|
| Synth, including the invariant walk | under 50 ms |
| Guardrail stub, mean | under 100 µs |

Projections, labeled so they are not read as measurements:

| Hop | Figure | Why it is not a measurement |
|---|---:|---|
| Bedrock guardrail round trip | 25 ms | Order of magnitude for a Bedrock Guardrails round trip. This demo does not call Bedrock. |
| KMS GenerateDataKey, cache miss | 4 ms | A typical GenerateDataKey on a cache miss. The mix assumes a 1% miss. |
| KMS, cache hit | 0 ms | The application cache. Not a resource in this synth. |
| Public internet RTT avoided | 20-40 ms | Internet RTT the private endpoint removes. Not measured from this machine. |

Planted breaks. Each one must fail the named rule. A clean synth fails none.

| Mutation | Rule that must fail |
|---|---|
| `open-sg` | `no-world-cidrs` |
| `shared-cmk` | `tenant-bucket-key` |
| `drop-guardrail` | `guardrail-attached` |
| `public-route` | `no-internet-gateway` |
| `lumen-bedrock` | `no-bedrock-outside-aegis` |
| `wildcard-kms` | `kms-no-wildcard` |
| `share-bedrock-dns` | `bedrock-dns-not-shared` |

Quantities read off the template, which is what the fixed cost multiplies:

| Quantity | Count |
|---|---:|
| Customer managed keys | 7 |
| Guardrails | 1 |
| Interface endpoint-AZ pairs | 36 |
| Interface endpoints | 18 |
| Load balancers | 1 |
| Fargate memory, GB running | 3.000000 |
| Fargate vCPU running | 1.500000 |
| Transit gateway attachments | 4 |
