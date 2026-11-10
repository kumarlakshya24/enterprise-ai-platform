// Models that must not be invoked, whatever the request says.
// A missing card, a prohibited tier, or a high-risk deployment with no reviewer
// is a forbid. A permit later in the bundle cannot override these.

// @id R-PROHIBITED
// @controls EU-5
forbid (
  principal,
  action,
  resource
)
when {
  resource.risk_tier == "unacceptable"
};

// @id R-CARD-INCOMPLETE
// @controls EU-11
forbid (
  principal,
  action,
  resource
)
when {
  resource.card_complete == false
};

// @id R-OVERSIGHT
// @controls EU-14
forbid (
  principal,
  action,
  resource
)
when {
  resource.risk_tier == "high" && resource.human_oversight == false
};

// @id R-RESTRICTED-BLOCK
// @controls EU-10
forbid (
  principal,
  action == Action::"invoke",
  resource
)
when {
  context.data_class == "RESTRICTED"
};
