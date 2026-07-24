# BrainKB Authentication & Identity — Unification Design

Status: **Phase 1 implemented** (branch `auth-unification`); Phase 2 proposed / for discussion.
Audience: BrainKB maintainers
Scope: `query_service`, `usermanagement_service`, `APItokenmanager` (Django), and downstream services (`ml_service`, `chat_service`, `brainkb_mcp`).

---

## 1. Problem statement

BrainKB today authenticates users through **two overlapping systems**:

1. **JWT / scope system** — credentials in `Web_jwtuser` (email, password, `is_active`,
   `read`/`write`/`admin` scopes). Tokens are issued/validated by `query_service`
   (`/api/token`) and the user/scope records are administered by the Django
   `APItokenmanager`. This layer answers **"can this client call this API?"**

2. **Web / RBAC system** — identity in `Web_user_profile` +
   `Web_oauth_identity` (Globus / ORCID / GitHub), with authorization in
   `Web_user_role`. Tokens are issued by `usermanagement_service`
   (`create_access_token_v2`, roles embedded) and OAuth auto-provisions users.
   This layer answers **"who is this person and what are they allowed to do?"**

Both live in the **same Postgres database** and are **joined by email**
(`query_service` RBAC already reads roles from the profile side by email). So this
is not two isolated silos — it is **one user split across two tables**:
`Web_jwtuser` (credentials) vs `Web_user_profile` (identity + roles).

That split is the real source of the inconsistencies observed in practice:

| Symptom | Cause |
|---|---|
| OAuth user cannot password-login to `query_service` | OAuth path creates a `Web_jwtuser` shell with a random password |
| Password `Web_jwtuser` has no roles → treated as public/no-role | No matching `Web_user_profile` row |
| Two token shapes | `query_service` token = scopes only; `v2` token = roles + scopes + profile |
| MCP must log in twice | One login for `query_service`, another for `usermanagement` |
| "Where do I add a user?" is ambiguous | Two admin surfaces (Django token-manager vs usermanagement) |

---

## 2. Design principles (constraints we must respect)

- **P1 — Preserve per-service token containment.** Per-service tokens were a
  deliberate security decision: a token leaked from one service must not be
  replayable against another. Any unification **must not** regress to a single
  shared bearer token that works everywhere.
- **P2 — One identity, one authorization source.** "Who is this user and what can
  they do" must be answerable exactly one way, from one source of truth.
- **P3 — OAuth is the primary onboarding path.** Globus/ORCID/GitHub provisioning
  already exists and is where new users come from; password login remains a
  supported credential, not a separate user universe.
- **P4 — Incremental, reversible migration.** No flag-day cutover; each phase must
  be shippable and independently valuable.

---

## 3. Key insight: separate the two decisions

"Merge the auth systems" conflates two independent choices. Treat them separately:

- **Decision A — Identity model.** One canonical user vs. the current
  `jwtuser`-shell + `profile` split.
- **Decision B — Token issuance.** How many issuers, what token shape, and how
  cross-service replay is prevented.

Merging identity (A) is high-value and low-risk. Collapsing tokens (B) is where the
security tradeoff lives and must be chosen deliberately.

---

## 4. Recommendation

### 4.1 Decision A — Unify the identity model (do this)

Converge on **one canonical user**, the profile, keyed by email:

- `Web_user_profile` is the **single user record**. Credentials, OAuth identities,
  roles, and API scopes all hang off it.
- `Web_jwtuser` is **demoted to a 1:1 credential record** for a profile (or removed
  entirely, with password hash + `is_active` folded into the profile). It is no
  longer a parallel "user."
- Every service resolves **identity + roles + scopes from this single source**
  (`query_service` already reads roles by email — this generalizes that pattern).
- OAuth provisioning stops creating a "shell" user; it creates/links **the** profile.
  A password can be set on the same profile later, so OAuth and password login
  address the same identity.

**Outcome:** the four-row table of symptoms in §1 disappears. There is one user,
one place roles/scopes live, one answer to "who is this."

### 4.2 Decision B — Token strategy (choose one, deliberately)

**Option B1 — Unified identity, per-service tokens (recommended first step).**
Keep each service issuing and validating its **own** token (own secret). The token
stays a thin proof-of-identity; **roles/scopes are read from the unified identity
source**, not trusted from a cross-service token. This fully preserves P1
(containment) and requires no JWKS/audience machinery. It is the smallest change
that removes the identity fragmentation.

**Option B2 — Single issuer + audience-scoped tokens (proper SSO; later).**
Make `usermanagement_service` the **auth authority** (it already issues role-bearing
v2 tokens and owns OAuth). Publish signing keys via **JWKS**; stamp every token with
an **`aud` (audience)** claim; each service accepts **only** tokens minted for its
own audience. This gives *one login* while still preventing cross-service replay —
containment is enforced by `aud` validation instead of separate secrets. This is the
clean long-term target but is a real project: JWKS rollout, `aud` enforcement in
every service, and token/user migration.

**Do not** merge into a single shared-secret token that works everywhere — it
violates P1.

### 4.3 Direction of travel

`usermanagement_service` is the newer, richer identity service (OAuth + roles + v2
tokens) and should become the **identity/auth authority**. The Django
`APItokenmanager`'s separate `jwtuser` notion is the **legacy piece to fold in**,
not the foundation to build on.

---

## 5. Phased migration plan

### Phase 0 — Freeze the contract (no behavior change)
- Document the canonical claims a BrainKB token carries: `sub` (email/profile id),
  `roles`, `scopes`, `iss`, `exp`, and (reserved for Phase 2) `aud`.
- Confirm every service reads roles/scopes from the shared source, not only from the
  token, so tokens can shrink safely later.

### Phase 1 — Unify identity (Decision A + Option B1)
1. Make `Web_user_profile` the single user; ensure every `Web_jwtuser` has a matching
   profile (backfill by email) and every profile can hold a password + `is_active`.
2. Repoint OAuth provisioning to create/link the profile (no shell user).
3. Repoint `query_service` login and RBAC to the unified record; keep its own token
   issuance/validation (containment preserved).
4. Update `brainkb_mcp` + `brainkb_skills`: one login concept, one identity; the MCP
   still obtains a per-service token where it calls each service, but from **one**
   set of user credentials.
5. Migration safety: keep `Web_jwtuser` readable during transition; dual-read, then
   deprecate.

**Ship here.** This resolves the reported inconsistencies. Stop unless SSO is wanted.

#### Phase 1 — what was actually implemented (branch `auth-unification`)

Decision A (unify identity) + Decision B Option B1 (per-service tokens), verified
live against the running stack:

- **Explicit credential→profile link.** Added `Web_jwtuser.profile_id`
  (FK → `Web_user_profile.id`, `ON DELETE SET NULL`, indexed) to the ORM model
  and as an idempotent inline migration in `usermanagement bootstrap`, plus a
  **case-insensitive email backfill** for pre-existing rows. The credential row
  is now a 1:1 record for the canonical profile, not an email-only sibling.
  *(Verified: migration applied cleanly; 2/3 existing credentials backfilled.)*
- **Single provisioning path.** New `provision_identity(...)` in
  `usermanagement/core/database.py` is the one place that ensures
  profile + linked credential + default role (`Curator`) + bootstrap-superadmin
  elevation. Idempotent; caller owns the transaction.
- **OAuth callback refactored** onto `provision_identity` — removed the ad-hoc
  `_ensure_jwt_user_shell` + default-role + bootstrap duplication; OAuth now
  sets `profile_id`. *(Verified: usermanagement boots clean, `/api/token` OK.)*
- **Password registration now provisions identity.** `query_service /api/register`
  ensures a canonical profile, assigns the default role, and links the
  credential (`_provision_profile_for_registration`, best-effort so it never
  blocks account creation). This fixes the "password user has no roles" symptom.
  *(Verified: fresh register → profile + `profile_id` link + `Curator` role.)*
- **Standardized token claims.** `query_service` tokens now carry
  `sub`/`scopes`/`user_id`/`profile_id`/`roles`/`auth_source` — identical in
  shape to usermanagement's v2 token — while still signed with query_service's
  **own** secret (containment preserved). Roles remain informational;
  authorization keeps re-reading roles from the DB via `core.rbac`.
  *(Verified: both services' `/api/token` return the same claim shape; existing
  protected endpoints still authorize.)*

Not in Phase 1 (unchanged, deliberate): per-service secrets/token isolation;
`require_admin` still trusts the token `roles` claim in usermanagement (noted for
Phase 2); no shared issuer / JWKS / `aud`.

### Phase 2 — Optional single-issuer SSO (Decision B → Option B2)
1. `usermanagement_service` becomes the sole issuer; expose **JWKS**.
2. Add `aud` to tokens; enforce per-service audience validation everywhere
   (`query_service`, `ml_service`, `chat_service`, MCP targets).
3. Migrate services from local secret validation to JWKS + `aud`.
4. Retire per-service `/api/token` login endpoints in favor of the central one;
   `APItokenmanager`'s user store is fully folded in.

---

## 6. Impact on `brainkb_mcp`

After Phase 1, the MCP no longer needs **two logins** (`query_service` +
`usermanagement`). A single `brainkb_login` authenticates one identity; admin/user
management and KG operations share it. This directly simplifies the dual-service
auth currently in `server.py` (`_um()` / separate token handling). After Phase 2,
the MCP would validate/forward a single audience-scoped token.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| User/token migration errors | Backfill by email; dual-read `jwtuser`↔`profile` before deprecating |
| Losing containment (P1) | Phase 1 keeps per-service tokens; Phase 2 uses `aud`, not shared secrets |
| Multi-service coordination | Phase 2 only; roll out JWKS+`aud` service by service behind a validation shim |
| OAuth vs password ambiguity | Single profile owns both; password becomes an attribute of the identity |
| Downstream breakage (`ml_service`, `chat_service`) | Phase 0 makes services read roles from source, so token shape can change safely |

---

## 8. Recommendation summary

- **Do now:** unify the **identity model** (§4.1) with **per-service tokens**
  (§4.2 Option B1). High value, preserves containment, small blast radius.
- **Do later, deliberately:** single-issuer **audience-scoped SSO** (§4.2 Option B2)
  when ready to operate JWKS + `aud` properly.
- **Do not:** collapse to one shared-secret token usable across all services.
