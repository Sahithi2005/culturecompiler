# Findings from live probes (28-29 Oct 2026, hackathon key, summary statistics only)

| Question | Result | Consequence |
|---|---|---|
| Do seeds resolve? | Muji, Blue Bottle Coffee, Spirited Away, Haruki Murakami all found (the last has 2 same-name entities) | Resolver picks the most popular exact-name match and warns |
| Place queries by POINT + radius | Work; 20 scored places at >= 1 km (Gachibowli only 2 at 500 m) | Default radius 1 km, automatic widening |
| Do neighbouring areas differ? | Place-list overlap about 0 at <= 2 km; Madhapur~Jubilee 0.74 at 4 km | Circles of 2 km overlapped; 1 km used |
| Does affinity level separate areas? | No: top-20 affinities about 0.80-0.82 everywhere; generic seeds scored higher (~0.83-0.84) | Raw level not used; paired per-place lift used instead |
| City location for brands | Honoured: Hyderabad vs Tokyo overlap 0.11, vs no location 0.08. Results are generic consumer/media brands | Shown as channel signals to verify |
| Category filter | `/v2/tags` + `filter.tags=urn:tag:genre:place:restaurant:cafe` returns real cafes (7 near Madhapur at 1 km) | Cafe filter on by default; `min_results` 5 |
| Tag types on places | menu_highlight, ambience, genre, amenity, neighborhood_characteristic, offerings, category, service_type, age_range, cost_description | Only menu, ambience and price types feed ideas |
| Brand vs generic place sets with cafe filter | Same complete set returned for both, so set overlap is uninformative | Paired lift per place (see ARCHITECTURE) |
| Speed | Sequential ~62 s; with concurrent prefetch ~12 s | Prefetch added |

Qloo rule: private server-side caching is allowed; Qloo response data must not be stored in a public repository.