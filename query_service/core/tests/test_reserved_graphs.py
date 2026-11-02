"""Reserved named graphs. Offline: the reservation lookup and roles are faked; the
tests pin who may register/bind what, and that both entry points enforce it."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from .. import reserved_graphs as rg
from ..routers import spaces as router

ADMIN, USER = "admin@example.org", "someone@example.org"


def run(coro):
    return asyncio.run(coro)


def fake_find(reservation):
    async def find(_iri):
        return reservation
    return find


async def is_admin(email):
    return email == ADMIN


class CheckAllowedTests(unittest.TestCase):
    def allowed(self, reservation, email, space_id=None, iri="https://brainkb.org/graph/allen/", ancestors=None):
        async def up(sid):                      # the space and the spaces above it
            return [sid] + list(ancestors or [])
        with patch.object(rg, "find", fake_find(reservation)), patch.object(rg.rbac, "is_admin", is_admin), \
                patch("core.spaces.ancestor_ids", up):
            return run(rg.check_allowed(iri, email, space_id))

    def test_unreserved_is_open(self):
        self.assertEqual(self.allowed(None, USER), (True, ""))

    def test_system_graphs_are_closed_to_everyone_even_admins(self):
        for iri in ("https://brainkb.org/metadata/named-graph", "https://brainkb.org/provenance/delta/job-1"):
            ok, why = run(rg.check_allowed(iri, ADMIN))     # real find(): system prefixes need no DB
            self.assertFalse(ok)
            self.assertIn("system graph", why)

    def test_reserved_graph_admin_only(self):
        res = {"system": False, "space_id": None, "space_slug": None, "reason": "Allen taxonomies"}
        self.assertTrue(self.allowed(res, ADMIN)[0])
        ok, why = self.allowed(res, USER)
        self.assertFalse(ok)
        self.assertIn("Allen taxonomies", why)

    def test_reserved_for_a_space_opens_it_to_that_space_only(self):
        res = {"system": False, "space_id": "sp-bican", "space_slug": "bican-resources", "reason": None}
        self.assertTrue(self.allowed(res, USER, space_id="sp-bican")[0])
        ok, why = self.allowed(res, USER, space_id="sp-other")
        self.assertFalse(ok)
        self.assertIn("bican-resources", why)
        self.assertFalse(self.allowed(res, USER, space_id=None)[0])   # standalone registration
        self.assertTrue(self.allowed(res, USER, space_id="sp-bican-sub", ancestors=["sp-bican"])[0])  # its subspace


class AddValidationTests(unittest.TestCase):
    def test_rejects_bad_input_before_touching_the_db(self):
        with self.assertRaises(ValueError):
            run(rg.add("https://brainkb.org/graph/x/", "regex", None, ADMIN))
        with self.assertRaises(ValueError):
            run(rg.add("ftp://example.org/x", "exact", None, ADMIN))
        for iri in ("https://brainkb.org/metadata/anything", "https://brainkb.org/"):
            with self.assertRaises(rg.ReservationConflict):            # inside, or above, a system prefix
                run(rg.add(iri, "prefix", None, ADMIN))

    def test_normalize_matches_registration(self):
        self.assertEqual(rg.normalize("https://brainkb.org/graph/x"), "https://brainkb.org/graph/x/")
        self.assertEqual(rg.normalize("https://brainkb.org/graph/x/"), "https://brainkb.org/graph/x/")


class EnforcementTests(unittest.TestCase):
    """POST /spaces/{slug}/graphs refuses a reserved graph before binding anything."""

    def test_binding_a_reserved_graph_is_403_and_nothing_is_bound(self):
        attached = []
        space = {"space_id": "sp-1", "slug": "lab", "owner": USER}

        async def get_space(_slug):
            return space

        async def can_manage(_space, _email):
            return True

        async def member_role(*_a):
            return "owner"

        async def attach(*a):
            attached.append(a)

        async def deny(_iri, _email, _space_id):
            return False, "'https://brainkb.org/graph/allen/' is reserved"

        class Body:
            named_graph_url = "https://brainkb.org/graph/allen"
            description = "x"
        with patch.object(router.sp, "get_space", get_space), patch.object(router, "_can_manage", can_manage), \
                patch.object(router.sp, "member_role", member_role), patch.object(router.sp, "attach_graph", attach), \
                patch.object(router.reserved, "check_allowed", deny):
            with self.assertRaises(HTTPException) as e:
                run(router.add_graph("lab", Body(), {"email": USER, "id": 2}))
        self.assertEqual(e.exception.status_code, 403)
        self.assertEqual(attached, [])

    def test_admin_endpoints_require_admin(self):
        async def no(_e):
            return False
        with patch.object(router.rbac, "is_admin", no):
            for call in (lambda: router.list_reserved_graphs({"email": USER}),
                         lambda: router.remove_reserved_graph(1, {"email": USER})):
                with self.assertRaises(HTTPException) as e:
                    run(call())
                self.assertEqual(e.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
