# CultureCompiler concepts, simple ga (like to a 10-year-old)

## 0. Big idea
Tokyo lo oka café superhit. Hyderabad lo open cheste? Menu ni Telugu lo translate chesthe saripodu. **Taste** (evaru emi ishtapadatharu) marali. CultureCompiler = "taste translator".

## 1. Qloo taste graph = giant "friend map" of likes
Oka pedda map imagine cheyyi. Prathi cheez (movie, brand, café, song) oka **dot**. Rendu dots ni same people like chesthe, vati madhya **line**. Qloo ade: lakshala dots + lines.
- **Entity** = oka dot (Muji, Spirited Away, oka café).
- **Tag** = dot ki sticker ("tea", "quiet", "dessert").
- **Signal** = nuvvu icche hint: "ee dots ni ishtapade vallaki..." (our brand seeds).
- **Filter** = rules: "places matrame", "ee area lo matrame".
- **Affinity** = ishtam strength, 0 nundi 1. 0.8 = chala close, 0.5 = middling.
- **Explainability** = "ee result enduku vachindi?" ani Qloo cheppe reason.

## 2. API = restaurant waiter
Nuvvu (app) kitchen (Qloo) tho direct matladav. Waiter (API) ki order istav: `GET /search` ("Muji ante evaru?" → dot ID) tarvata `GET /v2/insights` ("ee dots ishtapade valla taste ki daggara ga ee area lo emunnayi?"). **API key** = nee table number; evvariki cheppaku, server lone pettu (browser lo kaadu).

## 3. Brand DNA = "what must not change"
Hikari ki: matcha, specialty coffee, calm design. Ivi marchakudadu. Marchedi: side items, positioning, partners. Anduke `core_identity` (marchakudadu) vs taste seeds (compare cheyyadaniki).

## 4. Seeds = nee brand ki "friends list"
Muji, Blue Bottle, Spirited Away, Murakami. Ivi Hikari customers ishtapade cheelu. Qloo ki ivi icchi adugutham: "ilanti taste vallu Gachibowli lo eventi ishtapadatharu?"

## 5. Geographic zoom + fallback = binoculars
Madhapur close ga chudali. Kani chala takkuva data vasthe, binoculars zoom out chestham: 2 km → 4 km → 8 km → city. **Rule: zoom out ayyaka, adi "neighbourhood data" ani abaddham cheppakudadu.** Anduke resolution label prathi result ki untundi. City-level ki fall ayithe, anni areas ki same data → ranking ivvam.

## 6. Control seeds + Lift = "class average" trick
Oka student 70 marks techadu. Great aa? Class average 90 aithe kaadu. Alage Madhapur ki affinity 0.67 ante? Coca-Cola/Netflix/Spotify (generic taste) ki 0.52 ante, **lift = 0.67 − 0.52 = +0.15**. Ante Madhapur "popular area" ani kaadu, "mana taste ki specially close" ani. Idi mana main scientific idea; but real data lo work avutundo test cheyali (open question).

## 7. Evidence quality = "entha nammochu?"
Data entha undi (10 places leka 2?), entha zoom-out chesam (neighbourhood > widened > city). Takkuva evidence unte score ni konchem taggistham. Pill: high / medium / low.

## 8. Ranking + stability = "weights maarthe winner maaratha?"
Score = lift × evidence factor. Weights (enta important) manam nirnayinchina assumptions, Qloo cheppindi kaadu. So 500 sarlu weights ni konchem maarchi, prathi sari evaru gelichaaro count chestham. Win share 100% = steady. 40% = fragile, jagratta.

## 9. Agent vs chatbot
Chatbot: question → answer. **Agent**: loop lo pani chestundi: plan → tools vadatam (search, insights) → result chusi decide (data takkuva ah? zoom out) → stop rule. UI lo "How the agent worked" trace adi chupistundi. (Mana version lo decisions rules tho; LLM optional wording kosam matrame.)

## 10. Hypothesis vs fact + Verifier
"Madhapur lo 5/10 places ki 'quiet' tag undi" = **evidence**. "Quiet-led item test cheyyi" = **hypothesis** (idea). Verifier = strict teacher: prathi claim lo cited evidence ID unda? Numbers evidence lo unnaya? Lekapote claim reject. LLM wording marchina same check pass avvali. Idi hallucination ni apeste.

## 11. Mock mode = practice ground
Key lekunda app run avvali (judges kuda try cheyali). Mock data fake, "(synthetic)" ani label, yellow banner. Pipeline test kosam matrame; Hyderabad gurinchi nijalu kaadu.

## 12. What this can NOT do (judges ki honest ga cheppu)
Taste ≠ demand ≠ profit. Rent, competition, footfall Qloo ivvadu; nuvve ivvali (optional inputs). Output anni "test cheyyali" hypotheses; pop-up chesi customers tho validate cheyyali.

## Quiz (nuvvu answer ivvu)
Madhapur lift +0.15 kani evidence "low" (city fallback). Gachibowli lift +0.09 "high". Evaru mundu? Enduku?
