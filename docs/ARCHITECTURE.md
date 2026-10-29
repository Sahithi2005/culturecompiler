# CultureCompiler: Architecture and Code Walkthrough

## 1. What the project does
A brand that works in one market (for example a Tokyo matcha cafe) wants to enter another (Hyderabad). Translating the
menu is not enough; **tastes** differ. CultureCompiler uses Qloo's taste graph to answer:
1. Which candidate neighbourhoods are culturally closest to what made the brand successful?
2. How trustworthy is that answer (how much data, at what geographic resolution)?
3. What should be adapted and what kept? Each suggestion is a **hypothesis tied to evidence**.

It does not predict sales or profit. Taste affinity is not demand, rent or footfall.

## 2. System architecture
```
Browser (app/static/index.html)
   | POST /api/analyze  {brand, seeds, areas, place_categories, ...}
   v
app/server.py  validates input (models.py), rate-limits, limits concurrency, maps errors to HTTP codes
   v
app/agent.py   the agent loop
   1 plan       overlap warnings between areas                    (geo.py)
   2 resolve    seed names -> Qloo entity IDs; category -> tag ID  (client.search / client.tags)
   3 probe      per area: places near a point, widen if thin      (client.insights, geo.py)
   4 control    same places scored under generic seeds, paired    (client.insights)
   5 city       city-level brand signals                          (client.insights)
   6 rank       paired lift +/- SE, ties, stability               (ranker.py)
   7 localize   peer places + tag cues + channel signals          (localize.py)
   8 verify     reject untraceable claims                         (verify.py)
   v
client = QlooClient (qloo.py, real API)  OR  MockQloo (mock.py, synthetic data, labelled)
```
Design principle: **every number and claim in the output is traceable to an API call (`calls`) or an entity row
(`evidence`)**. The response contains `trace`, `calls`, `evidence`, `warnings` and `limitations`, so a run can be audited.

Live calls are made concurrently where independent (seed searches; first-attempt area probes plus the city query) to
warm the client cache; the same sequential logic then runs against the cache. A full live analysis takes about 12 s.

## 3. Core concepts
**Qloo taste graph.** Entities (brands, movies, places, people) linked when the same people like both. *Tags* describe
entities and carry a *type* (menu_highlight, ambience, cost_description, amenity ...). *Affinity* (0 to 1) is the strength
of association between an entity and the taste signal supplied.

**Seeds and signals.** Seeds are entities that characterise the brand's audience (Muji, Blue Bottle Coffee, Spirited
Away, Haruki Murakami), passed as `signal.interests.entities`.

**Place filters.** `filter.location=POINT(lon lat)` + `filter.location.radius` restricts places to a circle;
`filter.tags=<tag id>` restricts the venue category (for example `urn:tag:genre:place:restaurant:cafe`, found via `/v2/tags`).
For non-place types, location is a signal (`signal.location.query`), used at city level.

**Adaptive geographic resolution.** Start at the requested neighbourhood circle. If fewer than `min_results` scored places
come back, widen the radius (x2, x4, capped at 8 km), finally fall back to the whole city. Results keep the label of the
level they were actually obtained at (`neighborhood`, `widened`, `city`). City-level results are identical for every area,
so those areas are `comparable=false` and never ranked.

**Paired lift (the control experiment).** Live probes (28-29 Oct 2026) showed that Qloo's raw place affinity is nearly flat
across areas and that generic mainstream seeds score higher than brand seeds. With a cafe filter, brand and generic
queries return the same complete set of places, so set overlap carries no information either. What works is comparing each
place with itself: every place is scored under the brand seeds and under generic seeds (Coca-Cola, Netflix, Spotify), and
`lift = mean(brand affinity - generic affinity)` over the area's places, with standard error `sd / sqrt(n)`. This removes each
place's general popularity. Not validated against real store outcomes.

**Evidence quality.** `coverage = min(1, places compared / top_k)` times a resolution factor (neighbourhood 1.0,
widened 0.7, city 0.3). Confidence: high >= 0.9, medium >= 0.5, otherwise low.

**Ranking, ties, stability.** `cultural = clamp(0.5 + lift/0.2)` (assumption: +/-0.1 lift spans 0..1);
`adjusted = composite * ((1 - s) + s * evidence_quality)`, `s = 0.4`. Two areas **tie** when their lifts differ by at most
2 combined standard errors; tied areas share a rank (`1=`) and show no win share. Weights and `s` are assumptions, so they
are redrawn 500 times (seeded) to report each area's win share. Operational dimensions (rent, footfall) enter only if the
user supplies them for every area.

**Hypothesis vs finding.** "5 of 6 brand-leaning places carry tag X" is evidence. "Test an X cue" is a hypothesis.
Every hypothesis lists evidence IDs and a cheap real-world test.

**Verifier.** A hypothesis is kept only if it cites at least one evidence ID, every cited ID exists in the run's evidence or
call log, and every number in its sentence appears in cited evidence or was computed by code.

**Agentic.** A tool-using loop with decisions and stopping rules (widen when thin, drop unresolved seeds, refuse to rank
incomparable areas, abort if fewer than 2 seeds resolve), visible in `trace`. The logic is rule-based.

## 4. Code walkthrough
- **app/models.py**: `Seed`, `Area`, `Brief` and validation (2-8 seeds, 1-6 unique areas, valid coordinates, radius 300-8000 m,
  `min_results`/`top_k` 3-20, operational scores 0-1, seed types restricted so they cannot inject URL syntax).
  `DEFAULT_CONTROL` holds the generic seeds. `example_brief()` is the Hikari / Hyderabad example (category `cafe`, `min_results` 5).
- **app/geo.py**: `GeoSpec`, `resolution_chain` (radii r, 2r, 4r then city), `haversine_m`, `overlap_warnings`, `LEVEL_FACTOR`.
- **app/qloo.py**: GET-only client, key in the `X-Api-Key` header only, per-type parameter allowlist (Qloo silently ignores
  unknown parameters), defensive parsers, retries on 429/5xx with `Retry-After`, bounded in-memory cache, `search`,
  `insights` and `tags`. HTTP opener and sleep are injectable for offline tests.
- **app/mock.py**: deterministic synthetic data with the same interface; every name ends in "(synthetic)".
- **app/agent.py**: `_Run` (per-request evidence and call log), `_resolve`, `_resolve_categories`, `_analyze_area`
  (widening loop, paired comparison, evidence quality), `analyze` (orchestration, concurrent prefetch, ranking, hypotheses,
  verification) and `LIMITATIONS`.
- **app/ranker.py**: cultural score, standard-error tie test, evidence adjustment, 500-draw stability.
- **app/localize.py**: hypothesis kinds `preserve`, `peer_places` (places where brand taste beats generic taste),
  `taste_signal` (menu / ambience / price tags over-indexing among those places; amenity, service, age and neighbourhood tags
  ignored; hotel / payment / accessibility names denied), `caution` and `channel_signal` (city-level brands to verify).
  Includes an optional wording hook that is disabled by default.
- **app/verify.py**: the claim verifier.
- **app/server.py**: standard-library HTTP server; routes `GET /`, `/api/health`, `/api/example`, `POST /api/analyze`;
  100 KB body cap, 2 concurrent analyses, 10 analyses per IP per 10 minutes, errors mapped to 400/413/422/429/502/500
  without leaking internals; request URLs not logged.
- **app/static/index.html**: single page, no build step; all API-derived text is HTML-escaped.
- **scripts/probe_qloo.py**: feasibility probe; prints summary statistics only (never the key or raw responses).
- **tests/test_core.py**: 46 tests (geo, validation, parameter allowlist, auth header, retry and cache, ranker and ties,
  verifier, tag handling, end-to-end on mock data, live-mode prefetch, rate limit, HTTP server).

## 5. Run
```
python -m app.server                       # http://localhost:8000, synthetic data without a key
python -m unittest discover -s tests -t .  # tests
QLOO_API_KEY=... python scripts/probe_qloo.py
QLOO_API_KEY=... python -m app.server      # live mode
docker build -t cc . && docker run -p 8000:8000 -e QLOO_API_KEY=... cc
```
Environment: `QLOO_API_KEY` (required for live mode), `QLOO_BASE_URL`, `CC_MOCK=1`, `PORT`.

## 6. Known limitations
1. Affinity measures taste association, not demand. Rent, competition and footfall are not inferred.
2. With a cafe filter only about 5-10 places qualify per 1 km circle, so area comparisons are often a statistical tie; the app
   says so and shows peer places and tag cues instead of an order.
3. Radii can differ between areas when one is widened (shown in the Resolution column).
4. Place tags are whatever Qloo attaches; only menu, ambience and price types feed ideas.
5. City-level brand signals are generic consumer or media brands; they are channel leads to verify, not partners.
6. Weights (0.6 cultural, `s = 0.4`) and the lift scale (0.2) are assumptions; stability and ties show sensitivity but do not validate them.
7. No authentication or persistent storage; fine for a demo. The in-memory cache resets on restart.

## 7. Pitch lines
- "We translate cultural preferences, not languages."
- "Every claim is traceable to a Qloo call, and the verifier rejects the rest."
- "When the data cannot separate two neighbourhoods, we say so instead of faking a ranking."