"""Visibility down the space tree: a public space makes all its subspaces public; a
subspace of a public space can't be private on its own; under a private space each
subspace chooses. Offline fakes; the cascade itself is one recursive UPDATE in
spaces.set_visibility."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from .. import spaces as sp
from ..routers import spaces as router

PUB = {"space_id": "p", "slug": "atlas", "name": "Atlas", "visibility": "public", "space_type": "team", "ancestors": []}
PRIV = {"space_id": "q", "slug": "lab", "name": "Lab", "visibility": "private", "space_type": "team", "ancestors": []}
UNDER_PUB = {"space_id": "a", "slug": "atlas-sub", "name": "S", "visibility": "public", "space_type": "team",
             "ancestors": [{"slug": "atlas", "visibility": "public"}]}
UNDER_PRIV = {"space_id": "b", "slug": "lab-sub", "name": "S", "visibility": "public", "space_type": "team",
              "ancestors": [{"slug": "lab", "visibility": "private"}]}
STORE = {s["slug"]: s for s in (PUB, PRIV, UNDER_PUB, UNDER_PRIV)}


def run(coro):
    return asyncio.run(coro)


class Vis:
    def __init__(self, v):
        self.visibility = v


class Body:
    def __init__(self, parent, visibility="private"):
        self.slug, self.name, self.description = "new-sub", "New", None
        self.visibility, self.space_type, self.parent_slug = visibility, "individual", parent


def patched(fn):
    calls = {"set": [], "mirrored": [], "created": []}

    async def get_space(slug):
        return dict(STORE[slug]) if slug in STORE else None

    async def yes(*_a):
        return True

    async def set_vis(slug, v):
        calls["set"].append((slug, v))
        return [slug, f"{slug}-child"] if v == "public" else [slug]

    async def mirror(s):
        calls["mirrored"].append(s["slug"])

    async def create(*args):
        calls["created"].append(args)
        return {"slug": args[0], "visibility": args[4]}
    with patch.object(router.sp, "get_space", get_space), patch.object(router, "_can_manage", yes), \
            patch.object(router.rbac, "has_capability", yes), patch.object(router.sp, "set_visibility", set_vis), \
            patch.object(router.sp, "mirror_space_to_rdf", mirror), patch.object(router.sp, "create_space", create):
        out = run(fn())
    return out, calls


class SpaceVisibilityTests(unittest.TestCase):
    def test_public_ancestor(self):
        self.assertEqual(sp.public_ancestor(UNDER_PUB), "atlas")
        self.assertIsNone(sp.public_ancestor(UNDER_PRIV))
        self.assertIsNone(sp.public_ancestor(PUB))

    def test_making_a_space_public_reports_its_subspaces_too(self):
        out, calls = patched(lambda: router.set_visibility("lab", Vis("public"), {"email": "o@x.org"}))
        self.assertEqual(out["visibility_changed"], ["lab", "lab-child"])

    def test_a_subspace_of_a_public_space_cannot_go_private(self):
        with self.assertRaises(HTTPException) as e:
            patched(lambda: router.set_visibility("atlas-sub", Vis("private"), {"email": "o@x.org"}))
        self.assertEqual(e.exception.status_code, 409)

    def test_under_a_private_space_a_subspace_chooses(self):
        _, calls = patched(lambda: router.set_visibility("lab-sub", Vis("private"), {"email": "o@x.org"}))
        self.assertEqual(calls["set"], [("lab-sub", "private")])

    def test_a_new_subspace_of_a_public_space_is_public(self):
        out, _ = patched(lambda: router.create_space(Body("atlas", "private"), {"email": "o@x.org"}))
        self.assertEqual(out["visibility"], "public")
        out, _ = patched(lambda: router.create_space(Body("lab", "private"), {"email": "o@x.org"}))
        self.assertEqual(out["visibility"], "private")


if __name__ == "__main__":
    unittest.main()
