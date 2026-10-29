"""The agent loop: plan -> resolve -> probe (adaptive resolution) -> control -> rank -> localize -> verify.

'Agentic' here means a tool-using loop with decisions and stopping rules (widen when evidence is thin,
drop unresolved seeds, refuse to rank incomparable areas), recorded in a visible trace.
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import mean, stdev

from .geo import GeoSpec, LEVEL_FACTOR, overlap_warnings, resolution_chain
from .localize import build_hypotheses, maybe_rewrite
from .models import Brief
from .qloo import QlooError
from .ranker import rank_areas
from .verify import verify_hypotheses

LIMITATIONS = [
    "Live probe (28 Oct 2026): Qloo's raw affinity LEVEL is nearly flat across areas and generic mainstream seeds "
    "score higher than brand seeds. So each place is scored twice (brand taste, generic taste) and areas are "
    "compared by the average paired difference ('lift'), with a standard-error test deciding ties.",
    "Restricting to a place category (for example cafe) leaves few qualifying places per 1 km circle (often 5-10), "
    "so paired-lift estimates rest on small sets (see the ± value). Without a category the list includes hotels and other "
    "venues. Either way it is a cultural proxy, not a competitor census.",
    "Qloo affinities describe cultural/taste association, not demand, willingness to pay or profit.",
    "Neighbourhood evidence comes from places near a point; it does not describe the people who live there.",
    "Competition, rent and footfall are not inferred from Qloo. Supply them or treat the ranking as cultural only.",
    "All adaptations are hypotheses to test with customers before committing capital.",
]


class AnalysisError(RuntimeError):
    pass


def _urn(t: str) -> str:
    return t if t.startswith("urn:") else f"urn:entity:{t}"


def _parallel(fns):
    """Warm the client's cache with concurrent requests. Errors are ignored here: the sequential pass
    that follows hits the cache, or repeats the call and handles the error properly."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        for f in [ex.submit(fn) for fn in fns]:
            try:
                f.result()
            except Exception:
                pass


class _Run:
    def __init__(self):
        self.trace, self.warnings = [], []
        self.calls: dict[str, dict] = {}
        self.evidence: dict[str, dict] = {}

    def step(self, name: str, detail: str):
        self.trace.append({"step": name, "detail": detail})

    def log_call(self, call: dict, purpose: str) -> str:
        cid = f"C{len(self.calls) + 1}"
        self.calls[cid] = {**call, "purpose": purpose}
        return cid

    def add_evidence(self, cid: str, e, role: str) -> str:
        eid = f"{cid}:{e.id}"
        self.evidence[eid] = {"id": eid, "call": cid, "role": role, "entity_id": e.id, "name": e.name,
                              "type": e.type, "affinity": e.affinity, "tags": e.tags}
        return eid


def _resolve(run: _Run, client, seeds, role: str):
    found, eids = [], []
    for s in seeds:
        ents, call = client.search(s.name, _urn(s.type), take=5)
        cid = run.log_call(call, f"resolve {role} seed '{s.name}'")
        if not ents:
            run.warnings.append(f"{role} seed '{s.name}' ({s.type}) was not found in Qloo and was dropped.")
            continue
        top = ents[0]
        same = [e for e in ents if e.name.strip().lower() == top.name.strip().lower()]
        if len(same) > 1:
            top = max(same, key=lambda e: e.popularity or 0)
            run.warnings.append(f"'{s.name}' matches {len(same)} Qloo entities with the same name; using the "
                                f"most popular one. Check it is the one you meant.")
        found.append(top)
        eids.append(run.add_evidence(cid, top, f"{role}_seed"))
    run.step("resolve", f"{role} seeds: {len(found)}/{len(seeds)} resolved to Qloo entities")
    return found, eids


def _resolve_categories(run: _Run, client, cats: list[str]) -> list[str]:
    ids = []
    for c in cats:
        try:
            tags, call = client.tags(c, take=5)
        except QlooError as e:
            run.warnings.append(f"Could not look up place category '{c}': {e}")
            continue
        run.log_call(call, f"resolve place category '{c}'")
        pick = None
        for prefix in ("urn:tag:genre:place:restaurant:", "urn:tag:category:place:", "urn:tag:genre:place:"):
            pick = next((t for t in tags if t["id"].startswith(prefix)), None)
            if pick:
                break
        pick = pick or next((t for t in tags if ":place" in (t["id"] + t["type"]).lower()), None)
        if pick:
            ids.append(pick["id"])
            run.step("category", f"'{c}' -> {pick['name']} ({pick['id']})")
        else:
            run.warnings.append(f"No place tag found for category '{c}'; searching all place types instead.")
    return ids


def _scored(ents):
    return sorted([e for e in ents if e.affinity is not None], key=lambda e: -e.affinity)


def _r(x):
    return None if x is None else round(x, 4)


def _paired_stats(diffs):
    """Mean and standard error of per-place (brand affinity - generic affinity)."""
    if len(diffs) < 2:
        return None, None
    return mean(diffs), stdev(diffs) / math.sqrt(len(diffs))


def _analyze_area(run: _Run, client, brief: Brief, area, brand_ids, control_ids, tag_ids):
    chain = resolution_chain(area, brief.target_city)
    chosen = None
    for i, geo in enumerate(chain):
        ents, call = client.insights("urn:entity:place", brand_ids, geo=geo, take=20, tag_ids=tag_ids or None)
        cid = run.log_call(call, f"{area.name}: places aligned with brand taste, {geo.describe()}")
        sc = _scored(ents)
        last = i == len(chain) - 1
        if len(sc) >= brief.min_results or last:
            chosen = (geo, sc, cid)
            run.step("probe", f"{area.name}: {len(sc)} scored places at {geo.describe()}"
                              + ("" if len(sc) >= brief.min_results else " (accepting: nothing wider left)"))
            break
        run.step("widen", f"{area.name}: only {len(sc)} scored places at {geo.describe()} "
                          f"(< {brief.min_results}); widening")
    geo, sc, cid = chosen
    ev_brand = {e.id: run.add_evidence(cid, e, "place") for e in sc}
    top_places = [{"evidence_id": ev_brand[e.id], "name": e.name, "affinity": e.affinity, "tags": e.tags}
                  for e in sc[:brief.top_k]]
    fit = mean(e.affinity for e in sc) if sc else None

    baseline, overlap, paired = None, None, []
    if control_ids and sc:
        cents, ccall = client.insights("urn:entity:place", control_ids, geo=geo, take=20, tag_ids=tag_ids or None)
        ccid = run.log_call(ccall, f"{area.name}: CONTROL (generic taste), {geo.describe()}")
        call_all = _scored(cents)
        cmap = {e.id: e for e in call_all}
        baseline = mean(e.affinity for e in call_all) if call_all else None
        bset, cset = set(ev_brand), set(cmap)
        overlap = len(bset & cset) / len(bset | cset) if (bset | cset) else None
        # Paired comparison: the SAME places scored under brand taste and under generic taste. Removes each
        # place's general popularity, so what is left is how much more the brand's taste likes it.
        for e in sc:
            c = cmap.get(e.id)
            if c is not None:
                paired.append({"name": e.name, "evidence_id": ev_brand[e.id],
                               "control_evidence_id": run.add_evidence(ccid, c, "control_place"),
                               "brand": e.affinity, "control": c.affinity, "diff": e.affinity - c.affinity,
                               "tags": e.tags})
    lift, lift_se = _paired_stats([p["diff"] for p in paired])
    paired.sort(key=lambda p: -p["diff"])
    half = (len(paired) + 1) // 2
    leaning, other = (paired[:half], paired[half:]) if len(paired) >= 4 else ([], [])

    capped = len(sc) >= 20
    if capped:
        run.step("cap", f"{area.name}: hit the 20-place cap, so only the top results are compared (narrow the "
                        f"radius or add a category for a complete set)")
    n_cmp = len(paired) if control_ids else len(sc)
    coverage = min(1.0, n_cmp / brief.top_k)
    eq = round(coverage * LEVEL_FACTOR[geo.level], 3)
    confidence = "high" if eq >= 0.9 else "medium" if eq >= 0.5 else "low"
    return {
        "name": area.name, "resolution": {"level": geo.level, "description": geo.describe(),
                                          "radius_m": geo.radius_m},
        "comparable": geo.level != "city", "n_scored": len(sc), "n_paired": len(paired), "pool_capped": capped,
        "fit": _r(fit), "baseline": _r(baseline), "lift": _r(lift), "lift_se": _r(lift_se),
        "overlap_with_generic": _r(overlap), "evidence_quality": eq, "confidence": confidence,
        "top_places": top_places, "peers": paired[:3], "leaning": leaning, "other": other, "call": cid,
    }, {e.id for e in sc[:brief.top_k]}


def analyze(brief: Brief, client, llm=None) -> dict:
    t0 = time.time()
    run = _Run()
    live = client.mode == "live"
    run.step("plan", f"Compare {len(brief.areas)} areas of {brief.target_city} for '{brief.brand}' "
                     f"(home: {brief.home_market}); data mode: {client.mode}.")
    run.warnings += overlap_warnings(brief.areas)

    if live:  # wave 1: all seed searches concurrently
        _parallel([(lambda s=s: client.search(s.name, _urn(s.type), take=5))
                   for s in brief.seeds + brief.control_seeds])
    brand_ents, seed_eids = _resolve(run, client, brief.seeds, "brand")
    if len(brand_ents) < 2:
        raise AnalysisError("Fewer than 2 brand seeds resolved in Qloo, so there is no reliable taste "
                            "profile. Try more recognisable seed names.")
    control_ents, _ = _resolve(run, client, brief.control_seeds, "control")
    if len(control_ents) < 2:
        run.warnings.append("Control seeds did not resolve; areas cannot be scored against generic taste.")
        control_ents = []
    brand_ids, control_ids = [e.id for e in brand_ents], [e.id for e in control_ents]
    tag_ids = _resolve_categories(run, client, brief.place_categories) if brief.place_categories else []

    city_geo = GeoSpec("query", "city", brief.target_city, query=brief.target_city)
    if live:  # wave 2: first-attempt probes for every area (brand + control) and the city query, concurrently
        wave = []
        for a in brief.areas:
            g0 = resolution_chain(a, brief.target_city)[0]
            wave.append(lambda g0=g0: client.insights("urn:entity:place", brand_ids, geo=g0, take=20,
                                                      tag_ids=tag_ids or None))
            if control_ids:
                wave.append(lambda g0=g0: client.insights("urn:entity:place", control_ids, geo=g0, take=20,
                                                          tag_ids=tag_ids or None))
        wave.append(lambda: client.insights("urn:entity:brand", brand_ids, geo=city_geo, take=20))
        _parallel(wave)

    areas, id_sets = [], {}
    for a in brief.areas:
        res, ids = _analyze_area(run, client, brief, a, brand_ids, control_ids, tag_ids)
        areas.append(res)
        id_sets[a.name] = ids
    names = list(id_sets)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            u = id_sets[names[i]] | id_sets[names[j]]
            if u and len(id_sets[names[i]] & id_sets[names[j]]) / len(u) > 0.8:
                run.warnings.append(f"{names[i]} and {names[j]} returned almost the same places; "
                                    f"their scores are not independent evidence.")

    city_eids = []
    try:
        cents, ccall = client.insights("urn:entity:brand", brand_ids, geo=city_geo, take=20)
        ccid = run.log_call(ccall, f"{brief.target_city}: brands aligned with brand taste (city-level)")
        city_eids = [run.add_evidence(ccid, e, "city_brand") for e in _scored(cents)[:5]]
        run.step("city_context", f"{len(city_eids)} city-level brand signals for {brief.target_city}")
    except QlooError as e:
        run.warnings.append(f"City-level brand context unavailable: {e}")

    ranking = rank_areas(areas, brief.operational)
    tied = set(ranking["tied"])
    for a in areas:
        a["score"] = ranking["scores"].get(a["name"])
        a["rank"] = ranking["ranks"].get(a["name"])
        a["tied"] = a["name"] in tied
        a["win_share"] = None if a["tied"] else ranking["stability"].get(a["name"])
    areas.sort(key=lambda a: (a["rank"] is None, a["rank"] or 0, a["name"]))
    run.step("rank", f"Order: {', '.join(ranking['order']) or 'none comparable'}"
                     + (f" (ties: {', '.join(ranking['tied'])})" if tied else ""))

    hyps = build_hypotheses(brief, areas, run.evidence, seed_eids, city_eids,
                            {a["name"]: a["call"] for a in areas})
    verified, rejected = verify_hypotheses(hyps, run.evidence, run.calls)
    reworded = 0
    if llm is not None:
        verified, reworded = maybe_rewrite(verified, run.evidence, run.calls, llm)
    run.step("verify", f"{len(verified)} hypotheses passed the evidence check, {len(rejected)} rejected"
                       + (f"; {reworded} reworded by LLM" if llm else ""))

    return {
        "brief": {"brand": brief.brand, "home_market": brief.home_market, "target_city": brief.target_city,
                  "core_identity": brief.core_identity, "place_categories": brief.place_categories},
        "mode": client.mode, "synthetic": client.mode == "mock",
        "areas": areas, "ranking": ranking, "hypotheses": verified, "rejected": rejected,
        "trace": run.trace, "warnings": run.warnings, "calls": run.calls, "evidence": run.evidence,
        "limitations": LIMITATIONS, "elapsed_s": round(time.time() - t0, 2),
    }