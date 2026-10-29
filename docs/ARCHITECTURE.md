# CultureCompiler: Architecture, Code Walkthrough and Concepts

## 1. What the project does

A brand that works in one market (for example a Tokyo matcha café) wants to enter another (Hyderabad).
Translating the menu is not enough; **tastes** differ. CultureCompiler uses Qloo's taste graph to answer:

1. Which candidate neighbourhoods are culturally closest to what made the brand successful?
2. How trustworthy is that answer (how much data, at what geographic resolution)?
3. What should be adapted, and what should be kept? Each suggestion is a **hypothesis tied to evidence**.

It does not predict sales or profit. Taste affinity is not demand, rent or footfall.

## 2. System architecture

```
Browser (app/static/index.html)
   | POST /api/analyze  {brand, seeds, areas, ...}
   v
app/server.py  -- validates (models.py), limits concurrency, maps errors to HTTP codes
   v
app/agent.py   -- the agent loop
   1 plan      overlap warnings between areas (geo.py)
   2 resolve   seed names -> Qloo entity IDs          (client.search)
   3 probe     per area: places near a point          (client.insights), widen if thin (geo.py)
   4 control   same area, generic seeds -> baseline   (client.insights)
   5 city      city-level brand signals               (client.insights)
   6 rank      lift, evidence quality, stability      (ranker.py)
   7 localize  hypotheses from collected evidence     (localize.py)
   8 verify    reject untraceable claims              (verify.py)
   v
client = QlooClient (qloo.py, real API)  OR  MockQloo (mock.py, synthetic data)
```

Design principle: **every number and claim in the output must be traceable to an API call** (`calls`) or an
entity row (`evidence`). The final JSON contains `trace`, `calls`, `evidence`, `warnings` and `limitations`
so a judge or user can audit the run.

## 3. Core concepts

**Qloo taste graph.** A graph where nodes (*entities*: brands, movies, places, people) are linked when the same
people like both. *Tags* describe entities (for example a cuisine). *Affinity* (0 to 1) is the strength of association
between an entity and the taste signal you supply.

**Seeds and signals.** Seeds are entities that characterise the brand's audience (Muji, Blue Bottle Coffee,
Spirited Away). Passed to Qloo as `signal.interests.entities`, they mean "rank things by closeness to these".

**Filters.** For places, `filter.location=POINT(lon lat)` with `filter.location.radius` restricts results to a
circle. For non-place types, location is a *signal* (`signal.location.query`), usable at city level.

**Adaptive geographic resolution.** Start at the requested neighbourhood circle. If fewer than `min_results`
scored places come back, widen the radius (x2, x4, capped at 8 km), and finally fall back to the whole city.
The result keeps the label of the level it was **actually** obtained at (`neighborhood`, `widened`, `city`).
City-level results are identical for every area, so such areas are marked `comparable=false` and never ranked.

**Distinct taste cluster (the control experiment, revised after live data).** Inside the same circle we query Qloo
twice: once with the brand's seeds and once with generic mainstream seeds (Coca-Cola, Netflix, Spotify). The first
design compared the two affinity *levels* ("lift"). The live probe showed that is meaningless: top-20 affinities
sit in a ~0.80-0.82 band everywhere, and the generic seeds score *higher* than the brand seeds. What does vary
is whether the brand's taste surfaces *different places* than generic taste. So `distinct = 1 - Jaccard(brand
places, generic places)`. High means a brand-specific taste cluster exists there; low means the brand's nearest
places are just the mainstream ones. This is a hypothesis-grade signal, not validated against store outcomes.

**Evidence quality.** `coverage = min(1, scored_places / top_k)` times a resolution factor
(neighbourhood 1.0, widened 0.7, city 0.3). Confidence: high >= 0.9, medium >= 0.5, otherwise low.

**Ranking, ties and stability.** `cultural = distinct`.
`adjusted = composite * ((1 - s) + s * evidence_quality)` with `s = 0.4`. Weights and `s` are assumptions, so we
re-draw them 500 times (seeded, deterministic) and report each area's win share. Areas within 0.03 of the tier leader share a rank (shown as `1=`) and show no win share, because a tiny gap is not an order. Low win share elsewhere means a fragile ranking.

**Hypothesis vs finding.** A finding is "5 of the top 10 places in Madhapur carry tag X". A hypothesis is
"test an X-led item". Only the first is evidence. Every hypothesis lists evidence IDs and a cheap real-world test.

**Verifier.** A hypothesis is kept only if it cites at least one evidence ID, every cited ID exists in the run's
evidence or call log, and every number in its sentence appears in cited evidence or was computed by code.
This also guards optional LLM rewording.

**Agentic.** A tool-using loop with decisions and stopping rules (widen when thin, drop unresolved seeds,
refuse to rank incomparable areas, abort if fewer than 2 seeds resolve), visible in `trace`. The LLM is optional
and only polishes wording.

## 4. Code walkthrough

### app/models.py
- `Seed(name, type)`, `Area(name, lat, lon, radius_m)`, `Brief`: the validated request.
- `Brief.from_dict` enforces: 2 to 8 seeds, 1 to 6 unique areas, valid coordinates, radius 300 to 8000 m,
  `min_results` and `top_k` in 3 to 20, operational scores in 0 to 1. Seed type strings are restricted so they
  cannot inject URL syntax. Raises `BriefError` with a user-safe message.
- `DEFAULT_CONTROL`: Coca-Cola, Netflix, Spotify, the generic-taste control. Replaceable per request.
- `example_brief()`: the Hikari / Hyderabad example used by the UI.
- `operational` holds optional user-supplied per-area scores (rent affordability, footfall). Never invented.

### app/geo.py
- `GeoSpec`: either a `point` (lat, lon, radius) or a `query` (city name) with a `level` label.
- `resolution_chain(area, city)`: radii [r, 2r, 4r] capped and de-duplicated, then the city query.
- `haversine_m`: great-circle distance. `overlap_warnings`: warns when two areas are closer than the sum of
  their radii, because they would share places and look artificially similar.
- `LEVEL_FACTOR`: the evidence penalty per resolution level.

### app/qloo.py
- `ALLOWED_PARAMS`: Qloo silently ignores unknown parameters, which hides bugs, so we refuse to send
  anything not allowlisted. `build_insight_params` raises `QlooError` otherwise, and refuses point/radius for non-places.
- `parse_entities` / `parse_search`: defensive parsing (`results.entities` or a list; `entity_id` or `id`);
  affinity values above 1 are treated as a 0 to 100 scale.
- `QlooClient`: GET only; the API key goes in the `X-Api-Key` header and never in the URL; retries 429 and 5xx
  with `Retry-After` backoff; 401/403 gives an actionable message (hackathon keys work only on
  `hackathon.api.qloo.com`); in-memory cache keyed by path and parameters to save quota. The HTTP opener and sleep
  are injectable, which is how tests run without network.
- Parameter names come from public hackathon projects, not from your key. Verify with the probe script.

### app/mock.py
`MockQloo` implements the same methods. Data is deterministic (hash-based) and every name ends in "(synthetic)".
Area profiles are hand-set so the demo exercises widening (Jubilee Hills is sparse at 2 km). It exists to
test the pipeline; it says nothing about real places.

### app/agent.py
- `_Run`: per-request state; `log_call` assigns `C1, C2...`; `add_evidence` stores entity rows as `C3:entity_id`.
- `_resolve`: seed names to top Qloo match; warns on ambiguity and dropped seeds.
- `_analyze_area`: runs the widening loop, computes `fit`, the control `baseline`, `lift`, `evidence_quality`,
  `confidence`, `comparable`, and stores top places with tags as evidence.
- `analyze`: orchestration. Also warns if two areas return more than 80 percent identical places (Jaccard),
  fetches city-level brands (`signal.location.query`), ranks, builds hypotheses, verifies, optionally rewords.
- `LIMITATIONS` is returned with every report.

### app/ranker.py
Implements section 3's scoring. Operational dimensions are used only if supplied for **every** area; otherwise
they are ignored with a note, and the ranking says it is cultural-only. Notes flag fragile rankings
(top win share under 60 percent) and ties (cultural spread under 0.03).

### app/localize.py
Hypothesis kinds: `preserve` (keep core identity), `taste_signal` (tags of useful TYPES only (menu_highlight, specialty_dish, offerings, dining_option, genre, ambience,
cost_description) carried by at least 2 brand-aligned places and over-indexing by 20+ points versus generic-taste
places; amenity, service, age and neighbourhood tags are ignored, hotel/payment/accessibility names denied), `caution` (low-confidence or city-level areas), `channel_signal` (top city-level brands as candidate
marketing channels, to be checked for relevance).
`maybe_rewrite` accepts an LLM rewrite only if it passes the verifier.

### app/verify.py
`allowed_numbers` collects numbers from cited evidence (affinity to 2 decimals, digits in names) plus
code-derived counts; `verify_hypotheses` returns (kept, rejected-with-reasons).

### app/llm.py
Optional Anthropic Messages API call (`ANTHROPIC_API_KEY`). It cannot add facts because of the verifier.
Written to the public API shape but **not exercised live**.

### app/server.py
Standard-library `ThreadingHTTPServer`. Routes: `GET /`, `/api/health`, `/api/example`, `POST /api/analyze`.
Body capped at 100 KB; at most 2 concurrent analyses (protects API quota on a public demo); errors map to
400 (bad brief), 413, 422 (cannot analyse), 429 (busy), 502 (Qloo error), 500 (generic, no internals leaked).
Request URLs are not logged.

### app/static/index.html
Single page, no build step. All API-derived text is HTML-escaped before display (entity names come from an
external service). Shows the mode banner, ranking table, hypotheses with clickable evidence chips, the agent
trace, limits and the raw evidence log.

### scripts/probe_qloo.py
Day-1 feasibility test with a real key: seed resolution, coverage per radius, **Jaccard overlap between areas**
(1.0 means identical results; if so, neighbourhood ranking is unsupported), and a city-level `signal.location.query` check.

### tests/test_core.py
24 tests: geo chain and overlap, input validation, parameter allowlist, header auth, retry and cache (fake HTTP),
ranker behaviour, verifier accept/reject, end-to-end on mock data, city fallback, LLM rewrite gating, live HTTP server.
A mutation check (disabling the number check in the verifier) made tests fail, confirming they bite.

## 5. How to run

```bash
python -m app.server                      # http://localhost:8000 (mock data, no key)
python -m unittest discover -s tests -t . # run tests
export QLOO_API_KEY=...                   # then:
python scripts/probe_qloo.py              # verify the API assumptions FIRST
python -m app.server                      # live mode (green banner)
docker build -t cc . && docker run -p 8000:8000 -e QLOO_API_KEY=... cc   # deploy
```
Environment: `QLOO_API_KEY`, `QLOO_BASE_URL`, `CC_MOCK=1`, `ANTHROPIC_API_KEY`, `CC_LLM_MODEL`, `PORT`.

## 6. Known limitations and open risks

1. First live probes (28 Oct) confirmed seeds, point/radius place queries and city-level brand signals. Category
   filtering via `/v2/tags` is untested live.
2. **Biggest scientific risk:** neighbourhood circles may return near-identical places, or affinity may mostly
   reflect area popularity. The overlap warning, control baseline and probe test this, but only real data decides.
3. Place tags are whatever Qloo attaches (live ones include business attributes such as 'Upscale' or 'Hotel').
   Place categories (default `cafe`) restrict compared places via `/v2/tags` + `filter.tags`; verified live on 28 Oct
   (about 7 cafes per 1 km circle near Madhapur, so sets are small and `min_results` defaults to 5).
4. Affinity measures taste association, not demand. Rent, competition and footfall are not inferred.
5. Competition density is deliberately not computed: Qloo returns top-affinity places, not all places.
6. Weights (0.6 cultural, `s = 0.4`) are assumptions; the stability check shows sensitivity but does not validate them.
7. No authentication or persistent storage; fine for a demo, not for production. The in-memory cache resets on restart.

## 7. Suggested pitch lines

- "We translate cultural preferences, not languages."
- "Every claim is traceable to a Qloo call, and the verifier rejects the rest."
- "We say when we don't know: city-level fallback is never passed off as neighbourhood insight."

## 8. Performance
Live runs made 14 sequential calls and took about 62 s. The agent now warms the client cache with concurrent
requests (seed searches, then first-attempt area probes and the city query), then runs the same sequential logic
against the cache, so results are identical but wall-clock time should drop to roughly a quarter. Not yet re-timed live.
