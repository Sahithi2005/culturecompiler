import io
import json
import threading
import unittest
import urllib.error
import urllib.request

from app.agent import AnalysisError, analyze
from app.geo import GeoSpec, haversine_m, overlap_warnings, resolution_chain
from app.mock import MockQloo
from app.models import Area, Brief, BriefError, example_brief
from app.qloo import QEntity, QlooClient, QlooError, build_insight_params, parse_entities, parse_tags
from app.ranker import rank_areas
from app.server import make_server
from app.verify import verify_hypotheses


def mk(**over):
    d = example_brief()
    d.update(over)
    return Brief.from_dict(d)


class Geo(unittest.TestCase):
    def test_chain_widens_then_city(self):
        c = resolution_chain(Area("X", 17.4, 78.4, 2000), "Hyderabad")
        self.assertEqual([g.level for g in c], ["neighborhood", "widened", "widened", "city"])
        self.assertEqual([g.radius_m for g in c[:3]], [2000, 4000, 8000])
        self.assertEqual(c[-1].query, "Hyderabad")

    def test_radius_capped(self):
        c = resolution_chain(Area("X", 0, 0, 6000), "C", max_radius=8000)
        self.assertEqual([g.radius_m for g in c[:-1]], [6000, 8000])

    def test_haversine_known_distance(self):
        # 1 degree of latitude is ~111.2 km
        self.assertAlmostEqual(haversine_m(0, 0, 1, 0) / 1000, 111.2, delta=0.5)

    def test_overlap_warning(self):
        a = [Area("A", 17.4486, 78.3908, 2000), Area("B", 17.4326, 78.4071, 2000), Area("C", 17.4401, 78.3489, 500)]
        w = overlap_warnings(a)
        self.assertEqual(len(w), 1)
        self.assertIn("A and B", w[0])


class Models(unittest.TestCase):
    def test_example_valid(self):
        self.assertEqual(len(mk().areas), 3)

    def test_rejects_bad_input(self):
        for bad in [{"seeds": [{"name": "Muji"}]}, {"areas": []}, {"core_identity": []},
                    {"areas": [{"name": "A", "lat": 99, "lon": 0}]},
                    {"seeds": [{"name": "x", "type": "a&b=c"}, {"name": "y"}]},
                    {"operational": {"A": {"rent": 3}}}]:
            with self.assertRaises(BriefError, msg=str(bad)):
                mk(**bad)


class QlooClientTests(unittest.TestCase):
    def test_allowlist_blocks_unknown_and_point_for_non_place(self):
        with self.assertRaises(QlooError):
            build_insight_params("urn:entity:brand", ["a"], GeoSpec("point", "x", "L", lat=1, lon=1, radius_m=5), 5, None, False)

    def test_place_point_params(self):
        p = build_insight_params("urn:entity:place", ["a", "b"], GeoSpec("point", "neighborhood", "L", lat=17.4, lon=78.3, radius_m=2000), 20, None, True)
        self.assertEqual(p["filter.location"], "POINT(78.3 17.4)")
        self.assertEqual(p["signal.interests.entities"], "a,b")
        self.assertNotIn("signal.location.query", p)

    def test_non_place_city_uses_signal_location(self):
        p = build_insight_params("urn:entity:brand", ["a"], GeoSpec("query", "city", "L", query="Hyderabad"), 5, None, False)
        self.assertEqual(p["signal.location.query"], "Hyderabad")

    def test_parse_normalises_affinity_scale(self):
        ents = parse_entities({"results": {"entities": [
            {"entity_id": "1", "name": "A", "query": {"affinity": 87}, "tags": [{"id": "t", "name": "tea"}]},
            {"entity_id": "2", "name": "B", "query": {"affinity": 0.4}}, {"name": "no id"}]}})
        self.assertEqual([round(e.affinity, 2) for e in ents], [0.87, 0.4])

    def test_header_auth_retry_and_cache(self):
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout=0):
            calls.append(req)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "slow", {"Retry-After": "0"}, None)
            return Resp(json.dumps({"results": {"entities": [{"entity_id": "p1", "name": "P", "query": {"affinity": 0.5}}]}}).encode())

        c = QlooClient("SECRET", opener=opener, sleep=lambda s: None)
        ents, call = c.insights("urn:entity:place", ["s1"], take=3)
        self.assertEqual(len(ents), 1)
        self.assertEqual(calls[-1].get_header("X-api-key"), "SECRET")
        self.assertNotIn("SECRET", calls[-1].full_url)
        self.assertTrue(calls[-1].full_url.startswith("https://hackathon.api.qloo.com/v2/insights?"))
        c.insights("urn:entity:place", ["s1"], take=3)
        self.assertEqual(len(calls), 2)  # second identical request served from cache

    def test_401_gives_actionable_error(self):
        def opener(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
        with self.assertRaises(QlooError) as cm:
            QlooClient("k", opener=opener, sleep=lambda s: None).search("x", "urn:entity:brand")
        self.assertIn("hackathon.api.qloo.com", str(cm.exception))


class Ranker(unittest.TestCase):
    def area(self, name, lift, eq, comparable=True, se=None):
        return {"name": name, "lift": lift, "lift_se": se, "evidence_quality": eq, "comparable": comparable}

    def test_higher_lift_wins_and_low_evidence_penalised(self):
        r = rank_areas([self.area("A", .08, 1.0), self.area("B", .08, .3), self.area("C", -.05, 1.0)], {})
        self.assertEqual(r["order"][0], "A")
        self.assertGreater(r["scores"]["A"]["adjusted"], r["scores"]["B"]["adjusted"])
        self.assertEqual(r["order"][-1], "C")

    def test_city_fallback_not_ranked(self):
        r = rank_areas([self.area("A", .05, 1.0), self.area("B", .09, .3, comparable=False)], {})
        self.assertEqual(r["order"], ["A"])
        self.assertEqual(r["excluded"], ["B"])

    def test_operational_dim_used_only_if_complete(self):
        areas = [self.area("A", .08, 1.0), self.area("B", .08, 1.0)]
        r = rank_areas(areas, {"A": {"rent": .9}})
        self.assertEqual(list(r["weights"]), ["cultural"])
        r2 = rank_areas(areas, {"A": {"rent": .9}, "B": {"rent": .1}})
        self.assertEqual(r2["order"], ["A", "B"])
        self.assertEqual(r2["ranks"], {"A": 1, "B": 2})
        self.assertIn("rent", r2["weights"])

    def test_tie_without_se_uses_adjusted_gap_and_is_deterministic(self):
        areas = [self.area("A", .000, 1.0), self.area("B", .003, 1.0)]
        r1, r2 = rank_areas(areas, {}), rank_areas(areas, {})
        self.assertEqual(r1["stability"], r2["stability"])
        self.assertTrue(any("barely separates" in n for n in r1["notes"]))
        self.assertEqual(r1["tied"], ["A", "B"])
        self.assertEqual(set(r1["ranks"].values()), {1})

    def test_se_tie_test_makes_noisy_gap_a_tie_and_clear_gap_an_order(self):
        noisy = rank_areas([self.area("A", .05, 1.0, se=.02), self.area("B", .04, 1.0, se=.02)], {})
        self.assertEqual(noisy["tied"], ["A", "B"])  # gap .01 < 2*hypot(.02,.02)=.057
        clear = rank_areas([self.area("A", .08, 1.0, se=.005), self.area("B", -.02, 1.0, se=.005)], {})
        self.assertEqual(clear["ranks"], {"A": 1, "B": 2})
        self.assertEqual(clear["tied"], [])

    def test_area_without_lift_is_not_scored(self):
        r = rank_areas([self.area("A", .08, 1.0), self.area("B", None, 1.0)], {})
        self.assertEqual(r["order"], ["A"])


class Verifier(unittest.TestCase):
    ev = {"C1:e1": {"affinity": 0.68, "name": "Cafe 7"}}

    def test_accepts_traceable(self):
        h = {"statement": "Affinity 0.68 at Cafe 7; 2 of 10", "evidence": ["C1:e1"], "derived_numbers": ["2", "10"]}
        ok, bad = verify_hypotheses([h], self.ev, {})
        self.assertEqual((len(ok), len(bad)), (1, 0))

    def test_rejects_unknown_id_invented_number_and_empty(self):
        hs = [{"statement": "x", "evidence": ["nope"]},
              {"statement": "Affinity 0.91", "evidence": ["C1:e1"]},
              {"statement": "x", "evidence": []}]
        ok, bad = verify_hypotheses(hs, self.ev, {})
        self.assertEqual((len(ok), len(bad)), (0, 3))


class EndToEnd(unittest.TestCase):
    def test_mock_pipeline(self):
        r = analyze(mk(min_results=8), MockQloo())
        self.assertTrue(r["synthetic"])
        self.assertEqual(len(r["areas"]), 3)
        self.assertEqual(r["rejected"], [])
        self.assertTrue(any(t["step"] == "widen" for t in r["trace"]))  # Jubilee Hills thin at 2 km
        for h in r["hypotheses"]:
            for e in h["evidence"]:
                self.assertTrue(e in r["evidence"] or e in r["calls"])
        jh = next(a for a in r["areas"] if a["name"] == "Jubilee Hills")
        self.assertEqual(jh["resolution"]["level"], "widened")  # never relabelled as neighbourhood

    def test_city_fallback_marks_incomparable(self):
        class Thin(MockQloo):
            def insights(self, ft, ids, geo=None, **kw):
                ents, call = super().insights(ft, ids, geo, **kw)
                if ft == "urn:entity:place" and geo.kind == "point":
                    return ents[:2], call
                return ents, call
        r = analyze(mk(), Thin())
        self.assertTrue(all(a["resolution"]["level"] == "city" and not a["comparable"] for a in r["areas"]))
        self.assertEqual(r["ranking"]["order"], [])
        self.assertTrue(any(h["kind"] == "caution" for h in r["hypotheses"]))

    def test_unresolvable_seeds_abort(self):
        class Empty(MockQloo):
            def search(self, q, t, take=3):
                return [], {"endpoint": "/search", "params": {}, "n": 0, "cached": False}
        with self.assertRaises(AnalysisError):
            analyze(mk(), Empty())

    def test_llm_rewrite_must_pass_verifier(self):
        class Liar:
            def rewrite(self, s, ev): return "This will boost sales by 45 percent in the first quarter."
        class Good:
            def rewrite(self, s, ev): return s.replace("Explore", "Consider exploring")
        r = analyze(mk(), MockQloo(), Liar())
        self.assertFalse(any(h.get("reworded_by_llm") for h in r["hypotheses"]))
        r2 = analyze(mk(), MockQloo(), Good())
        self.assertTrue(any(h.get("reworded_by_llm") for h in r2["hypotheses"]))


class DotEnv(unittest.TestCase):
    def test_load_dotenv_sets_missing_only(self):
        import os, tempfile, pathlib
        from app.server import load_dotenv
        d = pathlib.Path(tempfile.mkdtemp()) / ".env"
        d.write_text('# c\nCC_TEST_A="one"\nCC_TEST_B=two\n')
        os.environ["CC_TEST_B"] = "keep"
        load_dotenv(d)
        self.assertEqual((os.environ["CC_TEST_A"], os.environ["CC_TEST_B"]), ("one", "keep"))


class LiveFindings(unittest.TestCase):
    """Behaviours added after the first live probe (28 Oct)."""

    def test_ambiguous_seed_picks_most_popular_exact_match(self):
        class Amb(MockQloo):
            def search(self, q, t, take=3):
                a = QEntity("low", q, t, popularity=0.1)
                b = QEntity("high", q, t, popularity=0.9)
                return [a, b], {"endpoint": "/search", "params": {}, "n": 2, "cached": False}
        r = analyze(mk(), Amb())
        ids = {e["entity_id"] for e in r["evidence"].values() if e["role"] == "brand_seed"}
        self.assertEqual(ids, {"high"})
        self.assertTrue(any("most popular" in w for w in r["warnings"]))

    def test_default_radius_is_1km_and_areas_do_not_overlap(self):
        b = mk()
        self.assertTrue(all(a.radius_m == 1000 for a in b.areas))
        self.assertEqual(overlap_warnings(b.areas), [])

    def test_mock_run_produces_paired_stats_and_peer_places(self):
        r = analyze(mk(), MockQloo())
        for a in r["areas"]:
            self.assertGreaterEqual(a["n_paired"], 2)
            self.assertIsNotNone(a["lift"])
            self.assertIsNotNone(a["lift_se"])
        self.assertTrue(any(h["kind"] == "peer_places" for h in r["hypotheses"]))
        self.assertEqual(r["rejected"], [])


class CategoriesAndTags(unittest.TestCase):
    def test_tag_params_and_union_operator(self):
        g = GeoSpec("point", "neighborhood", "L", lat=1, lon=2, radius_m=1000)
        p = build_insight_params("urn:entity:place", ["a"], g, 20, None, True, ["t1", "t2"])
        self.assertEqual((p["filter.tags"], p["operator.filter.tags"]), ("t1,t2", "union"))
        p1 = build_insight_params("urn:entity:place", ["a"], g, 20, None, True, ["t1"])
        self.assertNotIn("operator.filter.tags", p1)

    def test_parse_tags_defensive(self):
        out = parse_tags({"results": {"tags": [{"id": "urn:tag:category:place:cafe", "name": "Cafe", "type": "x"},
                                               {"name": "no id"}]}})
        self.assertEqual([t["name"] for t in out], ["Cafe"])
        self.assertEqual(parse_tags({"results": [{"tag_id": "z", "name": "Z"}]})[0]["id"], "z")

    def test_category_resolution_flows_into_report(self):
        r = analyze(mk(place_categories=["cafe"]), MockQloo())
        self.assertTrue(any(t["step"] == "category" for t in r["trace"]))
        self.assertEqual(r["brief"]["place_categories"], ["cafe"])

    def test_unresolvable_category_warns_and_continues(self):
        class NoTags(MockQloo):
            def tags(self, q, take=5):
                return [], {"endpoint": "/v2/tags", "params": {}, "n": 0, "cached": False}
        r = analyze(mk(place_categories=["cafe"]), NoTags())
        self.assertTrue(any("No place tag found" in w for w in r["warnings"]))
        self.assertEqual(len(r["areas"]), 3)

    def test_tags_endpoint_uses_header_and_path(self):
        seen = []

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout=0):
            seen.append(req)
            return Resp(json.dumps({"results": {"tags": [{"id": "urn:tag:category:place:cafe", "name": "Cafe"}]}}).encode())
        tags, call = QlooClient("K", opener=opener).tags("cafe")
        self.assertEqual(tags[0]["id"], "urn:tag:category:place:cafe")
        self.assertIn("/v2/tags?", seen[0].full_url)
        self.assertEqual(seen[0].get_header("X-api-key"), "K")


class Hypotheses(unittest.TestCase):
    def pl(self, i, tags, diff=0.05):
        return {"name": f"P{i}", "evidence_id": f"B{i}", "control_evidence_id": f"G{i}", "brand": .8,
                "control": round(.8 - diff, 2), "diff": diff,
                "tags": [{"id": n, "name": n, "type": ty} for n, ty in tags]}

    def run_one(self, lean_tags, rest_tags, n=3):
        from app.localize import build_hypotheses
        lean = [self.pl(i, lean_tags) for i in range(n)]
        rest = [self.pl(10 + i, rest_tags, diff=0.0) for i in range(n)]
        paired = lean + rest
        a = {"name": "Z", "top_places": [], "peers": paired[:3], "leaning": lean, "other": rest, "n_paired": len(paired),
             "confidence": "high", "comparable": True, "resolution": {"level": "neighborhood"}, "n_scored": 20,
             "call": "C1"}
        ev = {}
        for p in paired:
            ev[p["evidence_id"]] = {"name": p["name"], "affinity": p["brand"]}
            ev[p["control_evidence_id"]] = {"name": p["name"], "affinity": p["control"]}
        hy = build_hypotheses(mk(), [a], ev, [], [], {"Z": "C1"})
        ok, bad = verify_hypotheses(hy, ev, {"C1": {}})
        self.assertEqual(bad, [])
        return ok

    def tag(self, h):
        return h["statement"].split("carry the '")[1].split("'")[0]

    def test_only_useful_tag_types_overindex_and_dedupe(self):
        lean = [("Mastercard", "urn:tag:amenity:qloo"), ("Dessert", "urn:tag:menu_highlight:qloo"),
                ("dessert", "urn:tag:menu_highlight:qloo"), ("Brunch", "urn:tag:menu_highlight:qloo"),
                ("Hotel", "urn:tag:genre:place"), ("Stylish", "urn:tag:ambience:qloo"),
                ("Families", "urn:tag:neighborhood_characteristic:qloo")]
        rest = [("Brunch", "urn:tag:menu_highlight:qloo")]
        ok = [h for h in self.run_one(lean, rest) if h["kind"] == "taste_signal"]
        self.assertEqual(sorted(self.tag(h) for h in ok), ["Dessert", "Stylish"])
        by = {self.tag(h): h["statement"] for h in ok}
        self.assertIn("ambience or space-design cue", by["Stylish"])
        self.assertIn("menu cue", by["Dessert"])

    def test_untyped_tags_and_shared_tags_give_no_taste_signal(self):
        self.assertEqual([h for h in self.run_one([("Dessert", None)], []) if h["kind"] == "taste_signal"], [])
        shared = [("Dessert", "urn:tag:menu_highlight:qloo")]
        self.assertEqual([h for h in self.run_one(shared, shared) if h["kind"] == "taste_signal"], [])

    def test_peer_places_hypothesis_is_verified_and_cites_both_scores(self):
        ok = [h for h in self.run_one([], []) if h["kind"] == "peer_places"]
        self.assertEqual(len(ok), 1)
        self.assertIn("brand 0.80 vs generic 0.75", ok[0]["statement"])
        self.assertEqual(len(ok[0]["evidence"]), 6)

    def test_peer_places_exclude_places_where_generic_taste_scores_higher(self):
        from app.localize import build_hypotheses
        peers = [self.pl(1, [], diff=.04), self.pl(2, [], diff=.02), self.pl(3, [], diff=-.03)]
        a = {"name": "Z", "top_places": [], "peers": peers, "leaning": [], "other": [], "n_paired": 3,
             "confidence": "high", "comparable": True, "resolution": {"level": "neighborhood"}, "n_scored": 5, "call": "C1"}
        ev = {}
        for p in peers:
            ev[p["evidence_id"]] = {"name": p["name"], "affinity": p["brand"]}
            ev[p["control_evidence_id"]] = {"name": p["name"], "affinity": p["control"]}
        h = [x for x in build_hypotheses(mk(), [a], ev, [], [], {"Z": "C1"}) if x["kind"] == "peer_places"]
        self.assertEqual(len(h), 1)
        self.assertIn("P1", h[0]["statement"])
        self.assertIn("P2", h[0]["statement"])
        self.assertNotIn("P3", h[0]["statement"])

    def test_channel_signals_are_one_combined_verified_hypothesis(self):
        r = analyze(mk(), MockQloo())
        ch = [h for h in r["hypotheses"] if h["kind"] == "channel_signal"]
        self.assertEqual(len(ch), 1)
        self.assertEqual(len(ch[0]["evidence"]), 3)


class LiveModeParallel(unittest.TestCase):
    def test_live_mode_prefetch_does_not_change_result(self):
        class FakeLive(MockQloo):
            mode = "live"
        a, b = analyze(mk(), FakeLive()), analyze(mk(), MockQloo())
        self.assertEqual([x["name"] for x in a["areas"]], [x["name"] for x in b["areas"]])
        self.assertEqual([x["lift"] for x in a["areas"]], [x["lift"] for x in b["areas"]])

    def test_ties_have_no_win_share(self):
        class Flat(MockQloo):  # brand and control are identical => lift 0 and se 0 everywhere
            def insights(self, ft, ids, geo=None, **kw):
                return super().insights(ft, ["mock-brand-coca-cola"], geo, **kw)
        r = analyze(mk(), Flat())
        self.assertTrue(all(a["tied"] and a["win_share"] is None for a in r["areas"]))


class Hardening(unittest.TestCase):
    def test_example_defaults_use_cafe_category(self):
        b = mk()
        self.assertEqual((b.place_categories, b.min_results), (["cafe"], 5))

    def test_category_preference_picks_restaurant_cafe_tag(self):
        class Tags(MockQloo):
            def tags(self, q, take=5):
                ts = [{"id": "urn:tag:genre:place:hotel:cafe", "name": "Cafe", "type": "urn:tag:genre:place"},
                      {"id": "urn:tag:genre:place:restaurant:cafe", "name": "Cafe", "type": "urn:tag:genre:place"},
                      {"id": "urn:tag:category:place:cafe", "name": "Cafe", "type": "urn:tag:category:place"}]
                return ts, {"endpoint": "/v2/tags", "params": {}, "n": 3, "cached": False}
        r = analyze(mk(), Tags())
        step = next(t for t in r["trace"] if t["step"] == "category")
        self.assertIn("urn:tag:genre:place:restaurant:cafe", step["detail"])

    def test_rate_limit_per_ip(self):
        from app import server
        old, server._hits = server.RATE, {}
        try:
            server.RATE = (2, 60)
            self.assertEqual([server.rate_limited("1.1.1.1", 0), server.rate_limited("1.1.1.1", 1),
                              server.rate_limited("1.1.1.1", 2), server.rate_limited("2.2.2.2", 2),
                              server.rate_limited("1.1.1.1", 100)], [False, False, True, False, False])
        finally:
            server.RATE = old

    def test_cache_is_bounded(self):
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        c = QlooClient("K", opener=lambda req, timeout=0: Resp(b'{"results": []}'))
        for i in range(620):
            c.search(f"q{i}", "urn:entity:brand")
        self.assertLessEqual(len(c._cache), 500)


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server(0, client=MockQloo())
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def req(self, path, data=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                   data=None if data is None else (data if isinstance(data, bytes) else json.dumps(data).encode()),
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_health_page_and_analyze(self):
        s, b = self.req("/api/health")
        self.assertEqual((s, json.loads(b)["mode"]), (200, "mock"))
        s, b = self.req("/")
        self.assertIn(b"CultureCompiler", b)
        s, b = self.req("/api/analyze", example_brief())
        self.assertEqual(s, 200)
        self.assertEqual(len(json.loads(b)["areas"]), 3)

    def test_bad_requests(self):
        self.assertEqual(self.req("/api/analyze", b"not json")[0], 400)
        s, b = self.req("/api/analyze", {"brand": "x"})
        self.assertEqual(s, 400)
        self.assertIn("error", json.loads(b))
        self.assertEqual(self.req("/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()