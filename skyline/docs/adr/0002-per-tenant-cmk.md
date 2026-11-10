# ADR 0002: A CMK per tenant, with an encryption context

* Status: accepted
* Date: 2026-11-10

## Context

Lumen stores a tenant's documents. Aegis may wrap the same tenant's tokens. The easy key is one CMK
for the platform, with the tenant id written down as a tag or a bucket prefix. IAM then becomes the
only thing standing between tenant A and tenant B.

IAM gets this wrong in the usual ways. A policy uses `Resource: *` for a week. A role is shared
during an incident. A bucket policy allows the account root, which every admin is. None of those
mistakes should decrypt a second tenant.

SSE-S3 does not give you a key policy at all. A customer key per account, shared by every tenant in
that account, has the same shape as one platform key as soon as two tenants share the account. They
do. Lumen is one account.

## Decision

Each tenant gets a CMK in the security account.

* Alias `alias/skyline/<tenant>`.
* Rotation on.
* The root of the security account can administer the key. That statement is the recovery path, and
  it is the only statement without an encryption context.
* Aegis and Lumen may `Encrypt`, `Decrypt`, and `GenerateDataKey` only when
  `kms:EncryptionContext:tenant` equals that tenant.
* The tenant's bucket uses that key for default encryption. The gate reads the key id on the bucket,
  not the tag.

Switchboard does not get a grant. It does not store tenant documents.

Ops log groups use a different key in the account that writes the logs. The trail uses a different
key again. Those keys are not tenant keys, and the tenant-bucket rule does not accept them.

The planted break `shared-cmk` points the Helix and Brightline buckets at Northwind's key. The rule
`tenant-bucket-key` fails. `wildcard-kms` adds `Principal: "*"` to the Helix key and also omits the
context, so `kms-no-wildcard` and `kms-encryption-context` both fail.

## Consequences

Good:

* A confused Lumen role that forgets the tenant id fails closed at KMS, not open.
* The bill for three keys is a dollar a month each. The console shows it. It is not the reason to
  share a key.

Bad:

* The application has to pass the encryption context. The key policy cannot reach into a `PutObject`
  that used the bucket's default key and a different context. Default encryption on the bucket uses
  the tenant key, so an object written without an explicit context still uses the right key, and a
  caller who passes the wrong context is denied. A caller who is allowed the key and passes the
  right context for the wrong object is the remaining hole: the context is only as honest as the
  writer. Skyline does not deploy Lumen's writer. The app has to set the context to the tenant it
  authorized.
* Key policies use `Resource: "*"`, which is the normal shape, because the resource is the key the
  policy is attached to. The no-star rule applies to IAM role policies, not to key policies.
  `Principal: "*"` is forbidden on every key.
* `RoleName` is set so the key policy can name the role. Replacing a named role is a deploy hazard.
  A generated suffix would make the golden file move every synth, which this repo cannot accept.
  A real pipeline should accept the suffix and pass the ARN through an output. See failure modes.

What breaks at 10× tenants: still fine at thirty. At a thousand, CMK quota and a bucket per tenant
both hurt. The replacement is still a key per tenant, with a prefix inside fewer buckets and an
explicit key on each write. The gate would then look at the write path, which this fixture does not
have, because the application is not in the template.
