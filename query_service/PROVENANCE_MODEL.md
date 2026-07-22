# BrainKB Provenance Model (PROV-O in Oxigraph)

Status: implemented on branch `improve-ingestion-query-service`.

BrainKB stores knowledge in Oxigraph (a triplestore), so provenance is tracked
**natively as W3C PROV-O triples in the graph database** and queried with SPARQL —
not in a relational side-table. Postgres continues to hold job *execution state*
(`jobs`, `job_results`, `job_processing_log`); Oxigraph is the provenance
*source of truth*.

This replaces the previous approach, which embedded PROV triples directly into
each uploaded file's domain data via `attach_provenance()`. That polluted domain
graphs, generated per-file provenance with random UUIDs unlinked to the job, and
forced a full parse+re-serialize of every file (a memory/latency bottleneck).

## Where provenance lives

All provenance is written to one dedicated named graph:

```
https://brainkb.org/provenance/
```

Domain data uploaded during ingestion is **no longer modified** — files land in
their target named graph exactly as provided.

## Vocabulary

| Prefix    | IRI                                            |
|-----------|------------------------------------------------|
| `prov`    | `http://www.w3.org/ns/prov#`                   |
| `dcterms` | `http://purl.org/dc/terms/`                    |
| `xsd`     | `http://www.w3.org/2001/XMLSchema#`            |
| `brainkb` | `https://brainkb.org/vocab/` (custom terms)    |

Instance IRIs are minted under `https://brainkb.org/prov/`:

- Activity: `…/prov/activity/{job_id}`
- Ingested bundle (entity): `…/prov/bundle/{job_id}`
- Per-file entity: `…/prov/file/{job_id}/{urlencoded filename}`
- Agent: `…/prov/agent/{urlencoded id}`; system agent: `…/prov/agent/system`

## Tracked activities

Every mutating action becomes a `prov:Activity` with a typed agent.

### 1. Ingestion — `brainkb:IngestionActivity` (agent: user)

Written when a job reaches a terminal state (`done` / `error` / partial).

```turtle
GRAPH <https://brainkb.org/provenance/> {
  <…/prov/activity/{job_id}>
      a prov:Activity, brainkb:IngestionActivity ;
      prov:startedAtTime "…"^^xsd:dateTime ;
      prov:endedAtTime   "…"^^xsd:dateTime ;
      prov:wasAssociatedWith <…/prov/agent/{user}> ;
      brainkb:targetGraph <{named_graph_iri}> ;
      brainkb:jobStatus "done" ;
      brainkb:totalFiles 20 ;
      brainkb:successCount 19 ;
      brainkb:failCount 1 .

  <…/prov/bundle/{job_id}>
      a prov:Entity ;
      prov:wasGeneratedBy <…/prov/activity/{job_id}> ;
      prov:wasAttributedTo <…/prov/agent/{user}> ;
      prov:generatedAtTime "…"^^xsd:dateTime ;
      dcterms:isPartOf <{named_graph_iri}> .

  <…/prov/file/{job_id}/data_009.ttl>
      a prov:Entity ;
      prov:wasGeneratedBy <…/prov/activity/{job_id}> ;
      dcterms:isPartOf <…/prov/bundle/{job_id}> ;
      brainkb:fileName "data_009.ttl" ;
      brainkb:uploadStatus "success" ;
      brainkb:httpStatus 204 ;
      brainkb:sizeBytes 41943040 .

  <…/prov/agent/{user}> a prov:Agent, prov:Person .
}
```

### 2. Named-graph registration — `brainkb:RegistrationActivity` (agent: user)

Written after a graph is registered via `POST /register-named-graph`.

```turtle
<…/prov/activity/reg-{uuid}>
    a prov:Activity, brainkb:RegistrationActivity ;
    prov:startedAtTime "…"^^xsd:dateTime ;
    prov:wasAssociatedWith <…/prov/agent/{user}> ;
    brainkb:targetGraph <{named_graph_url}> .
<{named_graph_url}> prov:wasGeneratedBy <…/prov/activity/reg-{uuid}> .
```

### 3. Crash recovery — `brainkb:RecoveryActivity` (agent: system)

Written when `recover_stuck_jobs()` marks a stuck job as `error`.

```turtle
<…/prov/activity/rec-{job_id}-{ts}>
    a prov:Activity, brainkb:RecoveryActivity ;
    prov:startedAtTime "…"^^xsd:dateTime ;
    prov:wasAssociatedWith <…/prov/agent/system> ;
    prov:used <…/prov/activity/{job_id}> ;
    dcterms:description "{cause}" .
<…/prov/agent/system> a prov:Agent, prov:SoftwareAgent .
```

## Writing

Provenance triples are serialized to Turtle and appended to the provenance graph
via Oxigraph's Graph Store HTTP protocol (`POST {endpoint}/store?graph=…`, which
*merges* rather than replaces). Writes are best-effort: a provenance failure is
logged but never fails the underlying job/registration.

## Retrieval (JSON-LD)

Two read endpoints return a PROV-O bundle as `application/ld+json` via SPARQL
`CONSTRUCT` against the provenance graph:

- `GET /api/provenance/job?job_id=…&user_id=…` — provenance for one job
  (access-controlled with `verify_user_access`).
- `GET /api/provenance/named-graph?iri=…` — all ingestion/registration activity
  that targeted a given named graph.

Because everything is in Oxigraph, arbitrary provenance questions can also be
asked directly over SPARQL, e.g. "all graphs ingested by agent X since T".

## Backward compatibility

- The `skip_provenance` query parameter on the ingestion endpoints is retained
  but no longer controls domain-data embedding (which is removed). Graph-level
  PROV-O tracking always happens.
- `attach_provenance()` / `process_file_with_provenance()` remain in the codebase
  but are no longer on the ingestion hot path.
