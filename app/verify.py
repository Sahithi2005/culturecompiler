"""Claim verifier: a hypothesis survives only if every evidence id it cites exists in the evidence
log, and every number in its statement is traceable to cited evidence or to a code-derived count."""
from __future__ import annotations

import re

_NUM = re.compile(r"\d+(?:\.\d+)?")


def allowed_numbers(h: dict, evidence: dict, calls: dict) -> set[str]:
    nums = set(h.get("derived_numbers", []))
    for eid in h.get("evidence", []):
        ev = evidence.get(eid)
        if ev:
            if ev.get("affinity") is not None:
                nums.add(f"{ev['affinity']:.2f}")
            nums.update(_NUM.findall(ev.get("name", "")))
    return nums


def check_statement(statement: str, h: dict, evidence: dict, calls: dict) -> list[str]:
    extra = set(_NUM.findall(statement)) - allowed_numbers(h, evidence, calls)
    return [f"number(s) {sorted(extra)} not traceable to cited evidence"] if extra else []


def verify_hypotheses(hyps: list[dict], evidence: dict, calls: dict) -> tuple[list[dict], list[dict]]:
    ok, bad = [], []
    for h in hyps:
        issues = []
        cited = h.get("evidence") or []
        if not cited:
            issues.append("no evidence cited")
        for eid in cited:
            if eid not in evidence and eid not in calls:
                issues.append(f"unknown evidence id {eid}")
        issues += check_statement(h["statement"], h, evidence, calls)
        if issues:
            bad.append({**h, "status": "rejected", "issues": issues})
        else:
            ok.append({**h, "status": "hypothesis"})
    return ok, bad
