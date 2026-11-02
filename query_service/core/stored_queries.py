# -*- coding: utf-8 -*-
"""
Stored (named) SPARQL queries that anyone allowed to read a space may run
against that space's graph, without the admin-only arbitrary-SPARQL endpoint.

Each entry is a fixed query from the BrainKB UI (/taxonomy, /literature).
Callers choose the query by name and supply only:
  graph     -- a named graph that belongs to a space (checked for read access)
  and the parameters the query declares, each validated before substitution:
    "iri"      a single IRI, written <{{name}}> in the query
    "iri_list" up to MAX_IRI_LIST IRIs, substituted as "<a> <b> ..." (for VALUES)
Every query ends in a LIMIT; `limit` is that cap, so callers can tell when a
result was cut off.

Generated from brainkb-ui src/app/{taxonomy,literature}/queries.ts; keep the two
in step when a page's query changes.
"""

MAX_IRI_LIST = 50

STORED_QUERIES = {
    # Named taxa (they carry an accession; cluster-level taxa do not) of the newest
    # release, with their level, species (from the taxonomy title), display color
    # and how many clusters sit under them.
    "taxonomy.taxa": {
        "params": {},
        "limit": 3000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?taxon ?label ?accession ?level ?title ?version ?parent ?order ?cl ?color ?prev ?clusters
WHERE {
  GRAPH <{{graph}}> {
    ?taxon a bican:CellTypeTaxon ;
           bican:accession_id ?accession ;
           rdfs:label ?label .
    FILTER NOT EXISTS { ?newer bican:revision_of ?taxon }
    OPTIONAL {
      ?taxon bican:part_of_set ?set .
      OPTIONAL { ?set rdfs:label ?level }
      OPTIONAL { ?set bican:part_of_taxonomy/bican:title ?title }
    }
    OPTIONAL { ?taxon biolink:version ?version }
    OPTIONAL { ?taxon bican:has_parent ?parent }
    OPTIONAL { ?taxon bican:order ?order }
    OPTIONAL { ?taxon bican:cell_type_ontology_term ?cl }
    OPTIONAL { ?c bican:is_color_for_taxon ?taxon ; bican:color_hex_triplet ?color }
    OPTIONAL { ?taxon bican:revision_of ?prev }
    OPTIONAL {
      SELECT ?taxon (COUNT(DISTINCT ?k) AS ?clusters)
      WHERE { ?k a bican:Cluster ; bican:has_parent ?taxon }
      GROUP BY ?taxon
    }
  }
}
LIMIT 3000""",
    },
    # Every step of every newest taxon's revision chain: ?from revision_of ?prev,
    # with what the earlier revision said about itself.
    "taxonomy.revisions": {
        "params": {},
        "limit": 5000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?taxon ?from ?prev ?label ?accession ?version ?parentLabel ?cl
WHERE {
  GRAPH <{{graph}}> {
    ?taxon bican:accession_id ?a .
    FILTER NOT EXISTS { ?newer bican:revision_of ?taxon }
    ?taxon bican:revision_of* ?from .
    ?from bican:revision_of ?prev .
    OPTIONAL { ?prev rdfs:label ?label }
    OPTIONAL { ?prev bican:accession_id ?accession }
    OPTIONAL { ?prev biolink:version ?version }
    OPTIONAL { ?prev bican:has_parent/rdfs:label ?parentLabel }
    OPTIONAL { ?prev bican:cell_type_ontology_term ?cl }
  }
}
LIMIT 5000""",
    },
    # Curated marker genes of each newest taxon and of each of its earlier revisions
    # (?holder), so the two can be compared.
    "taxonomy.markers": {
        "params": {},
        "limit": 10000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT DISTINCT ?taxon ?holder ?gene ?symbol ?identifier
WHERE {
  GRAPH <{{graph}}> {
    ?taxon bican:accession_id ?a .
    FILTER NOT EXISTS { ?newer bican:revision_of ?taxon }
    ?taxon bican:revision_of* ?holder .
    ?holder bican:curated_markers ?gene .
    OPTIONAL { ?gene biolink:symbol ?symbol }
    OPTIONAL { ?gene schema:identifier ?identifier }
  }
}
LIMIT 10000""",
    },
    # Papers whose extracted entities point at a newest taxon or any earlier
    # revision of it (?hit) by a skos relation. Kept apart from MARKER_PAPERS_QUERY
    # (and in one graph) because Oxigraph times out on the combined/cross-graph form.
    "taxonomy.papers": {
        "params": {},
        "limit": 10000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?taxon ?hit ?how ?entity (SAMPLE(?el) AS ?entityLabel)
       ?paper (SAMPLE(?t) AS ?title) (SAMPLE(?d) AS ?doi) (COUNT(DISTINCT ?m) AS ?mentions)
WHERE {
  GRAPH <{{graph}}> {
    VALUES ?how { skos:exactMatch skos:closeMatch skos:broadMatch skos:narrowMatch skos:relatedMatch }
    ?entity ?how ?hit ;
            prov:hadPrimarySource ?paper .
    ?hit ^bican:revision_of* ?taxon .
    ?taxon bican:accession_id ?a .
    FILTER NOT EXISTS { ?newer bican:revision_of ?taxon }
    ?entity rdfs:label ?el ;
            ner:hasMention ?m .
    OPTIONAL { ?paper ner:title ?t }
    OPTIONAL { ?paper ner:doi ?d }
  }
}
GROUP BY ?taxon ?hit ?how ?entity ?paper
LIMIT 10000""",
    },
    # Papers with an extracted gene that is a curated marker of a newest taxon or
    # of one of its earlier revisions (?how = "marker").
    "taxonomy.marker_papers": {
        "params": {},
        "limit": 10000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?taxon ?hit ?how ?entity (SAMPLE(?el) AS ?entityLabel) (SAMPLE(?g) AS ?gene)
       ?paper (SAMPLE(?t) AS ?title) (SAMPLE(?d) AS ?doi) (COUNT(DISTINCT ?m) AS ?mentions)
WHERE {
  GRAPH <{{graph}}> {
    ?taxon bican:accession_id ?a .
    FILTER NOT EXISTS { ?newer bican:revision_of ?taxon }
    ?taxon bican:revision_of* ?hit .
    ?hit bican:curated_markers ?g .
    ?entity skos:exactMatch ?g ;
            prov:hadPrimarySource ?paper ;
            rdfs:label ?el ;
            ner:hasMention ?m .
    OPTIONAL { ?paper ner:title ?t }
    OPTIONAL { ?paper ner:doi ?d }
  }
  BIND("marker" AS ?how)
}
GROUP BY ?taxon ?hit ?how ?entity ?paper
LIMIT 10000""",
    },
    # One row per (epigenome summary, measurement), with its track and
    # marker-enhancer counts. Summaries without epi:about are for species that have
    # no taxonomy here (mouse); they are matched to taxa by accession.
    "taxonomy.epigenome_summaries": {
        "params": {},
        "limit": 10000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?summary ?taxon ?accession ?species ?measurement ?tracks ?enhancers
WHERE {
  GRAPH <{{graph}}> {
    ?summary a epi:EpigenomicSummary ;
             bican:accession_id ?accession .
    OPTIONAL { ?summary epi:about ?taxon }
    OPTIONAL { ?summary biolink:in_taxon ?species }
    OPTIONAL { ?summary epi:available_measurement ?measurement }
    {
      SELECT ?summary (COUNT(DISTINCT ?tr) AS ?tracks) (COUNT(DISTINCT ?en) AS ?enhancers)
      WHERE {
        ?summary a epi:EpigenomicSummary .
        OPTIONAL { ?summary epi:has_track ?tr }
        OPTIONAL { ?summary epi:has_marker_enhancer ?en }
      }
      GROUP BY ?summary
    }
  }
}
LIMIT 10000""",
    },
    # Tracks of the given summaries. {{summaries}} is a space-separated list of <IRI>s.
    "taxonomy.epigenome_tracks": {
        "params": {'summaries': 'iri_list'},
        "limit": 5000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?summary ?track ?label ?measurement ?assay ?lab ?url ?match ?level ?assembly ?format
WHERE {
  GRAPH <{{graph}}> {
    VALUES ?summary { {{summaries}} }
    ?summary epi:has_track ?track .
    ?track rdfs:label ?label .
    OPTIONAL { ?track epi:measurement ?measurement }
    OPTIONAL { ?track epi:assay ?assay }
    OPTIONAL { ?track epi:produced_by ?lab }
    OPTIONAL { ?track schema:url ?url }
    OPTIONAL { ?track epi:cell_type_match ?match }
    OPTIONAL { ?track epi:cell_type_level ?level }
    OPTIONAL { ?track epi:genome_assembly ?assembly }
    OPTIONAL { ?track epi:file_format ?format }
  }
}
LIMIT 5000""",
    },
    # Marker-gene enhancers (activity-by-contact links) of the given summaries,
    # with the other cell types the enhancer is also active in.
    "taxonomy.epigenome_enhancers": {
        "params": {'summaries': 'iri_list'},
        "limit": 5000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?summary ?enhancer ?gene ?symbol ?region ?regionType ?abc ?specific
       (COUNT(DISTINCT ?other) AS ?shared) (GROUP_CONCAT(DISTINCT ?ol; separator="; ") AS ?sharedLabels)
WHERE {
  GRAPH <{{graph}}> {
    VALUES ?summary { {{summaries}} }
    ?summary epi:has_marker_enhancer ?enhancer .
    ?enhancer epi:target_gene_symbol ?symbol ;
              epi:region ?region .
    OPTIONAL { ?enhancer epi:target_gene ?gene }
    OPTIONAL { ?enhancer epi:region_type ?regionType }
    OPTIONAL { ?enhancer epi:abc_score ?abc }
    OPTIONAL { ?enhancer epi:specific ?specific }
    OPTIONAL { ?enhancer epi:shared_with ?other }
    OPTIONAL { ?enhancer epi:shared_with_label ?otherLabel }
    BIND(COALESCE(?otherLabel, "") AS ?ol)
  }
}
GROUP BY ?summary ?enhancer ?gene ?symbol ?region ?regionType ?abc ?specific
LIMIT 5000""",
    },
    # Clusters directly under the given taxon (a cluster has_parent every level
    # above it, so this is only asked for taxa without named subtypes).
    "taxonomy.clusters": {
        "params": {'taxon': 'iri'},
        "limit": 1000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?cluster ?label
WHERE {
  GRAPH <{{graph}}> {
    ?cluster a bican:Cluster ;
             bican:has_parent <{{taxon}}> ;
             rdfs:label ?label .
  }
}
LIMIT 1000""",
    },
    # Cell counts of one taxon in the taxonomy's data file (epi:CellSummary):
    # totals, then the split by region and by donor. {{taxon}} is the taxon IRI.
    "taxonomy.cells": {
        "params": {'taxon': 'iri'},
        "limit": 10,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?summary ?cells ?fraction ?donors ?regions ?samples ?url
WHERE {
  GRAPH <{{graph}}> {
    ?summary a epi:CellSummary ;
             epi:about <{{taxon}}> ;
             epi:n_cells ?cells .
    OPTIONAL { ?summary epi:fraction_of_taxonomy_cells ?fraction }
    OPTIONAL { ?summary epi:n_donors ?donors }
    OPTIONAL { ?summary epi:n_regions ?regions }
    OPTIONAL { ?summary epi:n_barcoded_cell_samples ?samples }
    OPTIONAL { ?summary schema:url ?url }
  }
}
LIMIT 10""",
    },
    # ?source says where the region came from: the tissue sample's structure in
    # BrainKB, or (when it has none) the region named in the data file.
    "taxonomy.cell_regions": {
        "params": {'taxon': 'iri'},
        "limit": 1000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?count ?cells ?region ?regionLabel ?parentLabel ?abbreviation ?source
WHERE {
  GRAPH <{{graph}}> {
    ?summary epi:about <{{taxon}}> ;
             epi:has_region_count ?count .
    ?count epi:n_cells ?cells .
    OPTIONAL {
      ?count epi:region ?region .
      OPTIONAL { ?region rdfs:label ?regionLabel }
      OPTIONAL { ?region bican:has_parent_parcellation_term/rdfs:label ?parentLabel }
    }
    OPTIONAL { ?count epi:region_abbreviation ?abbreviation }
    OPTIONAL { ?count epi:region_source ?source }
  }
}
LIMIT 1000""",
    },
    "taxonomy.cell_donors": {
        "params": {'taxon': 'iri'},
        "limit": 1000,
        "query": """PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX epi: <https://identifiers.org/brain-bican/vocab/draft/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX schema: <http://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX ner: <https://brainkb.org/ner/>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?count ?cells ?donor ?donorId ?sex ?age ?ageUnit
WHERE {
  GRAPH <{{graph}}> {
    ?summary epi:about <{{taxon}}> ;
             epi:has_donor_count ?count .
    ?count epi:n_cells ?cells .
    OPTIONAL { ?count epi:donor_id ?donorId }
    OPTIONAL {
      ?count epi:donor ?donor .
      OPTIONAL { ?donor bican:sex ?sex }
      OPTIONAL { ?donor bican:age_of_death ?age }
      OPTIONAL { ?donor bican:age_at_death_unit ?ageUnit }
    }
  }
}
LIMIT 1000""",
    },
    "literature.papers": {
        "params": {},
        "limit": 1000,
        "query": """PREFIX ner: <https://brainkb.org/ner/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
SELECT ?paper (SAMPLE(?t) AS ?title) (SAMPLE(?d) AS ?doi) (SAMPLE(?y) AS ?year) (SAMPLE(?j) AS ?journal)
WHERE {
  GRAPH <{{graph}}> {
    ?paper a ner:Publication .
    OPTIONAL { ?paper ner:title ?t }
    OPTIONAL { ?paper ner:doi ?d }
    OPTIONAL { ?paper dcterms:issued ?y }
    OPTIONAL { ?paper dcterms:bibliographicCitation ?j }
  }
}
GROUP BY ?paper
LIMIT 1000""",
    },
    # One row per (entity, mapping): the entity's specific ner: class, its paper,
    # how often that paper mentions it, and what it maps to by which skos relation.
    # SAMPLE() collapses entities carrying two labels (PENK / Penk) into one row.
    "literature.entities": {
        "params": {},
        "limit": 20000,
        "query": """PREFIX ner: <https://brainkb.org/ner/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
SELECT ?paper ?entity (SAMPLE(?l) AS ?label) (SAMPLE(?ty) AS ?type) (COUNT(DISTINCT ?m) AS ?mentions) ?how ?target
WHERE {
  GRAPH <{{graph}}> {
    ?entity a ner:NamedEntity ;
            prov:hadPrimarySource ?paper ;
            rdfs:label ?l ;
            a ?ty ;
            ner:hasMention ?m .
    FILTER(?ty != ner:NamedEntity && STRSTARTS(STR(?ty), STR(ner:)))
    OPTIONAL {
      VALUES ?how { skos:exactMatch skos:closeMatch skos:broadMatch skos:narrowMatch skos:relatedMatch }
      ?entity ?how ?target .
    }
  }
}
GROUP BY ?paper ?entity ?how ?target
LIMIT 20000""",
    },
    # What the mapped-to records say about themselves. A cell-type taxon from an
    # earlier release also gets the newest taxon that revises it (?newest), which
    # is what /taxonomy shows.
    "literature.targets": {
        "params": {},
        "limit": 20000,
        "query": """PREFIX ner: <https://brainkb.org/ner/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
SELECT ?target (SAMPLE(?k) AS ?kind) (SAMPLE(?lab) AS ?label) (SAMPLE(?sym) AS ?symbol) (SAMPLE(?id) AS ?identifier)
       (SAMPLE(?sp) AS ?species) (SAMPLE(?acc) AS ?accession) (SAMPLE(?nw) AS ?newest) (SAMPLE(?nwl) AS ?newestLabel)
WHERE {
  GRAPH <{{graph}}> {
    VALUES ?how { skos:exactMatch skos:closeMatch skos:broadMatch skos:narrowMatch skos:relatedMatch }
    ?entity a ner:NamedEntity ;
            ?how ?target .
    OPTIONAL { ?target a ?k }
    OPTIONAL { ?target rdfs:label ?lab }
    OPTIONAL { ?target biolink:symbol ?sym }
    OPTIONAL { ?target <http://schema.org/identifier> ?id }
    OPTIONAL { ?target biolink:in_taxon_label ?sp }
    OPTIONAL { ?target bican:accession_id ?acc }
    OPTIONAL {
      ?target a bican:CellTypeTaxon ;
              ^bican:revision_of* ?nw .
      FILTER NOT EXISTS { ?n bican:revision_of ?nw }
      ?nw rdfs:label ?nwl .
    }
  }
}
GROUP BY ?target
LIMIT 20000""",
    },
    # A few mentions of one entity, with the sentence each sits in.
    "literature.mentions": {
        "params": {'entity': 'iri'},
        "limit": 5,
        "query": """PREFIX ner: <https://brainkb.org/ner/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX biolink: <https://w3id.org/biolink/vocab/>
SELECT DISTINCT ?surface ?sentence ?title
WHERE {
  GRAPH <{{graph}}> {
    <{{entity}}> ner:hasMention ?m .
    ?m ner:surfaceForm ?surface ;
       ner:inSentence/ner:sentenceText ?sentence .
    OPTIONAL { <{{entity}}> prov:hadPrimarySource/ner:title ?title }
  }
}
LIMIT 5""",
    },
}
