"""GET /spaces/writable — what the ingest page offers. Offline fakes; the write
decision itself is spaces.can_write_space, the same check ingestion uses."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from ..routers import spaces as router

SPACES = {
    "lab": {"space_id": "1", "slug": "lab", "name": "Lab", "visibility": "private", "ancestors": [],
            "graphs": ["https://g/lab/"]},
    "lab-sub": {"space_id": "2", "slug": "lab-sub", "name": "Sub", "visibility": "private",
                "ancestors": [{"slug": "lab"}], "graphs": []},
    "public-atlas": {"space_id": "3", "slug": "public-atlas", "name": "Atlas", "visibility": "public",
                     "ancestors": [], "graphs": ["https://g/atlas/"]},
}


def run(coro):
    return asyncio.run(coro)


def call(*, ingest=True, admin=False, writable=("lab", "lab-sub")):
    async def cap(_e, _c):
        return ingest

    async def is_admin(_e):
        return admin

    async def visible(_e):
        return [{"slug": s} for s in SPACES]

    async def all_slugs():
        return list(SPACES)

    async def get_space(slug):
        return SPACES.get(slug)

    async def can_write(space, _e):
        return (space["slug"] in writable or admin), "member (editor)"

    async def descriptions():
        return {"https://g/lab/": "Lab data", "https://g/atlas/": "Atlas", "https://g/legacy/": "Old graph"}

    async def bound():
        return {"https://g/lab/", "https://g/atlas/"}
    with patch.object(router.rbac, "has_capability", cap), patch.object(router.rbac, "is_admin", is_admin), \
            patch.object(router.sp, "list_visible_spaces", visible), patch.object(router.sp, "all_space_slugs", all_slugs), \
            patch.object(router.sp, "get_space", get_space), patch.object(router.sp, "can_write_space", can_write), \
            patch.object(router.sp, "graph_descriptions", descriptions), patch.object(router.sp, "bound_graphs", bound):
        return run(router.writable_spaces({"email": "u@x.org"}))


class WritableSpacesTests(unittest.TestCase):
    def test_only_spaces_the_caller_can_write_with_graphs_and_tree(self):
        out = call()
        self.assertTrue(out["can_ingest"])
        self.assertEqual([s["slug"] for s in out["spaces"]], ["lab", "lab-sub"])   # public-atlas: readable, not writable
        lab, sub = out["spaces"]
        self.assertEqual(lab["graphs"], [{"iri": "https://g/lab/", "description": "Lab data"}])
        self.assertEqual(sub["parent_slug"], "lab")
        self.assertEqual(sub["graphs"], [])                                        # shown even with no graph yet
        self.assertEqual(out["unmapped_graphs"], [{"iri": "https://g/legacy/", "description": "Old graph"}])

    def test_subspace_whose_parent_is_not_writable_becomes_a_root(self):
        out = call(writable=("lab-sub",))
        self.assertEqual([(s["slug"], s["parent_slug"]) for s in out["spaces"]], [("lab-sub", None)])

    def test_admin_can_write_every_space(self):
        self.assertEqual(len(call(admin=True, writable=())["spaces"]), 3)

    def test_without_an_ingest_role_nothing_is_offered(self):
        out = call(ingest=False)
        self.assertEqual((out["can_ingest"], out["spaces"], out["unmapped_graphs"]), (False, [], []))
        self.assertIn("write-capable role", out["reason"])

    def test_route_is_matched_before_the_slug_route(self):
        paths = [r.path for r in router.router.routes if "GET" in getattr(r, "methods", set())]
        self.assertLess(paths.index("/spaces/writable"), paths.index("/spaces/{slug}"))

    def test_writable_is_not_a_usable_slug(self):
        class Body:
            slug, name, description, visibility, space_type, parent_slug = "writable", "W", None, "private", "individual", None
        with self.assertRaises(HTTPException) as e:
            run(router.create_space(Body(), {"email": "u@x.org"}))
        self.assertEqual(e.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
