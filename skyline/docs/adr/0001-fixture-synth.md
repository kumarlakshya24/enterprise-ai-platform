# ADR 0001: Fixture synth, not a live CDK deploy

* Status: accepted
* Date: 2026-11-10

## Context

The portfolio has to run with no AWS account and no credentials. A reviewer should still be able to
see a multi-account design and a diff.

Two ways to get there:

1. Import `aws-cdk-lib`, call `App.synth()`, and hope the cloud assembly is stable.
2. Write the resources ourselves as CloudFormation-shaped JSON and pin the bytes.

The CDK app is the real tool a platform team would reach for. It is a poor demo here. Synth looks up
context, rewrites asset hashes, and emits tokens that move between versions. A green diff then means
"the CLI version matched", not "the design matched". It also pulls a large dependency so that
`make test` can import constructs the demo never deploys.

## Decision

Skyline has a small builder. Stacks are dicts. `canonical()` sorts keys and appends a newline.
`fixtures/assembly.json` is that string. `make diff` exits 1 when the synth is not those bytes.

Account ids, the transit gateway id, and KMS key ids are fixture ids. Real ones are assigned at
create time. The fixture says so in the manifest disclaimer and in the transit gateway output.

`SKYLINE_PROVIDER` defaults to `fixture`. Any other value refuses to start. There is no code path
that constructs a boto3 client.

## Consequences

Good:

* The diff is a reviewable JSON diff. A security group change shows up as a path.
* Tests do not need a network, a CLI, or an account.
* The invariants read the same document CI pins.

Bad:

* This is not the CDK output and not a schema-validated template. `cfn-lint` is not in the loop.
  A property AWS would reject can still pass our rules. The failure mode is documented, and the
  rules check the properties we claim to care about rather than a free-form comment.
* Cross-stack references are literal ids, not `Fn::ImportValue`. A real pipeline would wire those.
  The literal id is what makes the golden file readable.
* Someone can add a resource our rules do not look at. A new internet-shaped resource needs a new
  rule. The planted mutations are the regression suite for the rules we have, not a proof that the
  rule list is complete.

What breaks at 10×: custom resources, assets, and lookups. Each one would have to be modeled, or
the fixture stops being the source of truth. That is the point at which this ADR should be
revisited in favor of CDK with a pinned CLI and context frozen in `cdk.context.json`.
