"""Run all five demo scenarios against a running gateway and check the expected outcomes.

    python scripts/demo.py                       # http://localhost:8080
    python scripts/demo.py --base-url http://host:8080

Exits non-zero if any expectation fails, so it doubles as an end-to-end smoke test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aegis.demo.scenarios import SCENARIOS_BY_ID as S

GREEN, RED, DIM, BOLD, END = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


class Demo:
    def __init__(self, base: str) -> None:
        self.http = httpx.Client(base_url=base, timeout=30)
        self.tokens: dict[str, str] = {}
        self.failures = 0

    def token(self, user: str) -> str:
        if user not in self.tokens:
            r = self.http.post("/demo/login", json={"username": user})
            r.raise_for_status()
            self.tokens[user] = r.json()["access_token"]
        return self.tokens[user]

    def call(self, method: str, path: str, user: str, json: dict[str, Any] | None = None) -> httpx.Response:
        return self.http.request(
            method, path, json=json, headers={"Authorization": f"Bearer {self.token(user)}"}
        )

    def check(self, ok: bool, label: str) -> None:
        print(f"  {GREEN + 'PASS' if ok else RED + 'FAIL'}{END} {label}")
        self.failures += 0 if ok else 1

    def third_party_saw(self) -> str:
        ev = self.call("GET", "/demo/evidence", "avery").json()
        return "\n".join(str(m.get("content")) for e in ev["external_llm"] for m in e["messages"])

    def reset(self) -> None:
        self.call("POST", "/demo/reset", "avery")

    # ------------------------------------------------------------------ scenarios

    def s1(self) -> None:
        print(f"\n{BOLD}1. Direct paste leak{END}")
        text = S["s1_direct_paste"]["input"]
        raw = ("Dana Holloway", "4111 1111 1111 1111", "dana.holloway@example.com")
        self.reset()
        self.call("POST", "/demo/unprotected/chat", "avery", {"message": text})
        seen = self.third_party_saw()
        self.check(all(v in seen for v in raw), "unprotected: third party received name, card, and email")
        self.reset()
        body = self.call("POST", "/chat", "avery", {"message": text}).json()
        seen = self.third_party_saw()
        print(f"  {DIM}sent: {body['sent_to_llm']['prompt'][:120]}...{END}")
        self.check(not any(v in seen for v in raw), "protected: third party received placeholders only")
        self.check(
            "Dana Holloway" in body["answer"] and "•••• 1111" in body["answer"],
            "protected: answer restored for Avery, card masked to last 4",
        )
        print(f"  {DIM}gateway overhead {body['latency_ms']['gateway_overhead_ms']} ms{END}")

    def s2(self) -> None:
        print(f"\n{BOLD}2. Context leak with no pattern{END}")
        self.reset()
        body = self.call("POST", "/chat", "avery", {"message": S["s2_context_leak"]["input"]}).json()
        d = body["decision"]
        self.check(
            body["entities"] == [] and d["regex_only_baseline"]["sends_to_external_llm"],
            "regex finds nothing; a pattern-only DLP would send it out",
        )
        clf = d["classifier"]
        print(
            f"  {DIM}classifier {clf['label']} {clf['confidence']} features "
            f"{[f['feature'] for f in clf['top_features']]}{END}"
        )
        self.check(
            d["route"] in ("local_only", "block") and "Starter tier" not in self.third_party_saw(),
            f"classifier + router kept it inside the boundary ({d['route']})",
        )

    def s3(self) -> None:
        print(f"\n{BOLD}3. Tool exfiltration{END}")
        a = self.call("POST", "/agent/run", "avery", {"task": S["s3a_tool_exfil_personal"]["input"]}).json()
        rules = {r["rule"] for s in a["steps"] if s.get("guard") for r in s["guard"]["reasons"]}
        self.check(
            a["status"] == "blocked" and "R-TOOL-PERSONAL-DOMAIN" in rules, "personal Gmail recipient blocked"
        )
        b = self.call("POST", "/agent/run", "avery", {"task": S["s3b_tool_exfil_corporate"]["input"]}).json()
        self.check(b["status"] == "pending_approval", "corporate recipient queued for approval")
        aid = b["approval_id"]
        r = self.call("POST", f"/approvals/{aid}/approve", "avery", {})
        self.check(r.status_code == 403, "requester cannot approve their own request (four eyes)")
        r = self.call("POST", f"/approvals/{aid}/approve", "morgan", {"note": "demo"})
        self.check(
            r.status_code == 200 and r.json()["status"] == "executed", "approver Morgan approves; email sent"
        )
        outbox = self.call("GET", "/demo/evidence", "avery").json()["sandbox"]["outbox"]
        mail = next((m for m in reversed(outbox) if m["mode"] == "protected"), {})
        self.check(
            "•••• 1111" in mail.get("body", "") and "4111 1111" not in mail.get("body", ""),
            "delivered internally with the card masked",
        )

    def s4(self) -> None:
        print(f"\n{BOLD}4. Prompt injection exfiltration{END}")
        self.reset()
        r = self.call("POST", "/agent/run", "avery", {"task": S["s4_injection"]["input"]}).json()
        flagged = any((s.get("result") or {}).get("injection", {}).get("flagged") for s in r["steps"])
        self.check(flagged, "wiki page flagged as prompt injection; session tainted")
        render = next((s for s in r["steps"] if s.get("tool") == "render_image"), None)
        self.check(
            render is not None and render["guard"]["verdict"] == "block", "exfiltration via image URL blocked"
        )
        egress = self.call("GET", "/demo/evidence", "avery").json()["sandbox"]["egress"]
        self.check(not [e for e in egress if e["mode"] == "protected"], "nothing left the gateway")
        print(f"  {DIM}{r['final_answer'][:160]}...{END}")

    def s5(self) -> None:
        print(f"\n{BOLD}5. Legitimate work still works{END}")
        body = self.call("POST", "/chat", "avery", {"message": S["s5_legit"]["input"]}).json()
        self.check(
            body["decision"]["route"] == "allow" and body["entities"] == [], "PUBLIC, allowed, no redaction"
        )
        self.check(
            body["latency_ms"]["gateway_overhead_ms"] < 300,
            f"gateway overhead {body['latency_ms']['gateway_overhead_ms']} ms (< 300 ms budget)",
        )

    def extras(self) -> None:
        print(f"\n{BOLD}Controls{END}")
        r = self.call("POST", "/chat", "personal", {"message": "hi"})
        self.check(r.status_code == 403, f"personal account rejected ({r.json()['detail']['code']})")
        bundle = self.call("GET", "/admin/policies", "sam").json()["bundle"]
        bundle["base"]["entities"]["CREDIT_CARD"]["action"] = "allow"
        r = self.call(
            "PUT", "/admin/policies", "sam", {"bundle": bundle, "note": "demo: try to weaken cards"}
        )
        n = len(r.json()["detail"]["report"]["protection_regressions"]) if r.status_code == 409 else 0
        self.check(
            r.status_code == 409, f"weakening the card rule refused by the regression gate ({n} regressions)"
        )
        v = self.call("GET", "/audit/verify", "sam").json()
        self.check(v["ok"], f"audit hash chain intact ({v.get('checked')} events)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8080")
    args = ap.parse_args()
    d = Demo(args.base_url)
    health = d.http.get("/healthz").json()
    print(
        f"{BOLD}Aegis demo{END} {DIM}{args.base_url} · db={health['database']} vault={health['vault_backend']} "
        f"ner={health['ner_backend']} policy={health['policy_version']}{END}"
    )
    for step in (d.s1, d.s2, d.s3, d.s4, d.s5, d.extras):
        step()
    print(
        f"\n{GREEN + 'ALL CHECKS PASSED' if not d.failures else RED + f'{d.failures} CHECK(S) FAILED'}{END}"
    )
    return 1 if d.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
