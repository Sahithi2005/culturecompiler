"""Input model for CultureCompiler: a validated 'expansion brief'. Standard library only."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class BriefError(ValueError):
    """The user's brief is invalid (message is safe to show in the UI)."""


@dataclass
class Seed:
    name: str
    type: str = "brand"  # brand | movie | artist | person | book | podcast | tv_show ...


@dataclass
class Area:
    name: str
    lat: float
    lon: float
    radius_m: int = 1000


# Control seeds = deliberately generic, mainstream taste. They answer the question
# "would this area look culturally close to ANY brand, or specifically to ours?"
DEFAULT_CONTROL = [
    Seed("Coca-Cola", "brand"),
    Seed("Netflix", "brand"),
    Seed("Spotify", "brand"),
]


@dataclass
class Brief:
    brand: str
    home_market: str
    core_identity: list[str]
    seeds: list[Seed]
    target_city: str
    areas: list[Area]
    control_seeds: list[Seed] = field(default_factory=lambda: list(DEFAULT_CONTROL))
    place_categories: list[str] = field(default_factory=list)  # optional, e.g. ['cafe']
    min_results: int = 8   # fewer scored places than this => widen the search area
    top_k: int = 10        # how many top places define an area's "fit"
    # Optional user-supplied operational scores in [0,1] per area, e.g.
    # {"Madhapur": {"rent_affordability": 0.4, "footfall": 0.8}}. Never invented by us.
    operational: dict[str, dict[str, float]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Any) -> "Brief":
        if not isinstance(d, dict):
            raise BriefError("Brief must be a JSON object.")

        def s(key: str, maxlen: int = 120) -> str:
            v = d.get(key)
            if not isinstance(v, str) or not v.strip():
                raise BriefError(f"'{key}' is required.")
            return v.strip()[:maxlen]

        def seeds(key: str, lo: int, hi: int, required: bool) -> list[Seed]:
            raw = d.get(key)
            if raw is None and not required:
                return []
            if not isinstance(raw, list) or not (lo <= len(raw) <= hi):
                raise BriefError(f"'{key}' needs between {lo} and {hi} entries.")
            out = []
            for item in raw:
                if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                    raise BriefError(f"Each entry in '{key}' needs a 'name'.")
                t = str(item.get("type", "brand")).strip() or "brand"
                if len(t) > 40 or any(c in t for c in " \t\n&=?#"):
                    raise BriefError(f"Invalid type '{t[:20]}' in '{key}'.")
                out.append(Seed(str(item["name"]).strip()[:80], t))
            return out

        core = d.get("core_identity")
        if not isinstance(core, list) or not core or not all(isinstance(c, str) and c.strip() for c in core):
            raise BriefError("'core_identity' must be a non-empty list of short phrases.")

        areas_raw = d.get("areas")
        if not isinstance(areas_raw, list) or not (1 <= len(areas_raw) <= 6):
            raise BriefError("'areas' needs between 1 and 6 entries.")
        areas = []
        for a in areas_raw:
            try:
                area = Area(str(a["name"]).strip()[:60], float(a["lat"]), float(a["lon"]),
                            int(a.get("radius_m", 1000)))
            except (KeyError, TypeError, ValueError):
                raise BriefError("Each area needs name, lat, lon (and optional radius_m).")
            if not area.name:
                raise BriefError("Area name cannot be empty.")
            if not (-90 <= area.lat <= 90 and -180 <= area.lon <= 180):
                raise BriefError(f"Area '{area.name}' has out-of-range coordinates.")
            if not (300 <= area.radius_m <= 8000):
                raise BriefError(f"Area '{area.name}': radius_m must be 300..8000.")
            areas.append(area)
        if len({a.name.lower() for a in areas}) != len(areas):
            raise BriefError("Area names must be unique.")

        ops: dict[str, dict[str, float]] = {}
        for an, dims in (d.get("operational") or {}).items():
            if not isinstance(dims, dict):
                raise BriefError("'operational' must map area -> {dimension: 0..1}.")
            for k, v in dims.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    raise BriefError(f"operational[{an}][{k}] must be a number in 0..1.")
                if not 0 <= fv <= 1:
                    raise BriefError(f"operational[{an}][{k}] must be within 0..1.")
                ops.setdefault(str(an), {})[str(k)] = fv

        brief = cls(
            brand=s("brand"), home_market=s("home_market"),
            core_identity=[c.strip()[:60] for c in core][:8],
            seeds=seeds("seeds", 2, 8, True), target_city=s("target_city"), areas=areas,
            control_seeds=seeds("control_seeds", 2, 6, False) or list(DEFAULT_CONTROL),
            place_categories=[str(c).strip()[:40] for c in (d.get("place_categories") or []) if str(c).strip()][:3],
            min_results=int(d.get("min_results", 8)), top_k=int(d.get("top_k", 10)), operational=ops,
        )
        if not (3 <= brief.min_results <= 20 and 3 <= brief.top_k <= 20):
            raise BriefError("min_results and top_k must be within 3..20.")
        return brief


def example_brief() -> dict:
    """The running example from the pitch: a Tokyo café considering Hyderabad."""
    return {
        "brand": "Hikari",
        "home_market": "Tokyo, Japan",
        "core_identity": ["matcha", "specialty coffee", "calm minimalist spaces"],
        "seeds": [
            {"name": "Muji", "type": "brand"},
            {"name": "Blue Bottle Coffee", "type": "brand"},
            {"name": "Spirited Away", "type": "movie"},
            {"name": "Haruki Murakami", "type": "person"},
        ],
        "target_city": "Hyderabad",
        "areas": [
            {"name": "Gachibowli", "lat": 17.4401, "lon": 78.3489, "radius_m": 1000},
            {"name": "Madhapur", "lat": 17.4486, "lon": 78.3908, "radius_m": 1000},
            {"name": "Jubilee Hills", "lat": 17.4326, "lon": 78.4071, "radius_m": 1000},
        ],
        "place_categories": ["cafe"],
        "min_results": 5,
        "operational": {},
    }
