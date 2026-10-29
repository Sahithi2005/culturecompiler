"""Feasibility probe v2. Run with your real key:

    PowerShell:  $env:QLOO_API_KEY="..." ; python scripts/probe_qloo.py
    Mac/Linux:   QLOO_API_KEY=... python scripts/probe_qloo.py

It prints SUMMARY STATISTICS only (counts, ranges, overlaps, a few names), no full responses and never your key.
Per Qloo's hackathon rules do not commit raw Qloo response data to a public repository.

Questions answered:
  1. Do seeds resolve?
  2. Per area at the default 1 km radius: how many scored places, what affinity spread, do tags exist?
  3. Does brand-taste differ from generic-taste inside the same circle (Jaccard of the two top lists)?
  4. Which tags over-index for the brand versus generic taste?
  5. Is the city location parameter really honoured? (Hyderabad vs Tokyo vs no location; identical = ignored)
  6. Does take=50 work?
  7. Which tag types appear on places? 8. Can places be restricted to cafes via /v2/tags + filter.tags?
"""
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.geo import GeoSpec  # noqa: E402
from app.models import DEFAULT_CONTROL, Brief, example_brief  # noqa: E402
from app.qloo import LIVE_BASE, QlooClient, QlooError  # noqa: E402


def jac(a, b):
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def resolve(client, seeds):
    ids = []
    for s in seeds:
        ents, _ = client.search(s.name, f"urn:entity:{s.type}", take=5)
        same = [e for e in ents if ents and e.name.lower() == ents[0].name.lower()]
        pick = max(same, key=lambda e: e.popularity or 0) if same else None
        print(f"  {s.name!r:26} candidates={len(ents)} same-name={len(same)} -> {pick.name if pick else 'NOT FOUND'}")
        if pick:
            ids.append(pick.id)
    return ids


def places(client, ids, geo, take):
    try:
        ents, _ = client.insights("urn:entity:place", ids, geo=geo, take=take)
        return [e for e in ents if e.affinity is not None]
    except QlooError as e:
        print("    ERROR", e)
        return []


def main():
    key = os.environ.get("QLOO_API_KEY", "")
    if not key:
        sys.exit("Set QLOO_API_KEY first (hackathon key; base URL %s)." % LIVE_BASE)
    client = QlooClient(key, os.environ.get("QLOO_BASE_URL", LIVE_BASE))
    brief = Brief.from_dict(example_brief())

    print("== 1. Seeds ==")
    brand = resolve(client, brief.seeds)
    print(" control:")
    control = resolve(client, DEFAULT_CONTROL)
    if len(brand) < 2:
        sys.exit("Fewer than 2 brand seeds resolved.")

    print("\n== 2-4. Per area at r=1000 (brand taste vs generic taste) ==")
    for a in brief.areas:
        g = GeoSpec("point", "neighborhood", a.name, lat=a.lat, lon=a.lon, radius_m=a.radius_m)
        b, c = places(client, brand, g, 20), places(client, control, g, 20)
        ba, ca = [e.affinity for e in b], [e.affinity for e in c]
        print(f"  {a.name}: brand n={len(b)} aff min/med/max="
              f"{min(ba):.2f}/{statistics.median(ba):.2f}/{max(ba):.2f}" if ba else f"  {a.name}: no brand results",
              end="")
        print(f" | control n={len(c)} aff min/med/max="
              f"{min(ca):.2f}/{statistics.median(ca):.2f}/{max(ca):.2f}" if ca else " | no control results")
        print(f"     brand-vs-control Jaccard={jac({e.id for e in b}, {e.id for e in c}):.2f}"
              f"  tags present on {sum(1 for e in b if e.tags)}/{len(b)} brand places")
        bt = Counter(t["name"] for e in b for t in {t["name"]: t for t in e.tags}.values())
        ct = Counter(t["name"] for e in c for t in {t["name"]: t for t in e.tags}.values())
        over = sorted(bt, key=lambda k: -(bt[k] / max(1, len(b)) - ct[k] / max(1, len(c))))[:5]
        print("     top over-indexing tags:", [(k, bt[k], ct[k]) for k in over])
        print("     sample places:", [e.name for e in b[:4]])

    print("\n== 5. Is city location honoured? (brands for Hyderabad vs Tokyo vs none) ==")
    sets = {}
    for label, q in (("Hyderabad", "Hyderabad"), ("Tokyo", "Tokyo"), ("no location", None)):
        geo = GeoSpec("query", "city", label, query=q) if q else None
        try:
            ents, _ = client.insights("urn:entity:brand", brand, geo=geo, take=20)
        except QlooError as e:
            print(f"  {label}: ERROR {e}")
            continue
        sets[label] = {e.id for e in ents}
        print(f"  {label:12} n={len(ents)} e.g. {[e.name for e in ents[:4]]}")
    if len(sets) == 3:
        print(f"  Jaccard Hyderabad~Tokyo={jac(sets['Hyderabad'], sets['Tokyo']):.2f}  "
              f"Hyderabad~none={jac(sets['Hyderabad'], sets['no location']):.2f}  "
              "(1.00 means the location parameter is being ignored)")

    print("\n== 7. Tag types seen on brand-aligned places (decides which tags are useful) ==")
    g = GeoSpec("point", "neighborhood", "x", lat=17.4486, lon=78.3908, radius_m=1000)
    sample = places(client, brand, g, 20)
    types = Counter((t.get("type") or "?") for e in sample for t in e.tags)
    print("  tag type counts:", types.most_common(8))
    print("  example tags with types:", [(t["name"], (t.get("type") or "?")[-40:]) for t in sample[0].tags[:6]] if sample else [])

    print("\n== 8. Place categories via /v2/tags, then a category-filtered query near Madhapur ==")
    cat_ids = []
    for q in ("cafe", "coffee", "bakery", "dessert"):
        try:
            tags, _ = client.tags(q, take=5)
        except QlooError as e:
            print(f"  {q}: ERROR {e}")
            continue
        print(f"  {q!r}: {[(t['name'], t['id'][-45:]) for t in tags[:4]]}")
        pick = next((t for t in tags if ':place' in (t['id'] + t['type']).lower()), None)
        if q == "cafe" and pick:
            cat_ids = [pick["id"]]
    if cat_ids:
        try:
            ents, _ = client.insights("urn:entity:place", brand, geo=g, take=20, tag_ids=cat_ids)
            sc = [e for e in ents if e.affinity is not None]
            print(f"  filtered by {cat_ids[0][-45:]}: n={len(sc)}  sample={[e.name for e in sc[:6]]}")
            print(f"  overlap with unfiltered list: {jac({e.id for e in sc}, {e.id for e in sample}):.2f}")
        except QlooError as e:
            print("  filtered query ERROR", e)
    else:
        print("  no place-type tag found for 'cafe'; paste this section to Claude")

    print("\n== 6. take=50 ==")
    g = GeoSpec("point", "neighborhood", "x", lat=17.4486, lon=78.3908, radius_m=1000)
    print("  results with take=50 near Madhapur:", len(places(client, brand, g, 50)))
    print("\nDone. Paste everything above into the chat (it contains no key).")


if __name__ == "__main__":
    main()
