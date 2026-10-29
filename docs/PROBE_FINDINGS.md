# Live probe findings (28 Oct 2026, hackathon key, summary statistics only)

| Question | Result | Consequence |
|---|---|---|
| Seeds resolve? | Muji, Blue Bottle Coffee, Spirited Away, Haruki Murakami all found. "Haruki Murakami" has 2 same-name entities | Resolver now picks the most popular exact-name match and warns |
| Places filter by POINT + radius works? | Yes, 20 scored places at >= 1 km (Gachibowli only 2 at 500 m) | Approach is feasible; default radius set to 1 km |
| Do areas differ? | Overlap (Jaccard) about 0.00 at <= 2 km; Madhapur~Jubilee 0.74 at 4 km | 2 km circles overlapped; use 1 km. Neighbourhood place lists DO differ |
| Does affinity level separate areas? | No: top-20 affinities sit around 0.80-0.82 at 1-8 km | Do not rank on affinity level alone; localization now uses tags that over-index vs generic taste |
| City brands via signal.location.query | Accepted and returned brands, but results looked generic (e.g. Uber Eats, Eater) | Probe v2 compares Hyderabad vs Tokyo vs no location to check whether the parameter is really honoured |

Qloo rules: private server-side caching is allowed; do not store Qloo response data in a public repository.

## Second probe + live app run (28 Oct 2026, 1 km circles)
| Area | Overlap brand-vs-generic places | Note |
|---|---|---|
| Gachibowli | 0.74 | brand taste mostly picks the same places as generic taste (hotels, BBQ chains) |
| Madhapur | 0.18 | brand taste picks different places |
| Jubilee Hills | 0.18 | brand taste picks different places |

* Generic seeds had HIGHER affinity (~0.83-0.84) than brand seeds (~0.80), so "lift" was negative everywhere and is no longer used.
* City location IS honoured for brands: Hyderabad vs Tokyo overlap 0.11, Hyderabad vs none 0.08. Results are generic consumer/media brands, so they are shown as channel signals, not partners.
* Places include hotels and inns; tags include payment/accessibility attributes. Hence the denylist and the optional place-category filter.
* take=50 works. A full live run took ~62 s sequentially, hence the concurrent prefetch.

## Third probe (28 Oct 2026)
* `/v2/tags?filter.query=cafe` returns several tags; `urn:tag:genre:place:restaurant:cafe` works as `filter.tags` and returns real cafes (n=7 near Madhapur at 1 km; 0.08 overlap with the unfiltered hotel-heavy list). The resolver prefers this id.
* Tag TYPES seen on places: menu_highlight, ambience, genre, amenity, neighborhood_characteristic, interests, offerings, category, activity_type, service_type, age_range, cost_description. Only menu, ambience and price types feed localization ideas.
* After concurrent prefetch, a full live run took ~12 s (was ~62 s).
