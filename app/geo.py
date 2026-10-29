"""Adaptive geographic resolution.

Rule: start at the neighbourhood. If Qloo returns too little evidence, widen the circle,
and finally fall back to the whole city. Every result keeps the label of the resolution it
was *actually* obtained at -- city-level evidence is never relabelled as neighbourhood-level.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Area

LEVEL_FACTOR = {"neighborhood": 1.0, "widened": 0.7, "city": 0.3}


@dataclass(frozen=True)
class GeoSpec:
    kind: str                 # 'point' | 'query'
    level: str                # 'neighborhood' | 'widened' | 'city'
    label: str
    lat: float | None = None
    lon: float | None = None
    radius_m: int | None = None
    query: str | None = None

    def describe(self) -> str:
        if self.kind == "point":
            return f"{self.level} ({self.radius_m / 1000:g} km circle)"
        return f"{self.level} ('{self.query}')"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def resolution_chain(area: Area, city: str, max_radius: int = 8000) -> list[GeoSpec]:
    radii: list[int] = []
    for mult in (1, 2, 4):
        rr = min(area.radius_m * mult, max_radius)
        if rr not in radii:
            radii.append(rr)
    chain = [
        GeoSpec("point", "neighborhood" if i == 0 else "widened", area.name,
                lat=area.lat, lon=area.lon, radius_m=rr)
        for i, rr in enumerate(radii)
    ]
    chain.append(GeoSpec("query", "city", area.name, query=city))
    return chain


def overlap_warnings(areas: list[Area]) -> list[str]:
    out = []
    for i in range(len(areas)):
        for j in range(i + 1, len(areas)):
            a, b = areas[i], areas[j]
            d = haversine_m(a.lat, a.lon, b.lat, b.lon)
            if d < a.radius_m + b.radius_m:
                out.append(
                    f"{a.name} and {b.name} are {d / 1000:.1f} km apart but their search circles "
                    f"({a.radius_m / 1000:g}+{b.radius_m / 1000:g} km) overlap, so they may share "
                    f"places and look more alike than they are. Shrink the radii to compare them fairly."
                )
    return out
