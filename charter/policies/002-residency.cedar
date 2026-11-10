// EU confidential and restricted payloads stay in eu-central-1.
// This file is the one a weakened candidate deletes. The permit in
// 003-permits.cedar would allow the US model for customer support.
// Forbid wins while this file is loaded. Without it, that permit allows
// the EU confidential ticket to leave the region.

// @id R-RESIDENCY-EU
// @controls EU-10
forbid (
  principal,
  action == Action::"invoke",
  resource
)
when {
  context.data_residency == "EU" &&
  resource.region != "eu-central-1" &&
  context.data_class in ["CONFIDENTIAL", "RESTRICTED"]
};
