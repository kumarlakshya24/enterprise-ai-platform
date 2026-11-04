"""Generate the synthetic, labelled training corpus for the sensitivity classifier.

Seeded and deterministic. The held-out test set (data/classifier/test.jsonl) is written by hand
with different phrasing so the reported accuracy measures generalization, not template recall.

    python scripts/generate_classifier_data.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20261104
PER_LABEL = 320
OUT = Path(__file__).resolve().parents[1] / "data" / "classifier" / "train.jsonl"

SLOTS: dict[str, list[str]] = {
    "quarter": ["Q1", "Q2", "Q3", "Q4", "next quarter", "the second half", "January", "this fall"],
    "pct": ["8%", "12%", "15%", "18%", "22%", "30%", "5 percent", "a third"],
    "amount": ["$2.4M", "$850k", "$12 million", "$400,000", "$1.1M", "$75k"],
    "team": [
        "EMEA sales",
        "the platform team",
        "customer success",
        "support",
        "marketing",
        "the data team",
        "finance",
        "the mobile team",
        "field engineering",
        "recruiting",
    ],
    "product": [
        "the Starter tier",
        "the Enterprise plan",
        "Project Falcon",
        "the v5 release",
        "the analytics add-on",
        "our mobile app",
        "the new billing system",
        "Helios",
        "the partner API",
    ],
    "region": ["EMEA", "APAC", "North America", "LATAM", "the UK", "Germany"],
    "tech": [
        "Python",
        "Kubernetes",
        "PostgreSQL",
        "React",
        "Kafka",
        "Docker",
        "Terraform",
        "Rust",
        "Go",
        "SQL",
        "Redis",
        "GraphQL",
        "TypeScript",
        "Spark",
        "Linux",
    ],
    "topic": [
        "exponential backoff",
        "binary search",
        "OAuth2 flows",
        "database indexing",
        "unit testing",
        "rate limiting",
        "caching strategies",
        "event sourcing",
        "REST API design",
        "load balancing",
        "memory leaks",
        "gradient descent",
        "CAP theorem",
        "regular expressions",
        "TLS handshakes",
    ],
    "doc": [
        "a blog post",
        "a README",
        "a tweet",
        "a cover letter",
        "a haiku",
        "a short story",
        "a product FAQ",
        "a conference talk abstract",
        "a LinkedIn post",
        "release notes for an open source library",
    ],
    "issue": [
        "a delayed shipment",
        "a duplicate charge",
        "a login problem",
        "a broken export",
        "a missing invoice",
        "a password reset loop",
        "a damaged package",
        "an incorrect refund",
        "slow page loads",
    ],
    "placeholder_person": ["[PERSON_NAME]", "the customer", "[PERSON_NAME] from [ORG]", "a user"],
    "competitor": ["our main competitor", "a rival vendor", "a larger competitor", "a smaller startup"],
    "role": [
        "a senior engineer",
        "the sales director",
        "a product manager",
        "two support reps",
        "the VP of sales",
    ],
    "vuln": [
        "SQL injection",
        "remote code execution",
        "an authentication bypass",
        "an SSRF",
        "a deserialization flaw",
    ],
    "system": [
        "the auth service",
        "the payments API",
        "our admin portal",
        "the billing database",
        "the SSO gateway",
    ],
    "condition": ["diabetes", "a cancer diagnosis", "HIV status", "a psychiatric condition", "pregnancy"],
}

FRAMES: dict[str, list[str]] = {
    "PUBLIC": [
        "How do I implement {topic} in {tech}?",
        "Explain {topic} to a junior developer.",
        "What is the difference between {tech} and {tech}?",
        "Write {doc} about learning {tech}.",
        "Give me three tips for {topic}.",
        "Can you summarize how {topic} works?",
        "What are common mistakes with {topic} in {tech}?",
        "Write a function in {tech} that reverses a string.",
        "Suggest a title for {doc} about remote work.",
        "Translate 'good morning, how are you' into Spanish.",
        "What is a good way to structure {doc}?",
        "Recommend books about {topic}.",
        "Fix the grammar in this sentence: their going to the park tomorrow.",
        "What does HTTP status 429 mean and how should a client react?",
        "Compare {tech} and {tech} for a small hobby project.",
        "Write a regex that matches ISO dates.",
        "Explain the history of the printing press in two paragraphs.",
        "What are best practices for {topic}?",
        "Help me write {doc} for a general audience.",
        "Give me a beginner study plan for {tech}.",
        "Write a unit test example for a function that adds two numbers.",
        "What is the time complexity of quicksort?",
        "Outline a talk about {topic} for a public meetup.",
        "Brainstorm names for a public open source project about {topic}.",
        "What is the capital of Australia and why was it chosen?",
        "Draft a polite generic email declining a meeting invitation.",
        "Explain how vaccines train the immune system, in simple terms.",
        "Convert this recipe for four people into one for two people.",
        "What are the pros and cons of {tech} for web development?",
        "How should I prepare for a system design interview?",
    ],
    "INTERNAL": [
        "Draft a reply to {placeholder_person} about {issue}.",
        "Summarize this support ticket: {placeholder_person} reported {issue} and wants an update.",
        "Write meeting notes: {team} discussed sprint priorities and the on-call rotation.",
        "Create a Jira ticket for {issue} reported by {placeholder_person}.",
        "Turn these standup notes into a status update: migration is 60% done, two bugs open.",
        "Write an internal FAQ about our expense reimbursement process.",
        "Draft an onboarding checklist for new hires joining {team}.",
        "Summarize the retro from {team}: deploys were slow, alerts were noisy.",
        "Rewrite this customer email more politely: {placeholder_person} is upset about {issue}.",
        "Write a knowledge base article on how support should handle {issue}.",
        "Prepare an agenda for the {team} weekly sync.",
        "Draft a Slack message reminding {team} to submit timesheets by Friday.",
        "Customer {placeholder_person} with email [EMAIL] says {issue}; draft an apology.",
        "Reply to [PERSON_NAME] at [EMAIL] confirming we refunded the charge on [CREDIT_CARD].",
        "Complaint from [PERSON_NAME]: charged twice on card [CREDIT_CARD], wants a refund. Draft a response.",
        "Write a handover note for the support shift: three tickets about {issue} are open.",
        "Summarize the incident postmortem for the internal wiki: a config change caused slow page loads.",
        "Draft an internal announcement that the office will be closed on Monday.",
        "Help me write a runbook step for restarting the reporting job.",
        "Write release notes for internal users of {product} describing two bug fixes.",
        "Clean up these call notes from a customer check-in: they like the dashboard, want CSV export.",
        "Classify these support tickets by topic: login, billing, shipping.",
        "Draft a reply to [PERSON_NAME] explaining the shipping delay and offering tracking info.",
        "Write a project kickoff email for {team} with roles and the timeline.",
        "Summarize the feedback from the internal beta of {product}.",
        "Make a checklist for closing a support ticket about {issue}.",
        "Draft talking points for the all-hands about our new on-call tool.",
        "Write a short internal survey about the new laptop setup process.",
        "Respond to [PERSON_NAME] who called [PHONE] asking about {issue}.",
        "Summarize this thread between support and engineering about {issue}.",
    ],
    "CONFIDENTIAL": [
        "We will discontinue {product} in {quarter} and raise prices {pct}; draft the internal plan.",
        "The roadmap for {product} is not public yet: we plan to launch in {quarter}. Write talking points.",
        "We are planning layoffs of {pct} in {team} next month. Draft the manager script.",
        "Acquisition talks with {competitor} are ongoing and unannounced; summarize the strategic rationale.",
        "Our {quarter} revenue will miss guidance by {pct}. Draft the explanation for leadership.",
        "Salary bands for {role} are being cut by {pct}; prepare an FAQ for HR.",
        "Write a performance improvement plan for {role} who keeps missing deadlines.",
        "The largest customer is threatening to churn over the outage; their {amount} renewal is at risk.",
        "Draft the pricing proposal: {amount} discount for the strategic account, do not share externally.",
        "Our churn rate rose to {pct} in {region}; prepare the internal analysis for the exec team.",
        "Summarize the contract terms we offered {competitor}'s biggest client: {amount} over three years.",
        "We had a security incident in {system} last week that we have not disclosed yet. Draft the summary.",
        "Plan the reorganization: {team} will be merged into product and two directors will be let go.",
        "Draft the internal memo about the hiring freeze in {region} starting {quarter}.",
        "Here is the unreleased financial forecast: {amount} burn per month. Turn it into slides.",
        "Write the negotiation strategy for the {amount} enterprise deal; our walk-away price is lower.",
        "The board is considering selling {product}; summarize the options for my staff.",
        "Our gross margin dropped {pct} because of cloud costs; draft the internal explanation.",
        "HR complaint about {role}: harassment allegations under investigation. Summarize next steps.",
        "Compensation review: {role} will get a {pct} raise, others none. Draft the letters.",
        "We are moving {team} offshore in {quarter}; nobody has been told yet. Draft the timeline.",
        "Customer health report: the top three accounts in {region} are at risk, worth {amount}.",
        "Draft the competitive response plan: we will undercut {competitor} by {pct} before their launch.",
        "Our {quarter} sales pipeline is {amount} short of plan; draft the update for the CRO.",
        "Prepare talking points about the upcoming price increase of {pct} before it is announced.",
        "Internal planning: sunset {product} and migrate customers to the Enterprise plan by {quarter}.",
        "Write the termination letter for {role} effective Friday.",
        "Draft a memo on the unannounced partnership with {competitor} launching in {quarter}.",
        "Summarize the investor update draft: runway is 14 months, raising {amount} in {quarter}.",
        "The engineering headcount plan cuts {pct} of contractors; prepare the vendor notice.",
    ],
    "RESTRICTED": [
        "Attorney-client privileged: summarize counsel's assessment of our exposure in the patent lawsuit.",
        "Material non-public information: merger agreement with {competitor} at {amount} per share, closing {quarter}.",
        "Board-only: the CEO is being replaced next month. Draft the succession announcement.",
        "There is an unpatched {vuln} in {system}; here is how to exploit it step by step. Write it up.",
        "Patient records: list of employees with {condition} for the benefits review.",
        "Privileged legal memo: settlement strategy for the class action, maximum payout {amount}.",
        "Draft the 8-K disclosure for the acquisition before the announcement; terms are {amount}.",
        "Insider information: earnings will beat consensus by {pct}; prepare remarks before release.",
        "Legal hold: summarize the deposition prep notes for the regulatory investigation.",
        "Exploit details for the zero-day in {system}: bypass MFA by replaying the session token.",
        "Medical leave file: the employee disclosed {condition}; summarize accommodations.",
        "Board minutes, confidential session: approve the {amount} write-down and executive departures.",
        "Our lawyers advise that we likely violated export controls; draft the privileged response.",
        "Merger integration plan under NDA: {competitor} deal terms and the layoff list by name.",
        "Write up the penetration test findings for {system} including working payloads for {vuln}.",
        "Regulator inquiry, privileged and confidential: draft our response on the data breach scope.",
        "The tender offer price for {competitor} is {amount}; nobody outside the deal team may know.",
        "Health insurance claims data for staff with {condition}; analyze the cost trend.",
        "Counsel's draft of the whistleblower response, attorney work product.",
        "Root credentials and recovery codes for {system} are in this note; organize them.",
    ],
}

PREFIXES = ["", "", "", "Please ", "Can you help: ", "Quick one. ", "Hey, ", "For tomorrow: ", "Urgent: "]
SUFFIXES = [
    "",
    "",
    "",
    " Keep it short.",
    " Use bullet points.",
    " Make it friendly.",
    " Thanks!",
    " Two paragraphs max.",
    " Write it for a busy reader.",
]


def fill(frame: str, rng: random.Random) -> str:
    out = frame
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        key = out[start + 1 : end]
        out = out[:start] + rng.choice(SLOTS[key]) + out[end + 1 :]
    return out


def generate(seed: int = SEED, per_label: int = PER_LABEL) -> list[dict[str, str]]:
    rng = random.Random(seed)  # noqa: S311 - seeded data generation, not crypto
    rows: list[dict[str, str]] = []
    for label, frames in FRAMES.items():
        seen: set[str] = set()
        attempts = 0
        while len(seen) < per_label and attempts < per_label * 30:
            attempts += 1
            text = rng.choice(PREFIXES) + fill(rng.choice(frames), rng) + rng.choice(SUFFIXES)
            if text not in seen:
                seen.add(text)
                rows.append({"text": text, "label": label})
    rng.shuffle(rows)
    return rows


def main() -> None:
    rows = generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    print(f"wrote {len(rows)} rows to {OUT}: {counts}")


if __name__ == "__main__":
    main()
