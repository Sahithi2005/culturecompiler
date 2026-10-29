"""Localization hypotheses, generated ONLY from evidence the run actually collected.

Each hypothesis cites evidence ids, is labelled a hypothesis (never a finding) and carries a cheap
real-world test. An optional LLM may reword the sentence, but the reworded text must pass the same
verifier or the template wording is kept.
"""
from __future__ import annotations

from .models import Brief
from .verify import check_statement

VALIDATION = "Run a 2-week pop-up or tasting and compare repeat purchases against your core items."

# Qloo tags carry a type (seen live: menu_highlight, ambience, cost_description, amenity, service_type, age_range,
# category, neighborhood_characteristic ...). Only these kinds can inspire a localization cue.
KIND_BY_TYPE = (("menu_highlight", "menu"), ("specialty_dish", "menu"), ("offerings", "menu"),
                ("dining_option", "menu"), ("genre", "menu"), ("ambience", "ambience"),
                ("cost_description", "price"))
# Name-based safety net for tags whose type is useful but whose meaning is not (e.g. a hotel cuisine tag).
NON_ACTIONABLE = ("hotel", "inn", "lodging", "star", "mastercard", "visa", "amex", "wheelchair", "accessible",
                  "parking", "cash only", "payment")
CUE = {"menu": "a menu cue", "ambience": "an ambience or space-design cue", "price": "a price-positioning cue"}
TEST = {
    "menu": "Taste 3 such items at these places, then pop-up test one menu cue against your core items.",
    "ambience": "Visit 3 of these places, note how the cue shows up in design and service, then test one at a pop-up.",
    "price": "Compare menu prices at these places with your planned price points before fixing your own.",
}


def _kind(tag: dict) -> str | None:
    ty = (tag.get("type") or "").lower()
    for key, kind in KIND_BY_TYPE:
        if f":{key}" in ty:
            return kind
    return None


def _tag_profile(places: list[dict]):
    """(name lower, kind) -> [display name, count of places carrying it, evidence ids of those places]."""
    prof: dict[tuple, list] = {}
    for p in places:
        seen = set()
        for t in p["tags"]:
            kind = _kind(t)
            if kind is None:
                continue
            key = (t["name"].strip().lower(), kind)
            if key in seen:
                continue
            seen.add(key)
            row = prof.setdefault(key, [t["name"], 0, []])
            row[1] += 1
            row[2].append(p["evidence_id"])
    return prof


def build_hypotheses(brief: Brief, areas: list[dict], evidence: dict, seed_eids: list[str],
                     city_brand_eids: list[str], area_call_ids: dict[str, str]) -> list[dict]:
    hyps: list[dict] = []
    n = 0

    def add(kind, scope, statement, ev, derived=None, test=VALIDATION):
        nonlocal n
        n += 1
        hyps.append({"id": f"H{n}", "kind": kind, "scope": scope, "statement": statement, "evidence": ev,
                     "derived_numbers": derived or [], "validation_test": test})

    if seed_eids:
        names = ", ".join(evidence[e]["name"] for e in seed_eids)
        add("preserve", "brand",
            f"Keep {', '.join(brief.core_identity)} as the anchor of the concept; the taste seeds "
            f"({names}) are the basis of every comparison here.", seed_eids,
            test="Ask 10 target customers which of these elements they would miss most if removed.")

    core_words = [c.lower() for c in brief.core_identity]
    for a in areas:
        # 1) closest cultural peers: places where the brand's taste is strongest RELATIVE to generic taste
        peers = [p for p in a.get("peers", []) if p["diff"] > 0]  # only places where brand taste scores HIGHER
        if len(peers) >= 2 and a["n_paired"] >= 3:
            listing = "; ".join(f"{p['name']} (brand {p['brand']:.2f} vs generic {p['control']:.2f})" for p in peers)
            add("peer_places", a["name"],
                f"In {a['name']}, the places where your brand's taste is strongest relative to generic taste are: "
                f"{listing}. Study them as your closest cultural peers: menu, price points and design.",
                [x for p in peers for x in (p["evidence_id"], p["control_evidence_id"])],
                test="Visit these places, photograph menus and prices, and note what a Tokyo cafe would adapt.")
        # 2) tags that over-index among brand-leaning places versus the rest of the same area's places
        lean, rest = a.get("leaning", []), a.get("other", [])
        if len(lean) >= 2 and len(rest) >= 2:
            lprof, rprof = _tag_profile(lean), _tag_profile(rest)
            ranked = sorted(lprof, key=lambda k: -(lprof[k][1] / len(lean) - rprof.get(k, [0, 0])[1] / len(rest)))
            picked, per_kind = 0, {}
            for key in ranked:
                nm, c, holders = lprof[key]
                name_l, kind = key
                if c < 2 or any(w in name_l for w in NON_ACTIONABLE) or any(name_l in w or w in name_l for w in core_words):
                    continue
                co = rprof.get(key, [0, 0])[1]
                if c / len(lean) - co / len(rest) < 0.3 or per_kind.get(kind, 0) >= 2:
                    continue
                add("taste_signal", a["name"],
                    f"In {a['name']}, {c} of the {len(lean)} places where your brand's taste is strongest "
                    f"relative to generic taste carry the '{nm}' tag, versus {co} of {len(rest)} of the other "
                    f"places; check whether this reflects {CUE[kind]} worth testing.", holders,
                    derived=[str(c), str(len(lean)), str(co), str(len(rest))], test=TEST[kind])
                per_kind[kind] = per_kind.get(kind, 0) + 1
                picked += 1
                if picked == 3:
                    break
        if a["confidence"] == "low" or not a["comparable"]:
            add("caution", a["name"],
                f"Evidence for {a['name']} is {a['resolution']['level']}-level with "
                f"{a['n_scored']} scored places; treat its position as a lead to investigate, "
                f"not a conclusion.", [area_call_ids[a["name"]]], derived=[str(a["n_scored"])],
                test="Collect local customer interviews before spending on this area.")

    chosen = [e for e in city_brand_eids[:3] if e in evidence]
    if chosen:
        listing = ", ".join(f"{evidence[e]['name']} ({evidence[e]['affinity']:.2f})" for e in chosen)
        add("channel_signal", brief.target_city,
            f"Audiences in {brief.target_city} who share your taste over-index on: {listing} (Qloo affinity, a "
            f"city-level signal). Consider them as candidate marketing channels or partners and verify each is "
            f"relevant to a cafe before approaching.", chosen,
            test="Check each brand's audience, format and price point; then run one small joint test.")
    return hyps


def maybe_rewrite(hyps: list[dict], evidence: dict, calls: dict, llm) -> tuple[list[dict], int]:
    """Let an LLM polish wording. Keeps the template text unless the rewrite passes verification."""
    if llm is None:
        return hyps, 0
    changed = 0
    out = []
    for h in hyps:
        new = h
        try:
            text = llm.rewrite(h["statement"], [evidence[e] for e in h["evidence"] if e in evidence])
        except Exception:
            text = None
        if text and 20 < len(text) < 400 and not check_statement(text, h, evidence, calls):
            new = {**h, "statement": text.strip(), "reworded_by_llm": True}
            changed += 1
        out.append(new)
    return out, changed