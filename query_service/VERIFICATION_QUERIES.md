# BrainKB — Verification Queries

SPARQL (Oxigraph) and SQL (Postgres) queries to verify data written by the
BrainKB skill / MCP: ingested graphs, provenance, deltas, spaces, and the search
index. Replace `my-lab` / `JOB_ID` with your values.

## Fixed graph IRIs

| Purpose | Named graph |
|---|---|
| Graph registry (catalog) | `https://brainkb.org/metadata/named-graph` |
| Spaces manifest | `https://brainkb.org/metadata/spaces/` |
| Provenance | `https://brainkb.org/provenance/` |
| Per-job delta | `https://brainkb.org/provenance/delta/{job_id}` |
| Your data | e.g. `https://brainkb.org/graph/my-lab/` |

## Prefixes

```sparql
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX schema:  <https://schema.org/>
PREFIX brainkb: <https://brainkb.org/vocab/>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
```

---

## SPARQL (Oxigraph)

### 1. All named graphs + triple counts (what exists)

```sparql
SELECT ?g (COUNT(*) AS ?triples) WHERE { GRAPH ?g { ?s ?p ?o } }
GROUP BY ?g ORDER BY DESC(?triples)
```

### 2. Your ingested data

```sparql
SELECT ?s ?p ?o WHERE { GRAPH <https://brainkb.org/graph/my-lab/> { ?s ?p ?o } } LIMIT 200
```

### 3. Registry — which graphs are registered + by whom

```sparql
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>
SELECT ?graph ?description ?registered_at ?registered_by WHERE {
  GRAPH <https://brainkb.org/metadata/named-graph> {
    ?graph dcterms:description ?description ; prov:generatedAtTime ?registered_at .
    OPTIONAL { ?graph prov:wasAttributedTo ?registered_by }
  }
}
```

### 4. Spaces manifest — visibility, owner, contained graphs

```sparql
PREFIX schema:  <https://schema.org/>
PREFIX brainkb: <https://brainkb.org/vocab/>
SELECT ?space ?name ?visibility ?owner
       (GROUP_CONCAT(DISTINCT STR(?graph); SEPARATOR=", ") AS ?graphs) WHERE {
  GRAPH <https://brainkb.org/metadata/spaces/> {
    ?space a brainkb:Space ; schema:name ?name ;
           brainkb:visibility ?visibility ; brainkb:owner ?owner .
    OPTIONAL { ?space brainkb:containsGraph ?graph }
  }
} GROUP BY ?space ?name ?visibility ?owner
```

Members (owner/editor/viewer):

```sparql
PREFIX brainkb: <https://brainkb.org/vocab/>
SELECT ?space ?role ?agent WHERE {
  GRAPH <https://brainkb.org/metadata/spaces/> {
    VALUES ?role { brainkb:owner brainkb:editor brainkb:viewer }
    ?space ?role ?agent .
  }
}
```

### 5. Provenance — ingestion activities (who/when/status)

```sparql
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX brainkb: <https://brainkb.org/vocab/>
SELECT ?activity ?agent ?targetGraph ?status ?start ?end ?success ?fail WHERE {
  GRAPH <https://brainkb.org/provenance/> {
    ?activity a brainkb:IngestionActivity ;
              prov:wasAssociatedWith ?agent ;
              brainkb:targetGraph ?targetGraph ;
              brainkb:jobStatus ?status ;
              prov:startedAtTime ?start .
    OPTIONAL { ?activity prov:endedAtTime ?end }
    OPTIONAL { ?activity brainkb:successCount ?success }
    OPTIONAL { ?activity brainkb:failCount ?fail }
  }
} ORDER BY DESC(?start)
```

### 6. Change history + deltas for a graph

```sparql
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX brainkb: <https://brainkb.org/vocab/>
SELECT ?delta ?deltaGraph ?added ?time WHERE {
  GRAPH <https://brainkb.org/provenance/> {
    ?delta a brainkb:IngestionDelta ;
           brainkb:targetGraph <https://brainkb.org/graph/my-lab/> ;
           brainkb:deltaGraph ?deltaGraph ;
           brainkb:addedTripleCount ?added ;
           prov:generatedAtTime ?time .
  }
} ORDER BY DESC(?time)
```

The exact triples one job added:

```sparql
SELECT ?s ?p ?o WHERE { GRAPH <https://brainkb.org/provenance/delta/JOB_ID> { ?s ?p ?o } }
```

### 7. Per-file results for a job

```sparql
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX brainkb: <https://brainkb.org/vocab/>
SELECT ?name ?status ?http ?size WHERE {
  GRAPH <https://brainkb.org/provenance/> {
    ?file prov:wasGeneratedBy <https://brainkb.org/prov/activity/JOB_ID> ;
          brainkb:fileName ?name ; brainkb:uploadStatus ?status .
    OPTIONAL { ?file brainkb:httpStatus ?http }
    OPTIONAL { ?file brainkb:sizeBytes ?size }
  }
}
```

### 8. Find a term across everything (what search matched)

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?g ?s ?label WHERE {
  GRAPH ?g { ?s rdfs:label ?label . FILTER(CONTAINS(LCASE(STR(?label)), "purkinje")) }
}
```

---

## How to run the SPARQL

### Via the API (needs `admin` scope)

```bash
Q='SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g {?s ?p ?o} } GROUP BY ?g'
curl -s "http://localhost:8010/api/query/sparql/?sparql_query=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$Q")" \
  -H "Authorization: Bearer $TOKEN"
```

Get `$TOKEN`:

```bash
TOKEN=$(curl -s -X POST http://localhost:8010/api/token -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"***"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

### Directly against Oxigraph (nginx proxy on :7878, HTTP Basic auth)

```bash
curl -s "http://localhost:7878/query" \
  --data-urlencode 'query=SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g {?s ?p ?o} } GROUP BY ?g' \
  -u admin:"$OXIGRAPH_PASSWORD" -H 'Accept: application/sparql-results+json'
```

(`OXIGRAPH_USER` / `OXIGRAPH_PASSWORD` are in `.env`.)

---

## SQL (Postgres — not in Oxigraph)

Jobs, space ACL, the search locator index, and indexing tasks live in Postgres.

```sql
-- spaces & membership & graph bindings
SELECT slug, name, visibility, owner FROM spaces;
SELECT space_id, member, role FROM space_members;
SELECT space_id, named_graph_iri FROM space_graphs;

-- ingest jobs
SELECT job_id, status, total_files, success_count, fail_count, start_time, end_time
FROM jobs ORDER BY start_time DESC LIMIT 10;

-- search locator index (subject text per graph/space)
SELECT named_graph_iri, subject, left(text, 60) AS text FROM graph_search_index;

-- background indexing tasks
SELECT task_id, kind, target, status, subjects_indexed, graphs_done, graphs_total
FROM index_tasks ORDER BY created_at DESC LIMIT 10;
```

Run against the Docker Postgres:

```bash
docker exec -e PGPASSWORD="$JWT_POSTGRES_DATABASE_PASSWORD" brainkb-postgres \
  psql -U postgres -d brainkb -c "SELECT slug, visibility, owner FROM spaces;"
```
