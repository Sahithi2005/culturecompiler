# RUNBOOK: what to do, in order

Goal: a public live demo + public GitHub repo + open-source licence, submitted before the Qloo hackathon closes
(30 Oct 2026; confirm the exact time and time zone on the official hackathon page).

## Honest status
Built and tested on synthetic data (24 tests pass). **Never run against the live Qloo API.** Step 3 is the
one that matters most. Everything after it depends on its result.

## Step 1. Run it locally (5 min, no key needed)
Requirements: Python 3.10 or newer. No pip install.
```
unzip culturecompiler.zip
cd culturecompiler
python -m app.server
```
Open http://localhost:8000 and click "Analyze expansion opportunities". You should see a yellow SYNTHETIC banner,
a 3-row table, hypotheses and an agent trace. Stop the server with Ctrl+C.

## Step 2. Run the tests (1 min)
```
python -m unittest discover -s tests -t .
```
Expect: "Ran 24 tests ... OK".

## Step 3. Probe the real Qloo API (10 min). Most important step
Mac/Linux:
```
export QLOO_API_KEY=your_hackathon_key
python scripts/probe_qloo.py
```
Windows PowerShell:
```
$env:QLOO_API_KEY="your_hackathon_key"
python scripts/probe_qloo.py
```
Read the output in four parts:

| Part | Good sign | Bad sign and what to do |
|---|---|---|
| 1 Seed resolution | At least 2 of 4 seeds show a real match | "NOT FOUND" for most: change seed names/types in `app/models.py` `example_brief()` |
| 2 Coverage by radius | `scored` is 8 or more at 2000 m | scored=0 everywhere: place filter parameters need fixing in `app/qloo.py` |
| 3 Area overlap (Jaccard) | Values well below 0.8 at 1000 m | 0.9 to 1.0: areas return the same places; pitch city-level, not neighbourhood-level |
| 4 City brands | A list of brand names | ERROR: `signal.location.query` is not accepted; the app already degrades with a warning |

An HTTP 401 means the key or host is wrong (hackathon keys work only on https://hackathon.api.qloo.com).
Any other error: copy the full output to Claude and ask for a fix to `app/qloo.py`. Small parameter fixes are expected.

## Step 4. Run the app in live mode (2 min)
```
python -m app.server
```
The banner must be green ("Live mode"). Run the default example and check:
- Do place names look real for Hyderabad?
- Does the trace show widening or city fallback honestly?
- Do areas differ in lift, or is the spread tiny (the app will say so)?
Try 2 more briefs (for example a different brand or city) so your demo is not one hard-coded story.

## Step 5. Put it on GitHub (10 min)
1. Create a **public** repo on github.com (empty, no README).
2. In the project folder:
```
git init
git add .
git commit -m "CultureCompiler"
git branch -M main
git remote add origin https://github.com/<you>/culturecompiler.git
git push -u origin main
```
3. Check the repo contains no key: `git grep -n "hack_"` must print nothing. `.gitignore` already excludes `.env`.
The MIT LICENSE file is included; GitHub should show "MIT license" on the repo page.

## Step 6. Deploy a public demo (20 min)
Render.com (free tier is fine):
1. New > Web Service > connect your GitHub repo.
2. Runtime: **Docker** (the Dockerfile is included). No build or start command needed.
3. Environment variables: `QLOO_API_KEY` = your key. Optionally `ANTHROPIC_API_KEY`.
4. Health check path: `/api/health`.
5. When it is live, open the URL; the banner should say "Live mode". Run the example once.
Free instances sleep when idle: open the URL a few minutes before judges might, and mention it in the README.
Railway or Fly.io also accept the Dockerfile. The server limits itself to 2 concurrent analyses to protect quota.

## Step 7. Submission checklist
- [ ] Public demo URL works and is in live mode
- [ ] Public GitHub repo with LICENSE (MIT) and README
- [ ] README states what is real and what is not (it already has an "Honest status" section)
- [ ] AI-assistance disclosure if the official rules ask for it
- [ ] Demo video (2 to 3 minutes) if requested: see script below
- [ ] Re-read the official rules for required fields, eligibility and "built during the hackathon" conditions

## Demo script (about 2 minutes)
1. (15s) Problem: "A Tokyo café can't just copy-paste into Hyderabad. Tastes differ by neighbourhood."
2. (30s) Enter the brief; show seeds (Muji, Blue Bottle, Spirited Away) and 3 areas; click Analyze.
3. (30s) Show the ranking table: fit, generic baseline, lift, evidence confidence. Explain lift in one sentence.
4. (20s) Show the trace: it widened one area's radius and labelled it. "We never pass city data off as neighbourhood data."
5. (20s) Open one hypothesis; click an evidence chip to show the underlying Qloo entity.
6. (10s) Limits: "Taste is not demand; every idea is a hypothesis to test with a pop-up."

## Suggested schedule
- **Wed 28 Oct:** Steps 1 to 4. Fix whatever the probe reveals.
- **Thu 29 Oct:** Steps 5 and 6, try 2 extra brands, polish README, record video.
- **Fri 30 Oct:** Final check against the rules, submit early, not at the deadline.

## Troubleshooting
| Symptom | Likely cause | Fix |
|---|---|---|
| Banner stays yellow | `QLOO_API_KEY` not set in that shell, or `CC_MOCK=1` | Set the variable in the same terminal that runs the server |
| "Qloo rejected the key (HTTP 401)" | Wrong key or wrong host | Use https://hackathon.api.qloo.com and the hackathon key |
| "Fewer than 2 brand seeds resolved" | Seed names/types not found | Use well-known names; types: brand, movie, artist, person, book, podcast, tv_show |
| Every area shows "city" resolution | Neighbourhood queries return too little data | Increase radius, lower `min_results`, or pitch at city level |
| HTTP 429 "Server busy" | 2 analyses already running | Wait a few seconds |
| Two areas flagged as overlapping | Circles overlap | Reduce radius_m (for example 1000) |

## Security
Never commit or share the API key. It was pasted into a chat, so rotate it after the hackathon.
Keep it only in environment variables (local shell and the hosting dashboard).

## Update (v3): place categories
After running the v3 probe, look at section 8. If `'cafe'` returns a tag whose id contains `:place`, and the filtered
sample shows real cafes, type `cafe` into the **Place categories** box in the UI (or set `"place_categories": ["cafe"]`
in `example_brief()`). That restricts compared places to cafes and removes hotels from the results.
Do not commit any saved Qloo responses to a public repo.

## FINAL SUBMISSION PATH (v4)
1. Unzip, open the inner folder in VS Code, run the tests (expect 44 OK).
2. `$env:QLOO_API_KEY="..."` then `python -m app.server`; open http://localhost:8000; confirm green banner and the
   "Place categories" box shows `cafe`. Click Analyze. Place names should now be cafes.
3. Push to a public GitHub repo (see Step 5). Deploy on Render using the included `render.yaml` or Docker (Step 6).
4. Submit the demo URL and repo URL. Keep the API key only in Render's environment settings.
