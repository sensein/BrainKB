"""Subspaces: endpoint rules (creation rights, what the caller is shown, deletion
order). Offline: the space store and roles are fakes. Inheritance itself is SQL
(member_role / the space_effective_members view) and is exercised against Postgres."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from .. import spaces as sp
from ..routers import spaces as router

LAB = {"space_id": "s-lab", "slug": "lab", "name": "Lab", "visibility": "private", "space_type": "team",
       "owner": "alice@x.org", "members": [], "graphs": [], "ancestors": [],
       "subspaces": [{"slug": "lab-sub", "name": "Sub", "visibility": "private"},
                     {"slug": "lab-release", "name": "Release", "visibility": "public"}]}
SUB = {"space_id": "s-sub", "slug": "lab-sub", "name": "Sub", "visibility": "private", "space_type": "team",
       "owner": "bob@x.org", "members": [], "graphs": ["https://g/sub/"],
       "ancestors": [{"slug": "lab", "name": "Lab", "visibility": "private"}], "subspaces": []}
RELEASE = dict(SUB, space_id="s-rel", slug="lab-release", name="Release", visibility="public", graphs=[])
STORE = {"lab": LAB, "lab-sub": SUB, "lab-release": RELEASE}


def run(coro):
    return asyncio.run(coro)


class Body:
    def __init__(self, **kw):
        self.slug, self.name, self.description = kw.get("slug", "lab-new"), "New", None
        self.visibility, self.space_type, self.parent_slug = "private", kw.get("space_type", "individual"), kw.get("parent_slug")


class CreateSubspaceTests(unittest.TestCase):
    def create(self, *, can_manage, parent="lab", space_type="individual"):
        made = []

        async def get_space(slug):
            return STORE.get(slug)

        async def manage(_s, _e):
            return can_manage

        async def cap(_e, _c):
            return True

        async def create(*args):
            made.append(args)
            return {"slug": args[0]}

        async def mirror(_s):
            return True
        with patch.object(router.sp, "get_space", get_space), patch.object(router, "_can_manage", manage), \
                patch.object(router.rbac, "has_capability", cap), patch.object(router.sp, "create_space", create), \
                patch.object(router.sp, "mirror_space_to_rdf", mirror):
            out = run(router.create_space(Body(parent_slug=parent, space_type=space_type), {"email": "bob@x.org"}))
        return out, made

    def test_parent_manager_creates_a_subspace_of_the_parents_type(self):
        _, made = self.create(can_manage=True, space_type="individual")
        args = made[0]
        self.assertEqual(args[5], "team")          # takes the parent's space type
        self.assertEqual(args[6], "s-lab")         # parent_space_id

    def test_non_manager_cannot_create_a_subspace(self):
        with self.assertRaises(HTTPException) as e:
            self.create(can_manage=False)
        self.assertEqual(e.exception.status_code, 403)

    def test_missing_parent_is_404(self):
        with self.assertRaises(HTTPException) as e:
            self.create(can_manage=True, parent="nope")
        self.assertEqual(e.exception.status_code, 404)


class VisibilityTests(unittest.TestCase):
    def test_private_parent_is_not_named_to_outsiders(self):
        async def visible(_m):
            return {"lab-sub", "lab-release"}      # can see the subspaces, not the private parent
        with patch.object(router, "_visible_slugs", visible):
            out = run(router._with_visible_hierarchy(dict(SUB), "bob@x.org"))
        self.assertEqual((out["ancestors"], out["parent_slug"]), ([], None))
        self.assertNotIn("parent_space_id", out)

    def test_members_see_parent_and_only_visible_subspaces(self):
        async def visible(_m):
            return {"lab", "lab-release"}
        with patch.object(router, "_visible_slugs", visible):
            out = run(router._with_visible_hierarchy(dict(LAB), "carol@x.org"))
        self.assertEqual([c["slug"] for c in out["subspaces"]], ["lab-release"])

    def test_tree_nests_visible_subspaces_with_inherited_roles(self):
        async def get_space(slug):
            return STORE.get(slug)

        async def visible(_m):
            return {"lab", "lab-sub", "lab-release"}

        async def role(space_id, _m):
            return ("owner", False) if space_id == "s-lab" else ("owner", True)
        with patch.object(router.sp, "get_space", get_space), patch.object(router, "_visible_slugs", visible), \
                patch.object(router.sp, "member_role_detail", role):
            tree = run(router.space_tree("lab", {"email": "alice@x.org"}))
        self.assertEqual([c["slug"] for c in tree["subspaces"]], ["lab-sub", "lab-release"])
        self.assertTrue(all(c["role_inherited"] for c in tree["subspaces"]))
        self.assertEqual(tree["subspaces"][0]["graphs"], 1)

    def test_tree_of_a_space_the_caller_cannot_see_is_403(self):
        async def get_space(slug):
            return STORE.get(slug)

        async def visible(_m):
            return {"lab-release"}
        with patch.object(router.sp, "get_space", get_space), patch.object(router, "_visible_slugs", visible):
            with self.assertRaises(HTTPException) as e:
                run(router.space_tree("lab", None))
        self.assertEqual(e.exception.status_code, 403)


class DeletionOrderTests(unittest.TestCase):
    def test_space_with_subspaces_is_not_deleted(self):
        with self.assertRaises(sp.SpaceHasSubspaces) as e:
            run(sp.delete_space(dict(LAB), "admin@x.org"))
        self.assertEqual(e.exception.slugs, ["lab-sub", "lab-release"])

    def test_deleting_a_space_deletes_its_subspaces_first(self):
        order, reviews = [], []
        tree = {"lab": dict(LAB, subspaces=[]), "lab-sub": dict(SUB), "lab-release": dict(RELEASE),
                "lab-sub-deep": dict(SUB, space_id="s-deep", slug="lab-sub-deep")}

        async def yes(_e):
            return True

        async def get_space(slug):
            return tree.get(slug) if slug not in order else None

        async def descendants(_id):
            return ["lab-sub-deep", "lab-release", "lab-sub"]     # deepest first

        async def delete(space_, by):
            order.append(space_["slug"])
            return {"deleted": True, "slug": space_["slug"], "dropped_graphs": space_.get("graphs") or [],
                    "dropped_delta_graphs": [], "members_removed": 1}

        async def remove(slugs):
            reviews.extend(slugs)
            return len(slugs)
        with patch.object(router.rbac, "is_superadmin", yes), patch.object(router.sp, "get_space", get_space), \
                patch.object(sp, "get_space", get_space), patch.object(router.sp, "descendant_slugs", descendants), \
                patch.object(router.sp, "delete_space", delete), patch.object(router, "_remove_synthscholar", remove):
            out = run(router.delete_space("lab", {"email": "admin@x.org"}, "lab"))
        self.assertEqual(order, ["lab-sub-deep", "lab-release", "lab-sub", "lab"])
        self.assertEqual(out["subspaces_deleted"], ["lab-sub-deep", "lab-release", "lab-sub"])
        self.assertEqual(sorted(reviews), sorted(order))
        self.assertEqual(out["members_removed"], 4)

    def test_a_failure_part_way_says_what_was_deleted(self):
        done = []

        async def yes(_e):
            return True

        async def get_space(slug):
            return dict(SUB, slug=slug, space_id=slug) if slug not in done else None

        async def descendants(_id):
            return ["lab-a", "lab-b"]

        async def delete(space_, by):
            if space_["slug"] == "lab-b":
                raise sp.SpaceDeletionError("SPARQL update failed (HTTP 500)")
            done.append(space_["slug"])
            return {"deleted": True, "slug": space_["slug"]}

        async def remove(slugs):
            return 0
        with patch.object(router.rbac, "is_superadmin", yes), patch.object(router.sp, "get_space", get_space), \
                patch.object(sp, "get_space", get_space), patch.object(router.sp, "descendant_slugs", descendants), \
                patch.object(router.sp, "delete_space", delete), patch.object(router, "_remove_synthscholar", remove):
            with self.assertRaises(HTTPException) as e:
                run(router.delete_space("lab", {"email": "admin@x.org"}, "lab"))
        self.assertEqual(e.exception.status_code, 502)
        self.assertIn("Already deleted: lab-a", e.exception.detail)



if __name__ == "__main__":
    unittest.main()
