"""Turns the ranking into a decision-ready recommendation without overstating what the data shows.

* One area clearly ahead (not tied)  -> status "clear".
* Several areas tied at the top      -> status "tentative": the pick is a TIE-BREAK, not a statistical win.
  Tie-break order (all numbers come from the run itself): evidence quality, then the share of places where the
  brand's taste scores higher than generic taste, then the lift point estimate.
* Nothing scorable                   -> status "none".
"""
from __future__ import annotations


def _lift_text(a: dict) -> str:
    if a.get("lift") is None:
        return "lift unavailable"
    se = f" ± {a['lift_se']:.3f}" if a.get("lift_se") is not None else ""
    return f"paired lift {a['lift']:+.3f}{se}"


def _evidence_text(a: dict) -> str:
    return (f"{a['n_paired']} places compared at {a['resolution']['description']} "
            f"(evidence confidence: {a['confidence']})")


def recommend(areas: list[dict]) -> dict:
    scored = [a for a in areas if a.get("rank") is not None]
    if not scored:
        return {"status": "none", "area": None, "tied": [], "reasons": [],
                "caveats": ["No area could be compared against generic taste (too few places, or only city-level "
                            "data). Widen the radius, change the place category, or add more taste seeds."],
                "peers": [], "runner_up": None}
    top = [a for a in scored if a["rank"] == 1]
    others = [a for a in scored if a["rank"] != 1]
    runner = max(others, key=lambda a: (a["lift"] if a.get("lift") is not None else -9), default=None)

    if len(top) == 1:
        best = top[0]
        reasons = [_lift_text(best), _evidence_text(best)]
        caveats = []
        if runner is not None:
            reasons.append(f"Ahead of {runner['name']} ({_lift_text(runner)}) by more than the sampling noise.")
        else:
            caveats.append("Only one area had enough comparable data, so this is not a head-to-head result.")
        status = "clear" if runner is not None else "tentative"
        caveats.append("This is cultural alignment only. Validate with a small pop-up before committing capital.")
    else:
        def key(a):
            return (a["evidence_quality"], a["positive_share"] if a.get("positive_share") is not None else -1,
                    a["lift"] if a.get("lift") is not None else -9)
        ranked = sorted(top, key=key, reverse=True)
        best, runner = ranked[0], ranked[1]
        names = [a["name"] for a in top]
        reasons = [f"Taste data cannot statistically separate {', '.join(names)}. {best['name']} is picked by tie-break:",
                   f"Most reliable data: {_evidence_text(best)}."]
        if best.get("positive_share") is not None:
            reasons.append(f"Brand taste scores {round(best['positive_share'] * 100)}% of its places higher than "
                           f"generic taste does.")
        reasons.append(f"Point estimate: {_lift_text(best)} (within noise of the others).")
        caveats = [f"This is a tie-break, not a statistical win. If budget allows, pilot in {best['name']} and "
                   f"{runner['name']} and compare real results.",
                   "This is cultural alignment only. Validate with a small pop-up before committing capital."]
        status = "tentative"

    peers = [p["name"] for p in best.get("peers", []) if p["diff"] > 0][:3]
    return {"status": status, "area": best["name"], "tied": [a["name"] for a in top] if len(top) > 1 else [],
            "reasons": reasons, "caveats": caveats, "peers": peers,
            "runner_up": runner["name"] if runner else None}
