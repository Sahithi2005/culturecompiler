# CultureCompiler

An agent that finds where a brand culturally fits (country → neighbourhood) and proposes evidence-backed
localization hypotheses, using Qloo's taste graph. *We translate cultural preferences, not languages.*

**Live demo:** https://culturecompiler.onrender.com/

Architecture and code walkthrough: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Live Qloo probe findings: [docs/PROBE_FINDINGS.md](docs/PROBE_FINDINGS.md).

## Run (no pip install needed, Python 3.10+)
    python -m app.server                  # http://localhost:8000, SYNTHETIC data without a key
    QLOO_API_KEY=... python -m app.server # live mode
    python -m unittest discover -s tests -t .
    QLOO_API_KEY=... python scripts/probe_qloo.py   # feasibility probe (prints summaries only, no key)

`CC_MOCK=1` forces synthetic data.

## How it works
(places are restricted to a venue category such as `cafe` via `/v2/tags` + `filter.tags`)
plan → resolve seeds (/search) → per area: probe places (/v2/insights), widen radius → city fallback if thin →
paired brand-vs-generic lift per place → area lift ± standard error → ranking with statistical ties + re-weighting stability → hypotheses → verifier.
City-level fallback is labelled as such and never ranked against neighbourhood results.

## Honest status
* Tested: 46 unit/integration tests on mock data and a fake HTTP transport.
* Live (28-29 Oct 2026, hackathon key): seed search, place queries by point+radius, `/v2/tags` category lookup, `filter.tags` restriction to cafes and city-level brand signals were exercised with the probe script, and the full web app was run end to end in live mode (about 12 s per analysis).
* Qloo's raw place affinity is nearly flat across areas, so each place is scored twice (brand taste vs generic taste) and areas are compared by the paired difference. With 5-10 cafes per area the comparison is often a statistical tie; the app says so and shows closest peer places and tag cues instead.
* Qloo gives taste affinity, not demand, rent, or profit. Operational scores are user-supplied only.
* Mock data is invented and labelled in the UI.

## Deploy
`docker build -t cc . && docker run -p 8000:8000 -e QLOO_API_KEY=... cc` (Render/Railway/Fly accept the Dockerfile).
Set the key as a server env var only. License: MIT.

## API key
| Variable | Needed? | Purpose |
|---|---|---|
| `QLOO_API_KEY` | **Yes, for live mode** | Qloo hackathon key, sent only in the `X-Api-Key` header to `https://hackathon.api.qloo.com`. Without it the app runs on clearly labelled synthetic data. |

Set it as an environment variable (locally in your terminal, or in your hosting dashboard). It is never stored in the repo, and Qloo responses are cached in memory only and are not committed.
The agent loop (planning, widening the search area, scoring, ranking, evidence checking) is rule-based.