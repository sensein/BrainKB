# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : shared.py
# @Software: PyCharm

from core.configuration import load_environment
import uuid
import datetime
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, XSD, DCTERMS, PROV

ingest_url = load_environment()["INGEST_URL"]



def extract_base_namespace(graph):
    """
    Extracts the base namespace dynamically from the RDF graph.
    Assumes that the primary entities in the graph belong to the base namespace.
    """
    for subj in graph.subjects():
        if isinstance(subj, URIRef) and "#" not in subj and "/" in str(subj):
            base = str(subj).rsplit("/", 1)[0] + "/"  # Extract the base URI up to the last '/'
            return Namespace(base)
    return Namespace("http://brainkb.org/")  # Default fallback if extraction fails


def attach_provenance(user, ttl_data):
    """
Attach the provenance information about the ingestion activity. Saying, we received this triple by X user on XXXX date.
    It appends provenance triples externally while keeping the original triples intact.

    Parameters:
    - user (str): The username of the person posting the data.
    - ttl_data (str): The existing Turtle (TTL) RDF data.

    Returns:
    - str: Combined RDF (Turtle format) containing original data and provenance metadata.

    Example:
        Input:
            @prefix NCBIAssembly: <https://www.ncbi.nlm.nih.gov/assembly/> .
            @prefix NCBIGene: <http://identifiers.org/ncbigene/> .
            @prefix bican: <https://identifiers.org/brain-bican/vocab/> .
            @prefix biolink: <https://w3id.org/biolink/vocab/> .
            @prefix dcterms: <http://purl.org/dc/terms/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix schema1: <http://schema.org/> .

            bican:000015fd3d6a449b47e75651210a6cc74fca918255232c8af9e46d077034c84d a bican:GeneAnnotation ;
                rdfs:label "LOC106504536" ;
                schema1:identifier "106504536" ;
                bican:molecular_type "protein_coding" ;
                bican:referenced_in bican:d5c45501b3b8e5d8b5b5ba0f4d72750d8548515c1b00c23473a03a213f15360a ;
                biolink:category bican:GeneAnnotation ;
                biolink:in_taxon bican:7d54dfcbd21418ea26d9bfd51015414b6ad1d3760d09672afc2e1e4e6c7da1dd ;
                biolink:in_taxon_label "Sus scrofa" ;
                biolink:symbol "LOC106504536" ;
                biolink:xref NCBIGene:106504536 .

            bican:00027255beed5c235eaedf534ac72ffc67ed597821a5b5c0f35709d5eb93bd47 a bican:GeneAnnotation ;
                rdfs:label "LRRC40" ;
                schema1:identifier "100515841" ;
                bican:molecular_type "protein_coding" ;
                bican:referenced_in bican:d5c45501b3b8e5d8b5b5ba0f4d72750d8548515c1b00c23473a03a213f15360a ;
                biolink:category bican:GeneAnnotation ;
                biolink:in_taxon bican:7d54dfcbd21418ea26d9bfd51015414b6ad1d3760d09672afc2e1e4e6c7da1dd ;
                biolink:in_taxon_label "Sus scrofa" ;
                biolink:symbol "LRRC40" ;
                biolink:xref NCBIGene:100515841 .

        Output:
            @prefix NCBIGene: <http://identifiers.org/ncbigene/> .
            @prefix bican: <https://identifiers.org/brain-bican/vocab/> .
            @prefix biolink: <https://w3id.org/biolink/vocab/> .
            @prefix dcterms: <http://purl.org/dc/terms/> .
            @prefix prov: <http://www.w3.org/ns/prov#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix schema1: <http://schema.org/> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            bican:000015fd3d6a449b47e75651210a6cc74fca918255232c8af9e46d077034c84d a bican:GeneAnnotation ;
                rdfs:label "LOC106504536" ;
                schema1:identifier "106504536" ;
                bican:molecular_type "protein_coding" ;
                bican:referenced_in bican:d5c45501b3b8e5d8b5b5ba0f4d72750d8548515c1b00c23473a03a213f15360a ;
                biolink:category bican:GeneAnnotation ;
                biolink:in_taxon bican:7d54dfcbd21418ea26d9bfd51015414b6ad1d3760d09672afc2e1e4e6c7da1dd ;
                biolink:in_taxon_label "Sus scrofa" ;
                biolink:symbol "LOC106504536" ;
                biolink:xref NCBIGene:106504536 .

            bican:00027255beed5c235eaedf534ac72ffc67ed597821a5b5c0f35709d5eb93bd47 a bican:GeneAnnotation ;
                rdfs:label "LRRC40" ;
                schema1:identifier "100515841" ;
                bican:molecular_type "protein_coding" ;
                bican:referenced_in bican:d5c45501b3b8e5d8b5b5ba0f4d72750d8548515c1b00c23473a03a213f15360a ;
                biolink:category bican:GeneAnnotation ;
                biolink:in_taxon bican:7d54dfcbd21418ea26d9bfd51015414b6ad1d3760d09672afc2e1e4e6c7da1dd ;
                biolink:in_taxon_label "Sus scrofa" ;
                biolink:symbol "LRRC40" ;
                biolink:xref NCBIGene:100515841 .


            #added new provenance information regarding the ingestion activity. Might have to update  <https://identifiers.org/brain-bican/vocab/ingestionActivity/e4db1e0b-98ff-497c-88b1-afb4a6d7ee14 patten, to be discussed and done later
            <https://identifiers.org/brain-bican/vocab/ingestionActivity/e4db1e0b-98ff-497c-88b1-afb4a6d7ee14> a prov:Activity,
                    bican:IngestionActivity ;
                prov:generatedAtTime "2025-01-31T16:52:22.061674+00:00"^^xsd:dateTime ;
                prov:wasAssociatedWith bican:000015fd3d6a449b47e75651210a6cc74fca918255232c8af9e46d077034c84d,
                    bican:00027255beed5c235eaedf534ac72ffc67ed597821a5b5c0f35709d5eb93bd47,
                    <https://identifiers.org/brain-bican/vocab/agent/testuser> .

            <https://identifiers.org/brain-bican/vocab/provenance/e4db1e0b-98ff-497c-88b1-afb4a6d7ee14> a prov:Entity ;
                dcterms:provenance "Data posted by testuser on 2025-01-31T16:52:22.061674Z" ;
                prov:generatedAtTime "2025-01-31T16:52:22.061674+00:00"^^xsd:dateTime ;
                prov:wasAttributedTo <https://identifiers.org/brain-bican/vocab/agent/testuser> ;
                prov:wasGeneratedBy <https://identifiers.org/brain-bican/vocab/ingestionActivity/e4db1e0b-98ff-497c-88b1-afb4a6d7ee14> .

    """

    # Validate input parameters
    if not isinstance(user, str) or not user.strip():
        raise ValueError("User must be a non-empty string.")

    if not isinstance(ttl_data, str) or not ttl_data.strip():
        raise ValueError("TTL data must be a non-empty string.")

    try:
        original_graph = Graph()
        original_graph.parse(data=ttl_data, format="turtle")
    except Exception as e:
        raise RuntimeError(f"Error parsing TTL data: {e}")

    try:
        BASE = extract_base_namespace(original_graph)
    except Exception as e:
        raise RuntimeError(f"Failed to extract base namespace: {e}")

    try:
        # Create provenance graph
        prov_graph = Graph()

        # Generate timestamps (ISO 8601 format, UTC)
        start_time = datetime.datetime.utcnow().isoformat() + "Z"

        # Generate a unique UUID for provenance entity
        provenance_uuid = str(uuid.uuid4())
        prov_entity = URIRef(BASE[f"provenance/{provenance_uuid}"])
        ingestion_activity = URIRef(BASE[f"ingestionActivity/{provenance_uuid}"])
        user_uri = URIRef(BASE[f"agent/{user}"])

        # Define provenance entity
        prov_graph.add((prov_entity, RDF.type, PROV.Entity))
        prov_graph.add((prov_entity, PROV.generatedAtTime, Literal(start_time, datatype=XSD.dateTime)))
        prov_graph.add((prov_entity, PROV.wasAttributedTo, user_uri))
        prov_graph.add((prov_entity, PROV.wasGeneratedBy, ingestion_activity))

        # Define ingestion activity
        # here we say IngestionActivity is an activity of type prov:Activity
        prov_graph.add((ingestion_activity, RDF.type, PROV.Activity))
        prov_graph.add((ingestion_activity, RDF.type, BASE["IngestionActivity"]))
        prov_graph.add((ingestion_activity, PROV.generatedAtTime, Literal(start_time, datatype=XSD.dateTime)))
        prov_graph.add((ingestion_activity, PROV.wasAssociatedWith, user_uri))

        # Attach provenance to original triples
        for entity in original_graph.subjects():
            if isinstance(entity, URIRef):
                # disabled triple update, now it's just the referencing to the existing triple
                # prov_graph.add((entity, PROV.wasInformedBy, prov_entity)) #updates the triple to say that particular triple was ingested by some activity, which in our case is the ingestion activity
                prov_graph.add((ingestion_activity, PROV.wasAssociatedWith, entity))

        #  add a Dublin Core provenance statement -- this is the new addition to say it's ingested by user
        prov_graph.add((prov_entity, DCTERMS.provenance, Literal(f"Data ingested by {user} on {start_time}")))

        # Combine both graphs (original + provenance) so that we have new provenance information attached.
        final_graph = original_graph + prov_graph

        return final_graph.serialize(format="turtle")

    except Exception as e:
        raise RuntimeError(f"Error generating provenance RDF: {e}")


def get_endpoints(endpoint_type: str) -> str:
    """
    Retrieve the URL endpoint based on the specified type.

    Parameters:
        endpoint_type (str): The type of endpoint needed.
        ingest_url (str): The base URL to which the endpoint types will be appended.

    Returns:
        str: The full URL for the specified endpoint type.

    Raises:
        ValueError: If the specified endpoint type is not supported.
    """
    endpoints = {
        "jsonld": f"{ingest_url}/query/insert-jsonld",
    }

    if endpoint_type not in endpoints:
        raise ValueError("Unsupported endpoint type specified.")

    return endpoints[endpoint_type]


