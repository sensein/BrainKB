# Design Document for Project Grants and Research Findings Microservices

## Implementation (API Endpoints)

All the responses of API are in JSON format. The entities in API context denote things such as people and projects. 


#### `GET /`
Health/root endpoint.

**Response**

- `200 OK` — JSON (empty schema)

---


### Unified Search

#### `GET /api/search`
Unified search endpoint for **skills**, **projects**, and **people** with pagination.

**Query Parameters**

- `q` (string, optional): Search query. If omitted, returns recent/default data.
- `search_type` (string, optional, default `all`): `skills | projects | people | all`
- `use_semantic` (boolean, optional, default `true`): Enable semantic expansion.
- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `20`, min `1`, max `100`)

**Response**

- `200 OK` — JSON (paginated)
- `422` — Validation error

---


#### `GET /api/search/skills`
Search for people by **skill**.

**Query Parameters**

- `skill` (string, required): Skill keyword

**Response**

- `200 OK` — `SearchResult[]`
- `422` — Validation error

---

#### `GET /api/search/projects`
Search for projects by **keyword**.

**Query Parameters**

- `keyword` (string, required): Project keyword

**Response**

- `200 OK` — `SearchResult[]`
- `422` — Validation error

---

#### `GET /api/search/people`
Search for people, i.e., PIs and Co-PIs by **name**.

**Query Parameters**

- `name` (string, required): Person name
- `orcid_id` (string, optional): Person ORCID ID which will be populated automatically.

**Response**

- `200 OK` — `SearchResult[]`
- `422` — Validation error

---

### Projects
 

#### `GET /api/projects`
Get all projects with pagination and advanced filtering.

**Query Parameters**

- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)
- `search` (string, optional): Text filter
- `fiscal_year` (int, optional): Filter by fiscal year
- `min_funding` (number, optional)
- `max_funding` (number, optional)
- `organization` (string, optional)
- `pi_name` (string, optional)
- `skill` (string, optional)
- `research_area` (string, optional)

**Response**

- `200 OK` — JSON (paginated; schema not specified in OpenAPI snippet)
- `422` — Validation error

---

### Get Project Detail

#### `GET /api/project/{project_id}`
Get detailed information about a project.

**Parameter(s)**

- `project_id` (string, required)

**Response**

- `200 OK` — `SearchResult`
- `422` — Validation error

---

### Update Project Detail 

#### `PUT /api/project/{project_id}`
Update project info (title/description) with provenance tracking.

**Parameter(s)**

- `project_id` (string, required)

**Request Body** (`UpdateProjectRequest`)

- `title` (string, optional)
- `description` (string, optional)
- `editor_name` (string, optional, default `"User"`)

**Response**

- `200 OK` — `SearchResult`
- `422` — Validation error

---

## Grant PIs/Co-PIs

Note: The term people, person are used to refer to PIs/Co-PIs.

### List People 

#### `GET /api/people`
Get all people (PIs and co-PIs) with pagination and advanced filtering.

**Query Parameters**

- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)
- `search` (string, optional)
- `skill` (string, optional)
- `research_area` (string, optional)
- `organization` (string, optional)

**Response**

- `200 OK` — JSON (paginated; schema not specified in OpenAPI snippet)
- `422` — Validation error

---

### Get Person Detail

#### `GET /api/person/{person_id}`
Get detailed information about a person.

**Parameter(s)**

- `person_id` (string, required)

**Response**

- `200 OK` — `SearchResult`
- `422` — Validation error

---

### Get Person Projects

#### `GET /api/person/{person_id}/projects`
Get all projects for a person (as main PI or co-PI).

**Parameter(s)**
- `person_id` (string, required)

**Query Parameters**
- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)

**Response**
- `200 OK` — `SearchResult[]`
- `422` — Validation error

---

### Person Evolution

#### `GET /api/person/{person_id}/evolution`
Temporal evolution of skills and research areas over time.

**Parameter(s)**

- `person_id` (string, required)

**Query Parameters**

- `entity_type` (string, optional, default `all`): `skills | research_areas | all`

**Response**

- `200 OK` — `PersonEvolution`
- `422` — Validation error

---

## Skills & Research Areas

### List Skills

#### `GET /api/skills`

Get all skills with pagination and optional year filter.

**Query Parameters**

- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)
- `search` (string, optional)
- `year` (int, optional): Temporal filter

**Response**

- `200 OK` — JSON (paginated; schema not specified in OpenAPI snippet)
- `422` — Validation error

---

### Skill Detail

#### `GET /api/skill/{skill_name}`
Get skill detail, including associated projects and people.

**Parameter(s)**

- `skill_name` (string, required)

**Response**

- `200 OK` — JSON (schema not specified in OpenAPI snippet)
- `422` — Validation error

---

### List Research Areas

#### `GET /api/research-areas`
Get all research areas with pagination and optional year filter.

**Query Parameters**

- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)
- `search` (string, optional)
- `year` (int, optional)

**Response**

- `200 OK` — JSON (paginated; schema not specified in OpenAPI snippet)
- `422` — Validation error

---

### Research Area Detail

#### `GET /api/research-area/{area_name}`
Get research area detail, including associated projects and people.

**Parameter(s)**

- `area_name` (string, required)

**Response**

- `200 OK` — JSON (schema not specified in OpenAPI snippet)
- `422` — Validation error

---

## Related Entities

### Get Related Entities

#### `GET /api/related/{entity_type}/{entity_id}`
Fetch related entities based on shared skills, projects, or research areas.

**Parameter(s)**

- `entity_type` (string, required)
- `entity_id` (string, required)

**Query Parameters**

- `limit` (int, optional, default `10`, min `1`, max `50`)

**Response**

- `200 OK` — `SearchResult[]`
- `422` — Validation error

---

## Chat  


#### `POST /api/chat`
Chat endpoint backed by retrieval-augmented generation.

**Request Body** (`ChatRequest`)
- `query` (string, required) 

**Response**
- `200 OK` — JSON  
- `422` — Validation error

---

## Graph & Network

### Entity Network

#### `GET /api/network/{entity_id}`
Get network visualization data for an entity.

**Parameter(s)**

- `entity_id` (string, required)

**Query Parameters**

- `depth` (int, optional, default `1`, min `1`, max `3`)

**Response**

- `200 OK` — `NetworkGraph`
- `422` — Validation error

---

### Knowledge Graph (Global)

#### `GET /api/knowledge-graph`
Get the full knowledge graph (nodes/edges) with a node limit.

**Query Parameters**

- `limit` (int, optional, default `100`, min `10`, max `500`)

**Response**

- `200 OK` — `NetworkGraph`
- `422` — Validation error

---

## Sync & Stats

### Sync Data (Public)

#### `POST /api/sync`
Sync data from NIH Reporter API.

**Query Parameters**

- `limit` (int, optional, default `10`, min `1`, max `100`)

**Request Body**

- `project_ids` (string[] | null)

**Response**

- `200 OK` — JSON  
- `422` — Validation error

---

### Graph Stats

#### `GET /api/stats`
Get knowledge graph statistics.

**Response**
- `200 OK` — JSON (schema not specified in OpenAPI snippet)

---

# Admin Endpoints
 

## Admin Sync

### Start Admin Sync (Async)

#### `POST /api/admin/sync`

Starts a background job to sync projects from NIH.

**Request Body** (`SyncRequest`)

- `project_ids` (string[] | null)
- `limit` (int | null, default `10`)
- `fiscal_years` (int[] | null)
- `organization` (string | null)
- `keywords` (string[] | null)

**Response**

- `200 OK` — JSON (returns a job id; schema not specified in snippet)
- `422` — Validation error

---

### Check Sync Status

#### `GET /api/admin/sync/status/{job_id}`
Get status of a sync operation.

**Parameter(s)**

- `job_id` (string, required)

**Response**

- `200 OK` — JSON
- `422` — Validation error

---

## Admin Data Access

### Admin List Projects

#### `GET /api/admin/data/projects`
Admin list projects with filtering and pagination.

**Query Parameters**

- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)
- `search` (string, optional)
- `fiscal_year` (int, optional)

**Response**

- `200 OK` — `PaginatedResponse`
- `422` — Validation error

---

### Debug Project

#### `GET /api/admin/debug/project/{project_id}`
Check what’s stored for a project in the knowledge graph.

**Parameter(s)**

- `project_id` (string, required)

**Response**
- `200 OK` — JSON
- `422` — Validation error

---

### Admin List People

#### `GET /api/admin/data/people`
Admin list people with filtering and pagination.

**Query Parameters**

- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)
- `search` (string, optional)

**Response**

- `200 OK` — `PaginatedResponse`
- `422` — Validation error

---

### Admin List Skills

#### `GET /api/admin/data/skills`
Admin list skills with filtering and pagination.

**Query Parameters**

- `page` (int, optional, default `1`, min `1`)
- `page_size` (int, optional, default `50`, min `1`, max `200`)
- `search` (string, optional)

**Response**

- `200 OK` — `PaginatedResponse`
- `422` — Validation error

---

## Admin Delete

### Delete Entities

#### `POST /api/admin/delete`

Delete entities from the knowledge graph.

**Request Body** (`DeleteRequest`)

- `entity_type` (string, required)
- `entity_id` (string | null)

**Response**

- `200 OK` — JSON
- `422` — Validation error

---

## Admin Pull All NIH (Async)

### Start Pull-All Job

#### `POST /api/admin/pull-all-nih`

Starts a background job to fetch projects from NIH and skip already-stored projects.

**Request Body**

- `fiscal_years` (int[] | null): If null, pulls all projects
- `batch_size` (int, default `500`, min `100`, max `1000`)

**Response**

- `200 OK` — JSON (returns job id; schema not specified)
- `422` — Validation error

---

### Check Pull-All Status

#### `GET /api/admin/pull-all-nih/status/{job_id}`
Get status of pull operation.

**Parameter(s)**

- `job_id` (string, required)

**Response**

- `200 OK` — JSON
- `422` — Validation error

---

## Admin Import / Export

### Export Knowledge Graph

#### `GET /api/admin/export`
Export graph data.

**Query Parameters**

- `format` (string, optional, default `turtle`): `turtle | xml | json-ld`

**Response**

- `200 OK` — JSON (or file-like payload depending on implementation)
- `422` — Validation error

---

### Import Knowledge Graph

#### `POST /api/admin/import`
Import graph data. This avoids re-fetching of data and KG construction. 

**Query Parameters**

- `format` (string, optional, default `turtle`): `turtle | xml | json-ld`

**Request Body** (`ImportRequest`)

- `data` (string, required)

**Response**
- `200 OK` — JSON
- `422` — Validation error

---

## Admin Enrichment (Async)

### Enrich Author(s)

#### `POST /api/admin/enrich-author`
Enrich author(s) with publications and ORCID. Returns a job id.

**Request Body** (`EnrichAuthorRequest`)

- `person_id` (string | null)
- `person_name` (string | null)
- `project_id` (string | null)
- `fetch_publications` (bool, default `true`)
- `fetch_orcid` (bool, default `true`)
- `publication_limit` (int, default `20`)
- `skip_enriched` (bool, default `true`)

**Response**

- `200 OK` — JSON (job id)
- `422` — Validation error

---

### Enrich Author Status

#### `GET /api/admin/enrich-author/status/{job_id}`
Check status of an enrichment job.

**Parameter(s)**

- `job_id` (string, required)

**Response**

- `200 OK` — JSON
- `422` — Validation error

---

### Debug API Keys

#### `GET /api/admin/debug/api-keys`

This endpoint is to check API key configuration.

**Response**

- `200 OK` — JSON
- `422` — Validation error

---

### Autocomplete People

#### `GET /api/admin/autocomplete/people`
Provides lightweight, prefix-based autocomplete suggestions for person (PI/co-PI) names stored in the knowledge graph.

This endpoint performs a case-insensitive substring match against `foaf:name` values for all entities of type `foaf:Person`. It returns a limited list of matching people formatted for UI autocomplete components.

**Query Parameters**

- `q` (string, required, min length `1`)
- `limit` (int, optional, default `10`, min `1`, max `50`)

**Response**

- `200 OK` — JSON
- `422` — Validation error

---

### Autocomplete Projects

#### `GET /api/admin/autocomplete/projects`
Autocomplete for project IDs and titles. We will use the our schema -- to be developed. 

**Query Parameters**

- `q` (string, required, min length `1`)
- `limit` (int, optional, default `10`, min `1`, max `50`)

**Response**

- `200 OK` — JSON
- `422` — Validation error

---

### Enrich All Authors (Bulk, Async)

#### `POST /api/admin/enrich-all-authors`

Bulk enrichment for all authors, i.e., enrich with more information like skills and research areas by extracting the information.

**Query Parameters**

- `limit` (int | null, optional): Limit number of authors enriched
- `skip_enriched` (bool, default `true`)
- `fetch_publications` (bool, default `true`)
- `fetch_orcid` (bool, default `true`)
- `publication_limit` (int, default `20`, min `1`, max `100`)

**Response**

- `200 OK` — JSON (job id)
- `422` — Validation error

---