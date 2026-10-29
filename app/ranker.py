"""Evidence-aware ranking with a statistical tie test and a sensitivity check.

Qloo's raw place affinity LEVEL is nearly flat across areas, and generic mainstream seeds score higher than the
brand's seeds. So every place is scored twice (brand seeds, generic control seeds) and we use the PAIRED difference:

  lift(area) = mean over places of (brand affinity - generic affinity),  standard error = sd / sqrt(n)

Comparing places with themselves removes each place's general popularity. Two areas TIE when their lifts differ by
less than 2 combined standard errors (fallback: adjusted scores within 0.03 if no standard error is available).

cultural  = clamp(0.5 + lift / 0.2)      (assumption: a +/-0.1 lift spans the 0..1 scale)
composite = sum(weight_i * dim_i) over cultural + any USER-SUPPLIED operational dims
adjusted  = composite * ((1 - s) + s * evidence_quality),  s = 0.4 by default
"""
from __future__ import annotations

import math
import random

BASE_CULTURAL_WEIGHT = 0.6
EVIDENCE_PENALTY = 0.4
TIE = 0.03


def _cultural(a: dict) -> float | None:
    if a.get("lift") is None:
        return None
    return max(0.0, min(1.0, 0.5 + a["lift"] / 0.2))


def _is_tie(lead: dict, other: dict, scores: dict) -> bool:
    if lead.get("lift_se") is not None and other.get("lift_se") is not None:
        return abs(lead["lift"] - other["lift"]) <= 2 * math.hypot(lead["lift_se"], other["lift_se"])
    return scores[lead["name"]]["adjusted"] - scores[other["name"]]["adjusted"] < TIE


def _adjusted(dims: dict[str, float], weights: dict[str, float], eq: float, s: float) -> float:
    comp = sum(weights[k] * dims[k] for k in weights)
    return comp * ((1 - s) + s * eq)


def rank_areas(areas: list[dict], operational: dict[str, dict[str, float]],
               draws: int = 500, seed: int = 7) -> dict:
    notes: list[str] = []
    scorable = [a for a in areas if _cultural(a) is not None]
    if len(scorable) < len(areas):
        notes.append("Some areas could not be scored because fewer than 2 places could be compared against generic taste.")
    op_dims: list[str] = []
    if operational:
        shared = None
        for a in scorable:
            keys = set(operational.get(a["name"], {}))
            shared = keys if shared is None else shared & keys
        op_dims = sorted(shared or [])
        dropped = {k for v in operational.values() for k in v} - set(op_dims)
        if dropped:
            notes.append(f"Operational dimension(s) {sorted(dropped)} ignored: not supplied for every area.")
    if not op_dims:
        notes.append("No operational data supplied (rent, footfall, access): ranking reflects cultural "
                     "evidence only and says nothing about profitability.")

    weights = {"cultural": 1.0} if not op_dims else {
        "cultural": BASE_CULTURAL_WEIGHT,
        **{d: (1 - BASE_CULTURAL_WEIGHT) / len(op_dims) for d in op_dims}}

    scores: dict[str, dict] = {}
    for a in scorable:
        dims = {"cultural": _cultural(a), **{d: operational[a["name"]][d] for d in op_dims}}
        scores[a["name"]] = {
            "dims": dims,
            "adjusted": round(_adjusted(dims, weights, a["evidence_quality"], EVIDENCE_PENALTY), 4),
        }

    comparable = [a["name"] for a in scorable if a.get("comparable", True)]
    order = sorted(comparable, key=lambda n: -scores[n]["adjusted"])
    excluded = [a["name"] for a in scorable if not a.get("comparable", True)]
    if excluded:
        notes.append(f"{excluded} fell back to city-level evidence: identical for every such area, so "
                     f"they are not ranked.")

    by_name = {a["name"]: a for a in scorable}
    ranks: dict[str, int] = {}
    tied: set[str] = set()
    leader = None
    for i, n in enumerate(order):
        if leader is not None and _is_tie(by_name[leader], by_name[n], scores):
            ranks[n] = ranks[leader]
            tied.update((n, leader))
        else:
            ranks[n], leader = i + 1, n
    if tied:
        notes.append(f"{sorted(tied)} differ by less than the sampling noise (2 standard errors): treat as a "
                     f"tie, not an order.")

    stability: dict[str, float] = {}
    if len(order) >= 2:
        rng = random.Random(seed)
        wins = {n: 0 for n in order}
        for _ in range(draws):
            if op_dims:
                raw = {k: rng.gammavariate(max(0.2, w * 20), 1) for k, w in weights.items()}
                tot = sum(raw.values())
                w = {k: v / tot for k, v in raw.items()}
            else:
                w = weights
            s = rng.uniform(0.0, 0.8)
            best = max(order, key=lambda n: _adjusted(scores[n]["dims"], w, by_name[n]["evidence_quality"], s))
            wins[best] += 1
        stability = {n: round(c / draws, 3) for n, c in wins.items()}
        spread = (max(scores[n]["dims"]["cultural"] for n in order) -
                  min(scores[n]["dims"]["cultural"] for n in order))
        if spread < 0.03:
            notes.append("Cultural scores differ by less than 0.03 across areas: Qloo evidence barely "
                         "separates them. Treat the order as a tie and compare the places and tags instead.")
        elif max(stability.values()) < 0.6:
            notes.append(f"Fragile ranking: no area wins more than {max(stability.values()):.0%} of {draws} re-weightings.")
    return {"order": order, "ranks": ranks, "tied": sorted(tied), "excluded": excluded, "scores": scores,
            "weights": weights, "evidence_penalty": EVIDENCE_PENALTY, "stability": stability, "notes": notes}