# CultureCompiler

An agent that finds where a brand culturally fits (country → neighbourhood) and proposes evidence-backed
localization hypotheses, using Qloo's taste graph. *We translate cultural preferences, not languages.*

Step-by-step instructions: docs/RUNBOOK.md. Architecture and code walkthrough: docs/ARCHITECTURE.md.

## Run (no pip install needed, Python 3.10+)
    python -m app.server                  # http://localhost:8000, SYNTHETIC data without a key
    QLOO_API_KEY=... python -m app.server # live mode
    python -m unittest discover -s tests -t .
    QLOO_API_KEY=... python scripts/probe_qloo.py   # DAY-1 feasibility probe: run this first

Optional: `ANTHROPIC_API_KEY` lets an LLM polish hypothesis wording (rewrites are verifier-checked). `CC_MOCK=1` forces mock.

## How it works
(places are restricted to a venue category such as `cafe` via `/v2/tags` + `filter.tags`)
plan → resolve seeds (/search) → per area: probe places (/v2/insights), widen radius → city fallback if thin →
control-seed comparison → distinct-taste-cluster score → evidence-weighted ranking with ties + re-weighting stability → hypotheses → verifier.
City-level fallback is labelled as such and never ranked against neighbourhood results.

## Honest status
* Tested: 44 unit/integration tests on mock data and a fake HTTP transport.
* Live (28 Oct 2026, hackathon key): seed search, place queries by point+radius, `/v2/tags` category lookup,
  `filter.tags` restriction to cafes and city-level brand signals were exercised with the probe script; the web app
  ran end to end in live mode. The final v4 defaults (cafe filter on) should be re-checked once with a live run.
* Qloo gives taste affinity, not demand, rent, or profit. Operational scores are user-supplied only.
* Mock data is invented and labelled in the UI.

## Deploy
`docker build -t cc . && docker run -p 8000:8000 -e QLOO_API_KEY=... cc` (Render/Railway/Fly accept the Dockerfile).
Set the key as a server env var only. License: MIT.
