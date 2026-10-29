"""Qloo client (live) -- GET-only, header auth, strict per-type parameter allowlist.

Endpoints and parameter names below come from the public hackathon projects that use the
same API (base https://hackathon.api.qloo.com, header X-Api-Key, /search, /v2/insights).
They are NOT yet verified against *your* key: run scripts/probe_qloo.py first (Day-1 test).
Qloo silently ignores unknown parameters, so we refuse to send any that are not allowlisted.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from .geo import GeoSpec

LIVE_BASE = "https://hackathon.api.qloo.com"

_COMMON = {"filter.type", "signal.interests.entities", "filter.exclude.entities",
           "feature.explainability", "take"}
ALLOWED_PARAMS = {
    "urn:entity:place": _COMMON | {"filter.location", "filter.location.radius",
                                   "filter.location.query", "filter.tags", "operator.filter.tags"},
    "other": _COMMON | {"signal.location.query"},
}


class QlooError(RuntimeError):
    pass


@dataclass
class QEntity:
    id: str
    name: str
    type: str
    affinity: float | None = None
    popularity: float | None = None
    tags: list[dict] = field(default_factory=list)
    explain: dict | None = None


def _norm_aff(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v > 1:  # tolerate a 0..100 scale
        v /= 100.0
    return max(0.0, min(1.0, v))


def parse_entities(payload: dict) -> list[QEntity]:
    res = payload.get("results", {}) if isinstance(payload, dict) else {}
    items = res.get("entities", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        eid = it.get("entity_id") or it.get("id")
        if not eid:
            continue
        q = it.get("query") or {}
        tags = [{"id": t.get("id") or t.get("tag_id") or t.get("name"), "name": t.get("name"),
                 "type": t.get("type")}
                for t in (it.get("tags") or []) if isinstance(t, dict) and t.get("name")]
        out.append(QEntity(str(eid), str(it.get("name", eid)), str(it.get("type") or it.get("subtype") or ""),
                           _norm_aff(q.get("affinity")), _norm_aff(it.get("popularity")), tags,
                           q.get("explainability")))
    return out


def parse_search(payload: dict) -> list[QEntity]:
    res = payload.get("results", []) if isinstance(payload, dict) else []
    if isinstance(res, dict):
        res = res.get("entities", [])
    out = []
    for it in res:
        if not isinstance(it, dict):
            continue
        eid = it.get("entity_id") or it.get("id")
        if not eid:
            continue
        types = it.get("types") or []
        out.append(QEntity(str(eid), str(it.get("name", eid)),
                           str(types[0] if types else it.get("type", "")), None,
                           _norm_aff(it.get("popularity")), [], None))
    return out


def parse_tags(payload: dict) -> list[dict]:
    res = payload.get("results", {}) if isinstance(payload, dict) else {}
    items = res.get("tags", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
    out = []
    for it in items:
        if isinstance(it, dict) and (it.get("id") or it.get("tag_id")) and it.get("name"):
            out.append({"id": str(it.get("id") or it.get("tag_id")), "name": str(it["name"]),
                        "type": str(it.get("type") or "")})
    return out


def build_insight_params(filter_type: str, seed_ids: list[str], geo: GeoSpec | None,
                         take: int, exclude: list[str] | None, explain: bool,
                         tag_ids: list[str] | None = None) -> dict[str, str]:
    p: dict[str, str] = {"filter.type": filter_type, "take": str(take)}
    if seed_ids:
        p["signal.interests.entities"] = ",".join(seed_ids)
    if exclude:
        p["filter.exclude.entities"] = ",".join(exclude)
    if explain:
        p["feature.explainability"] = "true"
    is_place = filter_type == "urn:entity:place"
    if tag_ids:
        p["filter.tags"] = ",".join(tag_ids)
        if len(tag_ids) > 1:
            p["operator.filter.tags"] = "union"
    if geo is not None:
        if geo.kind == "point" and is_place:
            p["filter.location"] = f"POINT({geo.lon} {geo.lat})"
            p["filter.location.radius"] = str(geo.radius_m)
        elif geo.kind == "query" and is_place:
            p["filter.location.query"] = geo.query or ""
        elif geo.kind == "query":
            p["signal.location.query"] = geo.query or ""
        else:
            raise QlooError("Point/radius geography is only supported for places.")
    allowed = ALLOWED_PARAMS["urn:entity:place" if is_place else "other"]
    bad = set(p) - allowed
    if bad:
        raise QlooError(f"Refusing to send non-allowlisted parameters: {sorted(bad)}")
    return p


class QlooClient:
    mode = "live"

    def __init__(self, api_key: str, base_url: str = LIVE_BASE, timeout: float = 30,
                 max_retries: int = 3, opener: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise QlooError("QLOO_API_KEY is empty.")
        self._key, self._base = api_key, base_url.rstrip("/")
        self._timeout, self._retries = timeout, max_retries
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._cache: dict[tuple, dict] = {}

    def _get(self, path: str, params: dict[str, str]) -> tuple[dict, bool]:
        ckey = (path, tuple(sorted(params.items())))
        if ckey in self._cache:
            return self._cache[ckey], True
        url = f"{self._base}{path}?{urllib.parse.urlencode(params, safe=',:()')}"
        req = urllib.request.Request(url, headers={"X-Api-Key": self._key, "Accept": "application/json"})
        last = ""
        for attempt in range(self._retries):
            try:
                with self._open(req, timeout=self._timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if len(self._cache) >= 500:  # bound memory on a long-running public demo
                    self._cache.pop(next(iter(self._cache)))
                self._cache[ckey] = data
                return data, False
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    wait = e.headers.get("Retry-After") if e.headers else None
                    try:
                        delay = min(float(wait), 10) if wait else min(2 ** attempt, 8)
                    except ValueError:
                        delay = 2 ** attempt
                    last = f"HTTP {e.code}"
                    self._sleep(delay)
                    continue
                if e.code in (401, 403):
                    raise QlooError(f"Qloo rejected the key (HTTP {e.code}). Hackathon keys only work on "
                                    f"{LIVE_BASE}; check QLOO_API_KEY / QLOO_BASE_URL.")
                raise QlooError(f"Qloo returned HTTP {e.code} for {path}.")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last = type(e).__name__
                self._sleep(min(2 ** attempt, 8))
        raise QlooError(f"Qloo request failed after {self._retries} attempts ({last}).")

    def raw(self, path: str, params: dict[str, str]) -> dict:
        """Unparsed JSON, for diagnostics (scripts/probe_qloo.py)."""
        return self._get(path, params)[0]

    def search(self, query: str, type_urn: str, take: int = 3) -> tuple[list[QEntity], dict]:
        params = {"query": query, "types": type_urn, "take": str(take)}
        data, cached = self._get("/search", params)
        ents = parse_search(data)
        return ents, {"endpoint": "/search", "params": params, "n": len(ents), "cached": cached}

    def insights(self, filter_type: str, seed_ids: list[str], geo: GeoSpec | None = None,
                 take: int = 20, exclude: list[str] | None = None,
                 explain: bool = True, tag_ids: list[str] | None = None) -> tuple[list[QEntity], dict]:
        params = build_insight_params(filter_type, seed_ids, geo, take, exclude, explain, tag_ids)
        data, cached = self._get("/v2/insights", params)
        ents = parse_entities(data)
        return ents, {"endpoint": "/v2/insights", "params": params, "n": len(ents), "cached": cached}

    def tags(self, query: str, take: int = 5) -> tuple[list[dict], dict]:
        params = {"filter.query": query, "take": str(take)}
        data, cached = self._get("/v2/tags", params)
        out = parse_tags(data)
        return out, {"endpoint": "/v2/tags", "params": params, "n": len(out), "cached": cached}
