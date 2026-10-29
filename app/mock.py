"""Synthetic stand-in for Qloo so the app runs without a key.

Same method signatures and entity shapes as QlooClient. EVERYTHING returned here is invented
(names carry a '(synthetic)' suffix and the UI shows a banner). It exists to exercise the
pipeline, never to make claims about Hyderabad.
"""
from __future__ import annotations

import hashlib
import re

from .geo import GeoSpec
from .qloo import QEntity

PLACE_POOL = [
    "Lotus Leaf Tea Room", "Kaapi Lab", "Quiet Table Bakery", "Ember & Oat", "Sakura Courtyard Cafe",
    "Chai Atelier", "Paper Lantern Bistro", "Greenhouse Roastery", "Monsoon Dessert Bar",
    "Stone Bench Cafe", "Saffron Loft", "Lakeview Brew House", "Minimal Bowl", "The Slow Pour",
    "Cardamom Corner", "Origami Patisserie", "Banyan Cowork Cafe", "Terrace Seventeen",
    "Indigo Tea Bar", "Hush Reading Cafe",
]
CITY_BRANDS = [
    "Millet Mornings", "Handloom Home Co", "Pearl Street Sweets", "Deccan Denim", "Calm Cart Stationery",
    "Fern & Fable Books", "Urban Tiffin", "Kiln Ceramics", "Neem Naturals", "Twilight Cinemas",
]
TAG_POOL = ["specialty coffee", "dessert", "tea", "vegetarian friendly", "co-working friendly",
            "quiet", "outdoor seating", "bakery"]
DISTINCT_OFFSET = {"gachibowli": 2, "madhapur": 7, "jubilee-hills": 3}
TAG_TYPE = ["menu_highlight", "menu_highlight", "menu_highlight", "offerings", "ambience", "ambience",
            "ambience", "menu_highlight"]
BRANDLIKE = {"muji", "blue-bottle-coffee", "spirited-away", "haruki-murakami"}
# area slug -> (base affinity, extra affinity for brand-like seeds, density multiplier)
AREA_PROFILE = {"gachibowli": (0.50, 0.08, 1.0), "madhapur": (0.52, 0.14, 1.2),
                "jubilee-hills": (0.54, 0.05, 0.7)}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


class MockQloo:
    mode = "mock"

    def search(self, query: str, type_urn: str, take: int = 3):
        e = QEntity(f"mock-{type_urn.split(':')[-1]}-{_slug(query)}", query, type_urn)
        return [e], {"endpoint": "/search", "params": {"query": query, "types": type_urn, "take": str(take)},
                     "n": 1, "cached": False, "synthetic": True}

    def insights(self, filter_type: str, seed_ids: list[str], geo: GeoSpec | None = None,
                 take: int = 20, exclude: list[str] | None = None, explain: bool = True,
                 tag_ids: list[str] | None = None):
        area = _slug(geo.label) if geo else "global"
        sig = ",".join(sorted(seed_ids))
        share = sum(1 for s in seed_ids if any(s.endswith(b) for b in BRANDLIKE)) / max(1, len(seed_ids))
        if filter_type == "urn:entity:place":
            base, bonus, density = AREA_PROFILE.get(area, (0.5, 0.04 + (_h(area) % 10) / 100, 1.0))
            if geo is not None and geo.kind == "point":
                n = int(density * geo.radius_m / 100)
            else:
                base, bonus, n = 0.5, 0.06, 20
                area = "city"
            names = PLACE_POOL
            rot = _h(area) % len(PLACE_POOL)
            if share >= 0.5:  # brand-like taste surfaces partly different venues than generic taste
                rot = (rot + DISTINCT_OFFSET.get(area, 7)) % len(PLACE_POOL)
            ents = []
            for i in range(min(n, len(PLACE_POOL), take)):
                name = PLACE_POOL[(i + rot) % len(PLACE_POOL)]
                jitter = ((_h(area, name, sig) % 1000) / 1000 - 0.5) * 0.12
                aff = max(0.01, min(0.99, base + bonus * share + jitter))
                ks = {(i + rot) % 8, (i * 3 + 1) % 8, (i * 5 + 2 + rot) % 8}
                if share >= 0.5 and i % 2 == 0:  # brand-like taste favours tea/quiet/coffee places
                    ks.add([2, 5, 0][i % 3])
                tags = [{"id": f"mock-tag-{_slug(TAG_POOL[k % len(TAG_POOL)])}", "name": TAG_POOL[k % len(TAG_POOL)],
                         "type": f"urn:tag:{TAG_TYPE[k % len(TAG_TYPE)]}:qloo"} for k in sorted(ks)]
                ents.append(QEntity(f"mock-place-{area}-{_slug(name)}", f"{name} (synthetic)",
                                    filter_type, round(aff, 4), None, tags, None))
        else:
            ents = []
            for i, name in enumerate(CITY_BRANDS[:take]):
                jitter = ((_h("city", name, sig) % 1000) / 1000 - 0.5) * 0.2
                aff = max(0.01, min(0.99, 0.5 + 0.1 * share + jitter))
                ents.append(QEntity(f"mock-brand-city-{_slug(name)}", f"{name} (synthetic)",
                                    filter_type, round(aff, 4), None, [], None))
        ents.sort(key=lambda e: -(e.affinity or 0))
        return ents, {"endpoint": "/v2/insights",
                      "params": {"filter.type": filter_type, "geo": geo.describe() if geo else None,
                                 "seeds": len(seed_ids)},
                      "n": len(ents), "cached": False, "synthetic": True}

    def tags(self, query: str, take: int = 5):
        return ([{"id": f"mock-tag-{_slug(query)}", "name": query, "type": "urn:tag:category:place"}],
                {"endpoint": "/v2/tags", "params": {"filter.query": query}, "n": 1, "cached": False,
                 "synthetic": True})