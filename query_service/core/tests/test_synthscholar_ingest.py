"""SynthScholar review ingestion: what an output directory keeps, how review.json is
read (plain JSON, not the package), the import record that goes into the graph, and
the endpoint's permission and once-per-review checks. Offline fakes for the space,
role and storage calls, like the other router tests."""
import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from rdflib import Graph, URIRef
from rdflib.namespace import PROV

from .. import synthscholar as ss
from ..routers import synthscholar as router

REVIEW = {
    "protocol": {"title": "KGs in neuroscience", "review_id": "review_local_20261015_neurokg"},
    "research_question": "Which KGs exist?",
    "timestamp": "2026-10-15T19:46:01+00:00",
    "flow": {"total_identified": 7301, "included_synthesis": 2},
    "included_articles": [
        {"pmid": "1", "title": "A", "full_text": "text", "full_text_source": "europe_pmc_oa",
         "risk_of_bias": "{'assessments': [], 'overall': 'Some concerns'}"},
        {"pmid": "2", "title": "B", "full_text": "", "risk_of_bias": {"overall": "Low"}},
    ],
    "screening_log": [
        {"pmid": "1", "stage": "title_abstract", "assessed_on": "title_abstract", "decision": "include"},
        {"pmid": "1", "stage": "full_text", "assessed_on": "full_text", "full_text_source": "europe_pmc_oa"},
        {"pmid": "2", "stage": "full_text", "assessed_on": "abstract_only"},
    ],
    "grade_assessments": {},
    "some_field_a_newer_skill_added": {"anything": True},
}
TTL = b"<https://x/r> <https://x/p> \"o\" ."


def folder(review=REVIEW, ttl=TTL, extra=()):
    return [("output/review.json", json.dumps(review).encode()), ("output/review.ttl", ttl),
            ("output/figures/fig_prisma.svg", b"<svg/>"), ("output/work/screen.py", b"x"),
            ("output/.DS_Store", b"x"), *extra]


def run(coro):
    return asyncio.run(coro)


class PlanAndReadTests(unittest.TestCase):
    def test_keeps_the_review_and_records_what_was_left_out(self):
        plan = ss.plan_import(folder(), [{"path": "work/big.jsonl", "reason": "intermediate files (work/)"},
                                         {"path": "../../etc/passwd"}, "junk"])
        self.assertEqual([f.path for f in plan.files], ["figures/fig_prisma.svg", "review.json", "review.ttl"])
        self.assertEqual(plan.skipped, [
            {"path": "work/screen.py", "reason": "intermediate files (work/)"},
            {"path": "work/big.jsonl", "reason": "intermediate files (work/)", "by": "client"}])

    def test_review_ttl_is_required(self):
        with self.assertRaisesRegex(ss.ImportError_, "review.ttl is missing"):
            ss.plan_import([("o/review.json", json.dumps(REVIEW).encode())])

    def test_reads_review_json_as_plain_json_whatever_the_skill_version(self):
        review = ss.read_review(ss.plan_import(folder()))
        self.assertEqual(ss.review_id_of(review), "review_local_20261015_neurokg")
        d = ss.detail_of(review)
        self.assertEqual([a["rob_overall"] for a in d["included_articles"]], ["Some concerns", "Low"])
        self.assertEqual(d["retrieval"], {"included": 2, "with_full_text": 1, "abstract_only": 1,
                                          "routes": {"europe_pmc_oa": 1, "abstract only": 1}})
        self.assertEqual(d["screening"]["basis_by_stage"]["full_text"], {"full_text": 1, "abstract_only": 1})
        self.assertEqual(ss.summary_of(review)["included_count"], 2)

    def test_a_review_without_its_own_id_is_refused(self):
        bad = {**REVIEW, "protocol": {"title": "t"}}
        with self.assertRaisesRegex(ss.ImportError_, "review_id"):
            ss.review_id_of(ss.read_review(ss.plan_import(folder(bad))))
        with self.assertRaisesRegex(ss.ImportError_, "not a SynthScholar review"):
            ss.read_review(ss.plan_import(folder({"x": 1})))

    def test_import_record_links_every_kept_file(self):
        plan = ss.plan_import(folder())
        graph = ss.graph_iri_for("review_local_1", "lab")
        self.assertEqual(graph, "https://brainkb.org/synthscholar/lab/reviews/review_local_1/")
        ttl = ss.import_record_ttl("review_local_1", plan, agent=URIRef("https://brainkb.org/agent/u"),
                                   imported_at="2026-10-19T00:00:00+00:00", space_slug="lab",
                                   summary={"title": "T"}, graph_iri=graph)
        g = Graph().parse(data=ttl, format="turtle")
        act = URIRef(f"{graph}import")
        used = {str(o) for o in g.objects(act, PROV.used)}
        self.assertEqual(used, {ss.file_iri(graph, f.path) for f in plan.files})
        self.assertFalse(any(isinstance(n, type(None)) for n in g.all_nodes()))
        self.assertNotIn("_:", ttl)   # no blank nodes in an append-only graph


SPACE = {"space_id": "1", "slug": "lab", "name": "Lab", "visibility": "private", "graphs": []}


class Upload:
    def __init__(self, name, content):
        self.filename, self._c = name, content

    async def read(self):
        return self._c


def ingest(*, ingest_role=True, can_add=True, can_write=True, existing=None, holder=None, registered=False,
           upload=None):
    """existing: the stored row for (space, review id), if any; holder: the space its
    graph is bound to now (None: the graph is gone)."""
    calls = {}

    async def cap(_e, c):
        return ingest_role

    async def get_space(slug):
        return SPACE if slug == "lab" else None

    async def can_add_graph(_s, _m):
        return can_add

    async def write(_s, _m):
        return can_write, "member (editor)" if can_write else "viewer only"

    async def allowed(*_a):
        return True, ""

    async def false(*_a, **_k):
        return False

    async def none(*_a, **_k):
        return None

    async def record(name):
        async def f(*a, **k):
            calls[name] = (a, k)
        return f

    async def get_row(space, rid):
        return existing

    async def space_for_graph(g):
        return holder if existing and g == existing["graph_iri"] else None

    async def delete(space, rid):
        calls["deleted"] = (space, rid)

    async def registered_(_g):
        return registered

    async def attach(sid, g):
        calls["attach"] = g
        return True

    async def save(**k):
        calls["save"] = k

    async def start(user_id, graph, files):
        calls["job"] = (user_id, graph, sorted(files))
        return "job123"

    async def noop(*a, **k):
        return None
    with patch.object(router.rbac, "has_capability", cap), patch.object(router.sp, "get_space", get_space), \
            patch.object(router, "_can_add_graph", can_add_graph), patch.object(router.sp, "can_write_space", write), \
            patch.object(router.reserved, "check_allowed", allowed), patch.object(router.ss, "get_row", get_row), \
            patch.object(router.ss, "delete_review", delete), \
            patch.object(router, "check_named_graph_exists", registered_), \
            patch.object(router.sp, "get_space_for_graph", space_for_graph), patch.object(router.sp, "attach_graph", attach), \
            patch.object(router, "insert_data_gdb_async", noop), patch.object(router.sp, "mirror_space_to_rdf", noop), \
            patch.object(router.ss, "save_review", save), patch.object(router.ss, "set_job", noop), \
            patch.object(router, "_start_ingest_job", start):
        files = [Upload(n, c) for n, c in (upload or folder())]
        out = run(router.ingest_review({"email": "u@x.org", "id": 7}, "lab", files,
                                       json.dumps([{"path": "work/a", "reason": "intermediate files (work/)"}]), None))
        return out, calls


class IngestEndpointTests(unittest.TestCase):
    def test_ingests_into_the_review_s_own_graph_as_a_job(self):
        out, calls = ingest()
        graph = "https://brainkb.org/synthscholar/lab/reviews/review_local_20261015_neurokg/"
        self.assertEqual(out["graph_iri"], graph)
        self.assertEqual(out["job_id"], "job123")
        self.assertEqual(calls["attach"], graph)
        self.assertEqual(calls["job"], ("u@x.org", graph, ["review.ttl", "synthscholar-import.ttl"]))
        self.assertEqual(calls["save"]["owner_email"], "u@x.org")
        self.assertEqual(out["left_out"], 2)    # work/screen.py uploaded + work/a reported by the client

    def test_permissions_are_the_space_s(self):
        for kwargs, code in (({"ingest_role": False}, 403), ({"can_add": False}, 403), ({"can_write": False}, 403)):
            with self.subTest(**kwargs), self.assertRaises(HTTPException) as e:
                ingest(**kwargs)
            self.assertEqual(e.exception.status_code, code)

    def test_once_per_review_per_space(self):
        row = {"space_slug": "lab", "review_id": "review_local_20261015_neurokg",
               "graph_iri": "https://brainkb.org/synthscholar/lab/reviews/review_local_20261015_neurokg/"}
        for kwargs in ({"existing": row, "holder": {"slug": "lab"}}, {"registered": True}):
            with self.subTest(**kwargs), self.assertRaises(HTTPException) as e:
                ingest(**kwargs)
            self.assertEqual(e.exception.status_code, 409)

    def test_a_leftover_record_whose_graph_is_gone_does_not_block(self):
        # the space was deleted and made again: the old row's graph is bound nowhere
        row = {"space_slug": "lab", "review_id": "review_local_20261015_neurokg",
               "graph_iri": "https://brainkb.org/synthscholar/reviews/review_local_20261015_neurokg/"}
        out, calls = ingest(existing=row, holder=None)
        self.assertEqual(calls["deleted"], ("lab", "review_local_20261015_neurokg"))
        self.assertEqual(out["job_id"], "job123")

    def test_not_an_output_directory(self):
        with self.assertRaises(HTTPException) as e:
            ingest(upload=[("x/notes.md", b"hi")])
        self.assertEqual(e.exception.status_code, 400)


Q = {
    "included_articles": [
        {"pmid": "1", "doi": "10.1/A", "title": "Graph of neurons", "year": "2006", "full_text": "t",
         "full_text_source": "europe_pmc_oa", "risk_of_bias": {"overall": "Low"}, "abstract": "abs"},
        {"pmid": "2", "doi": "", "title": "Ontology study", "year": "2021", "full_text": "", "risk_of_bias": "{'overall': 'High'}"},
    ],
    "screening_log": [
        {"pmid": "1", "title": "Graph of neurons", "stage": "title_abstract", "decision": "include", "assessed_on": "title_abstract"},
        {"pmid": "3", "title": "Unrelated", "stage": "title_abstract", "decision": "exclude", "assessed_on": "title_abstract",
         "reason": "[EC2] Automated rule: no KG term"},
        {"pmid": "4", "title": "Also unrelated", "stage": "full_text", "decision": "exclude", "assessed_on": "abstract_only",
         "reason": "[EC1] not neuroscience"},
    ],
    "evidence_spans": [
        {"text": "D2RQ was used", "claim": "construction", "paper_pmid": "1", "grounded": "True"},
        {"text": "a guess", "claim": "evaluation", "paper_pmid": "2", "grounded": "False"},
    ],
}


class QueryTests(unittest.TestCase):
    def test_studies_filters(self):
        self.assertEqual([r["pmid"] for r in ss.query_studies(Q, full_text=False)["items"]], ["2"])
        self.assertEqual([r["pmid"] for r in ss.query_studies(Q, rob="high")["items"]], ["2"])
        self.assertEqual([r["pmid"] for r in ss.query_studies(Q, year_from=2010)["items"]], ["2"])
        self.assertEqual(ss.query_studies(Q, q="neurons", source="europe")["items"][0]["read"], "full text")
        self.assertNotIn("abstract", ss.query_studies(Q)["items"][0])
        self.assertEqual(ss.query_studies(Q, with_abstract=True)["items"][0]["abstract"], "abs")

    def test_screening_counts_and_reason_codes(self):
        out = ss.query_screening(Q, decision="exclude")
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["counts"]["exclusion_reasons"], {"EC2": 1, "EC1": 1})
        self.assertEqual(ss.query_screening(Q, assessed_on="abstract_only")["items"][0]["pmid"], "4")
        self.assertEqual(ss.query_screening(Q, reason="ec2")["total"], 1)

    def test_evidence_and_paging(self):
        self.assertEqual([e["claim"] for e in ss.query_evidence(Q, grounded=False)["items"]], ["evaluation"])
        page = ss.query_evidence(Q, limit=1, offset=1)
        self.assertEqual((page["total"], len(page["items"])), (2, 1))
        self.assertEqual(ss.query_evidence(Q, limit=10_000)["limit"], ss.MAX_PAGE)

    def test_find_a_study(self):
        self.assertEqual([h["as"] for h in ss.study_in_review(Q, doi="https://doi.org/10.1/a")], ["included"])
        self.assertEqual([h["as"] for h in ss.study_in_review(Q, pmid="1")], ["included", "screened"])
        self.assertEqual(ss.study_in_review(Q, pmid="999"), [])


    def test_records_search_answers_not_questions(self):
        r = {"data_charting_rubrics": [
            {"source_id": "S-1", "title": "A", "custom_fields": {"D4 Which interfaces (SPARQL, Cypher)?": "REST only"}},
            {"source_id": "S-2", "title": "B", "custom_fields": {"D4 Which interfaces (SPARQL, Cypher)?": "SPARQL endpoint"}}]}
        self.assertEqual([x["source_id"] for x in ss.query_records(r, "charting", q="sparql")["items"]], ["S-2"])
        self.assertEqual(ss.query_records(r, "charting", study="s-1", fields="title")["items"], [{"title": "A"}])
        self.assertIn("custom_fields", ss.query_records(r, "charting")["fields"])
        with self.assertRaises(ss.ImportError_):
            ss.query_records(r, "bogus")

    def test_text_sections(self):
        r = {"synthesis_text": "S", "limitations": "L", "search_queries": ["q1"], "per_group_analysis": {"n_groups": 2}}
        self.assertEqual(ss.review_text(r, "limitations"), {"limitations": "L"})
        allt = ss.review_text(r)
        self.assertEqual((allt["synthesis"], allt["search_queries"], allt["per_group"]), ("S", ["q1"], {"n_groups": 2}))
        with self.assertRaises(ss.ImportError_):
            ss.review_text(r, "nope")



class LocateTests(unittest.TestCase):
    def locate(self, space=None, readable=("a", "b")):
        async def rows(rid):
            return [{"review_id": rid, "space_slug": x} for x in ("a", "b", "private")]

        async def get_space(slug):
            return {"space_id": slug, "slug": slug, "visibility": "public" if slug in readable else "private"}

        async def permitted(*_a):
            return True
        with patch.object(router.ss, "list_reviews", rows), patch.object(router.sp, "get_space", get_space), \
                patch.object(router.sp, "space_action_permitted", permitted):
            return run(router._locate("r1", None, space))

    def test_one_readable_copy_needs_no_space(self):
        self.assertEqual(self.locate(readable=("b",)), "b")

    def test_several_copies_name_their_spaces(self):
        with self.assertRaises(HTTPException) as e:
            self.locate()
        self.assertEqual((e.exception.status_code, e.exception.detail["spaces"]), (409, ["a", "b"]))
        self.assertEqual(self.locate(space="a"), "a")

    def test_unreadable_is_not_found(self):
        with self.assertRaises(HTTPException) as e:
            self.locate(space="private")
        self.assertEqual(e.exception.status_code, 404)

if __name__ == "__main__":
    unittest.main()
