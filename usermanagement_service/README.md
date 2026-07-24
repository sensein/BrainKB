# BrainKB User Management Service

A modern, scalable user management service for neuroscience knowledge bases built with FastAPI, SQLAlchemy ORM, and PostgreSQL.

## 🚀 Features

- **🔐 JWT Authentication** - Secure token-based authentication
- **👥 User Profiles** - Comprehensive user profile management
- **📊 Activity Tracking** - Automatic logging of user activities
- **🎯 Contribution Management** - Track and manage user contributions
- **🏷️ Role-Based Access Control** - Multiple user roles and permissions
- **📈 Analytics** - User statistics and activity analytics
- **🔒 Security** - Input validation, SQL injection protection, XSS prevention

## 🏗️ Architecture

### Tech Stack
- **FastAPI** - Modern, fast web framework
- **SQLAlchemy ORM** - Type-safe database operations
- **PostgreSQL** - Robust relational database
- **Pydantic** - Data validation and serialization
- **JWT** - Secure authentication

### Key Components
```
core/
├── models/
│   ├── user.py                    # Pydantic models for API
│   └── database_models.py         # SQLAlchemy ORM models
├── user_database.py               # User-specific database operations
├── routers/
│   ├── user_management.py         # User management endpoints
│   └── jwt_auth.py               # Authentication endpoints
├── security.py                    # JWT and password utilities
├── configuration.py               # Environment configuration
└── main.py                       # FastAPI application
```

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- PostgreSQL 12+

### Installation

1. **Clone and install**
```bash
git clone <repository-url>
cd usermanagement_service
pip install -r requirements.txt
```

2. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your database and JWT settings
```

3. **Start the service**
```bash
uvicorn core.main:app --reload
```

### Docker Setup
```bash
# Start with Docker Compose
docker-compose -f docker-compose-postgres.yml up -d

# Or build and run
docker build -t brainkb-user-service .
docker run -p 8000:8000 brainkb-user-service
```

## 📚 API Documentation

Once running, visit:
- **Interactive API Docs**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc

### Key Endpoints

End-user sign-up happens automatically on first OAuth callback (see
*Configuring the Admin role* below) — there is **no self-registration**; users are
created on first OAuth login. Password login is at `/api/login` (`/api/token` is a
deprecated alias) for accounts that already exist.

- `POST /api/login` - Legacy HS256 password login (mints a v2 JWT); `/api/token` = deprecated alias
- `GET  /api/auth/providers` - List OAuth providers + which are configured
- `GET  /api/auth/{provider}/login` - Start OAuth flow (returns `authorize_url`)
- `GET  /api/auth/{provider}/callback` - OAuth callback; auto-creates profile + linked credential + default `Curator` role on first sign-in

**Single sign-on (RS256 + JWKS)** — usermanagement is the single token issuer.
One login mints a short-lived **refresh** token; clients **exchange** it for narrow
per-service **access** tokens (`aud=<service>`), which each service verifies via
the published JWKS. A token minted for one service can't be replayed against
another. See `../query_service/AUTH_UNIFICATION.md`.

- `GET  /.well-known/jwks.json` - Public keys for verifying SSO tokens
- `POST /api/auth/login` - `{email, password}` → refresh token (aud `brainkb-auth`)
- `POST /api/auth/exchange` - Bearer refresh + `{audience}` → per-service access token
- `POST /api/auth/cli/start` - `{provider}` → authorize URL for a CLI/skill OAuth
  login (paste-code). The provider callback shows a short one-time code (minimal
  page, no SPA) instead of redirecting to the frontend.
- `POST /api/auth/cli/exchange` - `{code}` → SSO refresh token (single-use). Lets
  the MCP/skill complete a Globus/ORCID/GitHub login without the web UI.

The signing key is auto-provisioned at container start (persisted on the
`./secrets` volume) unless `USERMANAGEMENT_JWT_PRIVATE_KEY_PEM`/`_FILE` is set.
This service also accepts SSO access tokens minted for `aud=usermanagement` on its
own protected routes (alongside the legacy v2 token).
- `GET  /api/users/profile` - Get user profile
- `POST /api/users/profile` - Create/update profile
- `GET /api/users/activities` - Get user activities
- `POST /api/users/contributions` - Create contribution
- `GET /api/users/roles` - Get user roles
- `POST /api/users/roles` - Assign role

### Admin: roles, permissions & moderation (`/api/admin`, Admin/SuperAdmin)

- `GET/POST /api/admin/roles`, `PUT /api/admin/roles/{id}` — list/create custom
  roles/groups (e.g. `uk_collaborator`).
- `GET/POST /api/admin/permissions` — list all permissions and **add new ones**
  (`{name, resource, action, description}`); attach to roles via
  `PUT /api/admin/roles/{id}/permissions`.
- `POST /api/admin/users/{profile_id}/roles`, `DELETE .../roles/{role}` — assign/
  remove a user's role. **Assigning/removing the `Admin` role is SuperAdmin-only**
  (hierarchy: SuperAdmin > Admin); the `SuperAdmin` role is protected.
- `POST /api/admin/users/{profile_id}/ban` + `DELETE …/ban` — ban/unban. **Banning
  an Admin is SuperAdmin-only.** Banning is the removal mechanism.
- `POST /api/admin/users/{activate,deactivate}` — toggle login access.

**No hard deletion.** `DELETE /api/admin/users/{id}` is disabled (returns `405`) —
accounts are **banned** (reversible, preserves provenance/audit history), never
deleted.

## 🎯 User Roles

### Content Contribution
- **Submitter** - Upload primary content
- **Annotator** - Add metadata and tags
- **Mapper** - Align concepts to ontologies
- **Curator** - Review and edit submissions

### Quality Control
- **Reviewer** - Evaluate content quality
- **Validator** - Check schema compliance
- **Conflict Resolver** - Handle contradictions

### Knowledge Management
- **Knowledge Contributor** - Add domain knowledge
- **Evidence Tracer** - Link supporting evidence
- **Provenance Tracker** - Track source metadata

### Community Management
- **Moderator** - Oversee discussions
- **Ambassador** - Community outreach

## 👑 Configuring the Admin role

The `Admin` role is special — only admins can assign roles to other users via
`POST /api/admin/users/{profile_id}/roles`. That creates a chicken-and-egg
problem for the *first* admin, solved by env-var bootstrap.

### 1. First admin (bootstrap, env-var)

In the backend's `.env` (project root, e.g. `BrainKB/.env`):

```env
USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS=you@example.com,colleague@example.com
```

Comma-separated; whitespace around emails is trimmed. Restart the service —
on every startup `core/bootstrap.py::promote_bootstrap_superadmins()` runs and:

1. **Email already has a `UserProfile`** → assigns both `Admin` and
   `SuperAdmin` (idempotent, safe to re-run).
2. **Email has not signed in yet** → no profile to update, but the
   `require_admin` dependency honors the env allowlist as a fallback. The
   user can sign in via OAuth, which creates their profile, and the next
   restart persists the roles.

Bootstrap also seeds baseline roles and grants both `Admin` and `SuperAdmin`
every permission in the registry, so a fresh admin has full access
immediately. The `SuperAdmin` role is protected — accounts holding it cannot
be banned, deleted, or have that role stripped via the admin UI/API.

Verify:

```bash
# After the user has signed in, with their JWT in $TOKEN:
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8004/api/users/me | jq .roles
# → ["Admin", ...]
```

### 2. Subsequent admins (UI)

Once at least one admin exists, role management happens through the BrainKB
UI's admin surface:

1. Sign in as an existing admin and visit `/admin/users`.
2. Search by name, email, or ORCID.
3. In the *Roles* column, pick **Admin** from the *+ add role* dropdown.

Demote: click the `Admin ✕` chip on the user's row.

Programmatic equivalent (any admin's JWT):

```bash
curl -X POST http://localhost:8004/api/admin/users/{profile_id}/roles \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "Admin", "is_active": true}'
```

See `UI_INTEGRATION.md` for the full set of admin endpoints.

## 📊 Database Models

### Core Models
- **User** - Authentication and basic info
- **UserProfile** - Detailed profile information
- **UserActivity** - Activity tracking and logging
- **UserContribution** - Content contribution management
- **UserRole** - Role assignments and permissions

### Automatic Setup
The service automatically creates all database tables on startup using SQLAlchemy ORM models. No manual migration required!

## 🔧 Development

### Adding Features
1. **Add models** in `core/models/database_models.py`
2. **Add repository methods** in `core/user_database.py`
3. **Add API endpoints** in `core/routers/user_management.py`
4. **Add Pydantic models** in `core/models/user.py`

### Testing
```bash
pytest
pytest --cov=core
```

## 📈 Performance

- **Connection Pooling** - Efficient database connections
- **Optimized Indexes** - Fast query performance
- **Async Operations** - Non-blocking operations
- **Type Safety** - Catch errors at development time

## 🔒 Security

- **JWT Authentication** - Secure token-based auth
- **Password Hashing** - bcrypt for password security
- **Input Validation** - Pydantic model validation
- **SQL Injection Protection** - ORM prevents injection
- **Role-Based Access** - Granular permissions

## 📞 Support

- **Email**: tekraj@mit.edu
- **Issues**: GitHub Issues
- **Documentation**: `/docs` endpoint when running

---

**Built for scalable neuroscience knowledge base user management!** 🧠🔬