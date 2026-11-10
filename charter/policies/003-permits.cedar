// Permits are narrow on purpose, except the hosted support permit, which is
// deliberately wide so the residency forbid has something to override.
// No matching permit is a deny (R-DEFAULT-DENY). There is no "allow all".

// @id R-PERMIT-SUPPORT-EU
// @controls EU-9
permit (
  principal,
  action == Action::"invoke",
  resource == Model::"atlas-eu-mini"
)
when {
  context.purpose == "customer_support" &&
  context.data_class in ["PUBLIC", "INTERNAL", "CONFIDENTIAL"]
};

// @id R-PERMIT-HOSTED-SUPPORT
// @controls EU-9
permit (
  principal,
  action == Action::"invoke",
  resource == Model::"frontier-us-large"
)
when {
  context.purpose == "customer_support" &&
  context.data_class in ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
};

// @id R-PERMIT-PUBLIC-US
// @controls EU-13
permit (
  principal,
  action == Action::"invoke",
  resource == Model::"frontier-us-large"
)
when {
  context.purpose == "public_faq" &&
  context.data_class == "PUBLIC"
};

// @id R-PERMIT-CREDIT
// @controls EU-14
permit (
  principal,
  action == Action::"invoke",
  resource == Model::"credit-eu-scorer"
)
when {
  context.purpose == "credit_decision" &&
  context.data_residency == "EU" &&
  context.data_class in ["INTERNAL", "CONFIDENTIAL"]
};

// @id R-PERMIT-CLAIMS
// @controls EU-14
permit (
  principal,
  action == Action::"invoke",
  resource == Model::"claims-triage-eu"
)
when {
  context.purpose == "claims_triage" &&
  context.data_residency == "EU" &&
  context.data_class in ["PUBLIC", "INTERNAL", "CONFIDENTIAL"]
};
