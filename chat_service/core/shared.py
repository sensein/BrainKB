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

from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import logging
import requests
import asyncio
from core.configuration import config

logger = logging.getLogger(__name__)

chat_sessions = {}


def get_or_create_session(session_id: Optional[str] = None) -> str:
    """Get existing session ID or create a new one"""
    if session_id and session_id in chat_sessions:
        return session_id
    else:
        new_session_id = str(uuid.uuid4())
        chat_sessions[new_session_id] = {
            "messages": [],
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat()
        }
        return new_session_id


def update_session_history(session_id: str, user_message: str, assistant_message: str):
    """Update the session with new messages"""
    if session_id not in chat_sessions:
        chat_sessions[session_id] = {
            "messages": [],
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat()
        }

    # user message
    chat_sessions[session_id]["messages"].append({
        "role": "user",
        "content": user_message,
        "timestamp": datetime.now().isoformat()
    })

    # Add assistant message
    chat_sessions[session_id]["messages"].append({
        "role": "assistant",
        "content": assistant_message,
        "timestamp": datetime.now().isoformat()
    })

    # Update last updated timestamp
    chat_sessions[session_id]["last_updated"] = datetime.now().isoformat()

def anatomical_structure():
    """Return the anatomical structure model"""
    return """
        {
        "$defs": {
            "ANATOMICALDIRECTION": {
                "description": "A controlled vocabulary term defining axis direction in terms of anatomical direction.",
                "enum": [
                    "left_to_right",
                    "posterior_to_anterior",
                    "inferior_to_superior",
                    "superior_to_inferior",
                    "anterior_to_posterior"
                ],
                "title": "ANATOMICALDIRECTION",
                "type": "string"
            },
            "Activity": {
                "additionalProperties": false,
                "description": "An activity is something that occurs over a period of time and acts upon or with entities; it may include consuming, processing, transforming, modifying, relocating, using, or generating entities.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:Activity"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "Activity",
                "type": "object"
            },
            "AnatomicalAnnotationSet": {
                "additionalProperties": false,
                "description": "An anatomical annotation set is a versioned release of a set of anatomical annotations anchored  in the same anatomical space that divides the space into distinct segments following some annotation  criteria or parcellation scheme. For example, the anatomical annotation set of 3D image based  reference atlases (e.g. Allen Mouse CCF) can be expressed as a set of label indices of single  multi-valued image annotations or as a set of segmentation masks (ref: ILX:0777108, RRID:SCR_023499)",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:AnatomicalAnnotationSet"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "parameterizes": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the anatomical space for which the anatomical annotation set is anchored",
                        "type": "string"
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "type": "string"
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "version": {
                        "type": "string"
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "parameterizes",
                    "version",
                    "id"
                ],
                "title": "AnatomicalAnnotationSet",
                "type": "object"
            },
            "AnatomicalSpace": {
                "additionalProperties": false,
                "description": "An anatomical space is versioned release of a mathematical space with a defined mapping  between the anatomical axes and the mathematical axes. An anatomical space may be defined by  a reference image chosen as the biological reference for an anatomical structure of interest  derived from a single or multiple specimens (ref: ILX:0777106, RRID:SCR_023499)",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:AnatomicalSpace"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "measures": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the specific image dataset used to define the anatomical space.",
                        "type": "string"
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "type": "string"
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "version": {
                        "type": "string"
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "measures",
                    "version",
                    "id"
                ],
                "title": "AnatomicalSpace",
                "type": "object"
            },
            "Attribute": {
                "additionalProperties": false,
                "description": "A property or characteristic of an entity. For example, an apple may have properties such as color, shape, age, crispiness. An environmental sample may have attributes such as depth, lat, long, material.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:Attribute"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "has_attribute_type": {
                        "description": "connects an attribute to a class that describes it",
                        "type": "string"
                    },
                    "has_qualitative_value": {
                        "description": "connects an attribute to a value",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_quantitative_value": {
                        "description": "connects an attribute to a value",
                        "items": {
                            "$ref": "#/$defs/QuantityValue"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "The human-readable 'attribute name' can be set to a string which reflects its context of interpretation, e.g. SEPIO evidence/provenance/confidence annotation or it can default to the name associated with the 'has attribute type' slot ontology term.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id",
                    "has_attribute_type"
                ],
                "title": "Attribute",
                "type": "object"
            },
            "Checksum": {
                "additionalProperties": false,
                "description": "Checksum values associated with digital entities.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:Checksum"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "checksum_algorithm": {
                        "$ref": "#/$defs/DigestType",
                        "description": "The type of cryptographic hash function used to calculate the checksum value."
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "value": {
                        "description": "The checksum value obtained from a specific cryotographic hash function.",
                        "type": [
                            "string",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "Checksum",
                "type": "object"
            },
            "DISTANCEUNIT": {
                "description": "",
                "enum": [
                    "mm",
                    "um",
                    "m"
                ],
                "title": "DISTANCEUNIT",
                "type": "string"
            },
            "Dataset": {
                "additionalProperties": false,
                "description": "an item that refers to a collection of data from a data source.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:Dataset"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "creation_date": {
                        "description": "date on which an entity was created. This can be applied to nodes or edges",
                        "format": "date",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "format": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "license": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "rights": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "Dataset",
                "type": "object"
            },
            "DigestType": {
                "description": "",
                "enum": [
                    "spdx:checksumAlgorithm_sha1",
                    "spdx:checksumAlgorithm_md5",
                    "spdx:checksumAlgorithm_sha256"
                ],
                "title": "DigestType",
                "type": "string"
            },
            "Gene": {
                "additionalProperties": false,
                "description": "A region (or regions) that includes all of the sequence elements necessary to encode a functional transcript. A gene locus may include regulatory regions, transcribed regions and/or other functional sequence regions.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:Gene"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "has_biological_sequence": {
                        "description": "connects a genomic feature to its sequence",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "in_taxon": {
                        "description": "connects an entity to its taxonomic classification. Only certain kinds of entities can be taxonomically classified; see 'thing with taxon'",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "in_taxon_label": {
                        "description": "The human readable scientific name for the taxon of the entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "symbol": {
                        "description": "Symbol for a particular thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "Gene",
                "type": "object"
            },
            "Genome": {
                "additionalProperties": false,
                "description": "A genome is the sum of genetic material within a cell or virion.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:Genome"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "has_biological_sequence": {
                        "description": "connects a genomic feature to its sequence",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "in_taxon": {
                        "description": "connects an entity to its taxonomic classification. Only certain kinds of entities can be taxonomically classified; see 'thing with taxon'",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "in_taxon_label": {
                        "description": "The human readable scientific name for the taxon of the entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "Genome",
                "type": "object"
            },
            "ImageDataset": {
                "additionalProperties": false,
                "description": "An image dataset is versioned release of a multidimensional regular grid of measurements  and metadata required for a morphological representation of an entity such as an anatomical  structure (ref: OBI_0003327, RRID:SCR_006266)",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:ImageDataset"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "type": "string"
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "unit": {
                        "$ref": "#/$defs/DISTANCEUNIT",
                        "description": "A controlled vocabulary attribute defining the length unit of the x, y, and z  resolution values."
                    },
                    "version": {
                        "type": "string"
                    },
                    "x_direction": {
                        "$ref": "#/$defs/ANATOMICALDIRECTION",
                        "description": "A controlled vocabulary attribute defining the x axis direction in terms of anatomical  direction."
                    },
                    "x_resolution": {
                        "description": "The resolution (length / pixel) in along the x axis (numerical value part).",
                        "type": [
                            "number",
                            "null"
                        ]
                    },
                    "x_size": {
                        "description": "The number of pixels/voxels (size) along the x axis.",
                        "minimum": 1,
                        "type": [
                            "integer",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "y_direction": {
                        "$ref": "#/$defs/ANATOMICALDIRECTION",
                        "description": "A controlled vocabulary attribute defining the y axis direction in terms of anatomical  direction."
                    },
                    "y_resolution": {
                        "description": "The resolution (length / pixel) in along the y axis (numerical value part).",
                        "type": [
                            "number",
                            "null"
                        ]
                    },
                    "y_size": {
                        "description": "The number of pixels/voxels (size) along the y axis.",
                        "minimum": 1,
                        "type": [
                            "integer",
                            "null"
                        ]
                    },
                    "z_direction": {
                        "$ref": "#/$defs/ANATOMICALDIRECTION",
                        "description": "A controlled vocabulary attribute defining the z axis direction in terms of anatomical  direction."
                    },
                    "z_resolution": {
                        "description": "The resolution (length / pixel) in along the z axis (numerical value part).",
                        "type": [
                            "number",
                            "null"
                        ]
                    },
                    "z_size": {
                        "description": "The number of pixels/voxels (size) along the y axis.",
                        "minimum": 1,
                        "type": [
                            "integer",
                            "null"
                        ]
                    }
                },
                "required": [
                    "version",
                    "id"
                ],
                "title": "ImageDataset",
                "type": "object"
            },
            "MaterialSample": {
                "additionalProperties": false,
                "description": "A sample is a limited quantity of something (e.g. an individual or set of individuals from a population, or a portion of a substance) to be used for testing, analysis, inspection, investigation, demonstration, or trial use. [SIO]",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:MaterialSample"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "MaterialSample",
                "type": "object"
            },
            "NamedThing": {
                "additionalProperties": false,
                "description": "a databased entity or concept/class",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:NamedThing"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "NamedThing",
                "type": "object"
            },
            "OrganismTaxon": {
                "additionalProperties": false,
                "description": "A classification of a set of organisms. Example instances: NCBITaxon:9606 (Homo sapiens), NCBITaxon:2 (Bacteria). Can also be used to represent strains or subspecies.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:OrganismTaxon"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "has_taxonomic_rank": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "OrganismTaxon",
                "type": "object"
            },
            "ParcellationAnnotation": {
                "additionalProperties": false,
                "description": "A parcellation annotation defines a specific segment of an anatomical space denoted by an internal  identifier and is a unique and exclusive member of a versioned release anatomical annotation set.  For example, in the case where the anatomical annotation set is a single multi-value image mask (e.g. Allen Mouse CCF), a specific annotation corresponds to a specific label index (internal identifier) in the mask.",
                "properties": {
                    "internal_identifier": {
                        "description": "An identifier that uniquely denotes a specific parcellation annotation within the context of an anatomical annotation set",
                        "type": "string"
                    },
                    "part_of_anatomical_annotation_set": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "type": "string"
                    },
                    "voxel_count": {
                        "description": "The number of voxels (3D pixels) spanned by the parcellation annotation (optional).",
                        "minimum": 0,
                        "type": [
                            "integer",
                            "null"
                        ]
                    }
                },
                "required": [
                    "part_of_anatomical_annotation_set",
                    "internal_identifier"
                ],
                "title": "ParcellationAnnotation",
                "type": "object"
            },
            "ParcellationAnnotationTermMap": {
                "additionalProperties": false,
                "description": "The parcellation annotation term map table defines the relationship between parcellation annotations and parcellation terms.  A parcellation term is uniquely denoted by a parcellation term identifier and the parcellation terminology it belongs to.  A parcellation term can be spatially parameterized by the union of one or more parcellation annotations within a versioned  release of an anatomical annotation set. For example, annotations defining individual cortical layers in cortical region  R (R1, R2/3, R4, etc) can be combined to define the parent region R.",
                "properties": {
                    "subject_parcellation_annotation": {
                        "anyOf": [
                            {
                                "$ref": "#/$defs/ParcellationAnnotation"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation annotation that is the subject of the association.",
                        "type": "string"
                    },
                    "subject_parcellation_term": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation term that is the subject of the association.",
                        "type": "string"
                    }
                },
                "required": [
                    "subject_parcellation_term",
                    "subject_parcellation_annotation"
                ],
                "title": "ParcellationAnnotationTermMap",
                "type": "object"
            },
            "ParcellationAtlas": {
                "additionalProperties": false,
                "description": "A parcellation atlas is a versioned release reference used to guide experiments or deal with the spatial relationship between  objects or the location of objects within the context of some anatomical structure. An atlas is minimally defined by a notion  of space (either implicit or explicit) and an annotation set. Reference atlases usually have additional parts that make them  more useful in certain situations, such as a well defined coordinate system, delineations indicating the boundaries of various  regions or cell populations, landmarks, and labels and names to make it easier to communicate about well known and useful  locations (ref: ILX:0777109, RRID:SCR_023499).",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:ParcellationAtlas"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_anatomical_annotation_set": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the anatomical annotation set component of the parcellation atlas",
                        "type": "string"
                    },
                    "has_anatomical_space": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the anatomical space component of the parcellation atlas",
                        "type": "string"
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "has_parcellation_terminology": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation terminology component of the parcellation atlas",
                        "type": "string"
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "type": "string"
                    },
                    "specialization_of": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "description": "Reference to the general (non versioned) parcellation atlas for which the parcellation atlas is a specific  version release of.",
                        "type": "string"
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "version": {
                        "type": "string"
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "has_anatomical_space",
                    "has_anatomical_annotation_set",
                    "has_parcellation_terminology",
                    "version",
                    "id"
                ],
                "title": "ParcellationAtlas",
                "type": "object"
            },
            "ParcellationColorAssignment": {
                "additionalProperties": false,
                "description": "The parcellation color assignment associates hex color value to a parcellation term within a  versioned release of a color scheme. A parcellation term is uniquely denoted by a parcellation  term identifier and the parcellation terminology it belongs to.",
                "properties": {
                    "color": {
                        "description": "A string representing to hex triplet code of a color",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "part_of_parcellation_color_scheme": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation color scheme for which the color assignment is part of.",
                        "type": "string"
                    },
                    "subject_parcellation_term": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation term that is the subject of the association.",
                        "type": "string"
                    }
                },
                "required": [
                    "subject_parcellation_term",
                    "part_of_parcellation_color_scheme"
                ],
                "title": "ParcellationColorAssignment",
                "type": "object"
            },
            "ParcellationColorScheme": {
                "additionalProperties": false,
                "description": "A parcellation color scheme is a versioned release color palette that can be used to visualize a  parcellation terminology or its related parcellation annotation. A parcellation terminology may  have zero or more parcellation color schemes and each color scheme is in context of a specific  parcellation terminology, where each parcellation term is assigned a hex color value. A parcellation  color scheme is defined as a part of one and only one parcellation terminology.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:ParcellationColorScheme"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "type": "string"
                    },
                    "subject_parcellation_terminology": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation terminology for which the parcellation color scheme is in  context of.",
                        "type": "string"
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "version": {
                        "type": "string"
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "subject_parcellation_terminology",
                    "version",
                    "id"
                ],
                "title": "ParcellationColorScheme",
                "type": "object"
            },
            "ParcellationTerm": {
                "additionalProperties": false,
                "description": "A parcellation term is an individual term within a specific parcellation terminology describing a  single anatomical entity by a persistent identifier, name, symbol and description.  A parcellation  term is a unique and exclusive member of a versioned release parcellation terminology. Although term  identifiers must be unique within the context of one versioned release of a parcellation terminology,  they can be reused in different parcellation terminology versions enabling the representation of  terminology updates and modifications over time.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:ParcellationTerm"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "has_parent_parcellation_term": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "description": "Reference to the parent parcellation term for which the parcellation term is a child ( spatially part) of",
                        "type": "string"
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "ordinal": {
                        "description": "Ordinal of the parcellation term among other terms within the context of the associated  parcellation terminology.",
                        "minimum": 0,
                        "type": [
                            "integer",
                            "null"
                        ]
                    },
                    "part_of_parcellation_term_set": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation term set for which the parcellation term is part of.",
                        "type": "string"
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "symbol": {
                        "description": "Symbol representing a parcellation term.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "version": {
                        "type": "string"
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "part_of_parcellation_term_set",
                    "version",
                    "id"
                ],
                "title": "ParcellationTerm",
                "type": "object"
            },
            "ParcellationTermSet": {
                "additionalProperties": false,
                "description": "A parcellation term set is the set of parcellation terms within a specific parcellation terminology.  A parcellation term set belongs to one and only one parcellation terminology and each parcellation  term in a parcellation terminology belongs to one and only one term set.  If the parcellation terminology is a taxonomy, parcellation term sets can be used to represent  taxonomic ranks. For consistency, if the terminology does not have the notion of taxonomic ranks,  all terms are grouped into a single parcellation term set.",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:ParcellationTermSet"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "has_parent_parcellation_term_set": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "description": "Reference to the parent parcellation term set for which the parcellation term set is a child  (lower taxonomic rank) of.",
                        "type": "string"
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "ordinal": {
                        "description": "Ordinal of the parcellation term set among other term sets within the context of the  associated parcellation terminology.",
                        "minimum": 0,
                        "type": [
                            "integer",
                            "null"
                        ]
                    },
                    "part_of_parcellation_terminology": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            }
                        ],
                        "description": "Reference to the parcellation terminology for which the parcellation term set partitions.",
                        "type": "string"
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "version": {
                        "type": "string"
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "part_of_parcellation_terminology",
                    "version",
                    "id"
                ],
                "title": "ParcellationTermSet",
                "type": "object"
            },
            "ParcellationTerminology": {
                "additionalProperties": false,
                "description": "A parcellation terminology is a versioned release set of terms that can be used to label  annotations in an atlas, providing human readability and context and allowing communication  about brain locations and structural properties. Typically, a terminology is a set of  descriptive anatomical terms following a specific naming convention and/or approach to  organization scheme. The terminology may be a flat list of controlled vocabulary, a taxonomy  and partonomy, or an ontology (ref: ILX:0777107, RRID:SCR_023499)",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "bican:ParcellationTerminology"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "revision_of": {
                        "anyOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "string"
                            },
                            {
                                "type": "null"
                            }
                        ],
                        "type": "string"
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "version": {
                        "type": "string"
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "version",
                    "id"
                ],
                "title": "ParcellationTerminology",
                "type": "object"
            },
            "PhysicalEntity": {
                "additionalProperties": false,
                "description": "An entity that has material reality (a.k.a. physical essence).",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:PhysicalEntity"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "PhysicalEntity",
                "type": "object"
            },
            "Procedure": {
                "additionalProperties": false,
                "description": "A series of actions conducted in a certain order or manner",
                "properties": {
                    "category": {
                        "description": "Name of the high level ontology class in which this entity is categorized. Corresponds to the label for the biolink entity type class. In a neo4j database this MAY correspond to the neo4j label tag. In an RDF database it should be a biolink model class URI. This field is multi-valued. It should include values for ancestors of the biolink class; for example, a protein such as Shh would have category values `biolink:Protein`, `biolink:GeneProduct`, `biolink:MolecularEntity`. In an RDF database, nodes will typically have an rdf:type triples. This can be to the most specific biolink class, or potentially to a class more specific than something in biolink. For example, a sequence feature `f` may have a rdf:type assertion to a SO class such as TF_binding_site, which is more specific than anything in biolink. Here we would have categories {biolink:GenomicEntity, biolink:MolecularEntity, biolink:NamedThing}.",
                        "enum": [
                            "biolink:Procedure"
                        ],
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "deprecated": {
                        "description": "A boolean flag indicating that an entity is no longer considered current or valid.",
                        "type": [
                            "boolean",
                            "null"
                        ]
                    },
                    "description": {
                        "description": "a human-readable description of an entity",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "full_name": {
                        "description": "a long-form human readable name for a thing",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "has_attribute": {
                        "description": "connects any entity to an attribute",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    },
                    "iri": {
                        "description": "An IRI for an entity. This is determined by the id using expansion rules.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "name": {
                        "description": "A human-readable name for an attribute or entity.",
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "provided_by": {
                        "description": "The value in this node property represents the knowledge provider that created or assembled the node and all of its attributes.  Used internally to represent how a particular node made its way into a knowledge provider or graph.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "synonym": {
                        "description": "Alternate human-readable names for a thing",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "type": {
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    },
                    "xref": {
                        "description": "A database cross reference or alternative identifier for a NamedThing or edge between two NamedThings.  This property should point to a database record or webpage that supports the existence of the edge, or gives more detail about the edge. This property can be used on a node or edge to provide multiple URIs or CURIE cross references.",
                        "items": {
                            "type": "string"
                        },
                        "type": [
                            "array",
                            "null"
                        ]
                    }
                },
                "required": [
                    "id"
                ],
                "title": "Procedure",
                "type": "object"
            },
            "QuantityValue": {
                "additionalProperties": false,
                "description": "A value of an attribute that is quantitative and measurable, expressed as a combination of a unit and a numeric value",
                "properties": {
                    "has_numeric_value": {
                        "description": "connects a quantity value to a number",
                        "type": [
                            "number",
                            "null"
                        ]
                    },
                    "has_unit": {
                        "description": "connects a quantity value to a unit",
                        "type": [
                            "string",
                            "null"
                        ]
                    }
                },
                "title": "QuantityValue",
                "type": "object"
            },
            "TaxonomicRank": {
                "additionalProperties": false,
                "description": "A descriptor for the rank within a taxonomic classification. Example instance: TAXRANK:0000017 (kingdom)",
                "properties": {
                    "id": {
                        "description": "A unique identifier for an entity. Must be either a CURIE shorthand for a URI or a complete URI",
                        "type": "string"
                    }
                },
                "required": [
                    "id"
                ],
                "title": "TaxonomicRank",
                "type": "object"
            }
        },
        "$id": "https://identifiers.org/brain-bican/anatomical-structure-schema",
        "$schema": "https://json-schema.org/draft/2019-09/schema",
        "additionalProperties": true,
        "metamodel_version": "1.7.0",
        "title": "anatomical-structure-schema",
        "type": "object",
        "version": null
    }
    """


def clean_response_content(content: str) -> str:
    """
    Clean up response content to remove duplicates and artifacts especially in the streaming response.
    """
    if not content:
        return content

    content = content.strip()

    # First, handle the specific pattern you're seeing - repeated "Certainly! Here's an analysis..."
    if "Certainly! Here's an analysis" in content:
        # Find the first occurrence and everything after it
        first_occurrence = content.find("Certainly! Here's an analysis")
        if first_occurrence >= 0:
            # Take everything from the first occurrence onwards
            content = content[first_occurrence:]

            # Now remove any subsequent repetitions
            parts = content.split("Certainly! Here's an analysis")
            if len(parts) > 1:
                # Take only the first part (which includes the first occurrence)
                content = "Certainly! Here's an analysis" + parts[1]

    # Split into lines and remove duplicates
    lines = content.split('\n')
    cleaned_lines = []
    seen_lines = set()

    for line in lines:
        line = line.strip()
        if line and line not in seen_lines:
            cleaned_lines.append(line)
            seen_lines.add(line)

    # Join lines back together
    cleaned_content = '\n'.join(cleaned_lines)

    # Remove obvious duplicate patterns (like repeated sentences)
    sentences = cleaned_content.split('. ')
    unique_sentences = []
    seen_sentences = set()

    for sentence in sentences:
        sentence = sentence.strip()
        if sentence and sentence not in seen_sentences:
            unique_sentences.append(sentence)
            seen_sentences.add(sentence)

    cleaned_content = '. '.join(unique_sentences)

    # Additional aggressive cleaning for repeated content blocks
    # Look for repeated paragraphs or sections
    paragraphs = cleaned_content.split('\n\n')
    unique_paragraphs = []
    seen_paragraphs = set()

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if paragraph and paragraph not in seen_paragraphs:
            unique_paragraphs.append(paragraph)
            seen_paragraphs.add(paragraph)

    cleaned_content = '\n\n'.join(unique_paragraphs)

    # Remove any trailing incomplete sentences
    if cleaned_content.endswith('...'):
        cleaned_content = cleaned_content[:-3].strip()

    # Final check: if the content is still too long, take only the first reasonable chunk
    if len(cleaned_content) > 2000:  # If still very long, there might be hidden duplicates
        # Try to find a natural break point
        sentences = cleaned_content.split('. ')
        if len(sentences) > 10:
            # Take first 10 sentences
            cleaned_content = '. '.join(sentences[:10]) + '.'

    return cleaned_content


async def call_llm_api(system_prompt: str, user_prompt: str) -> str:
    """
    Call the OpenRouter API to generate a response /perform task.
    """
    try:
        # Get OpenRouter settings from centralized configuration
        openrouter_settings = config.get_openrouter_settings()
        
        # OpenRouter API configuration
        api_url = openrouter_settings["api_url"]
        api_key = openrouter_settings["api_key"]
        model = openrouter_settings["model"]
        service_name = openrouter_settings["service_name"]
        service_url = openrouter_settings["service_url"]
        
        logger.debug(f"API Key found: {'Yes' if api_key else 'No'}")
        logger.debug(f"API Key length: {len(api_key) if api_key else 0}")

        if not api_key:
            logger.error("OPENROUTER_API_KEY not found in environment variables")
            return "I apologize, but the LLM service is not properly configured. Please check your API key settings."

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": service_url,
            "X-Title": service_name
        }

        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.7,
            "top_p": 0.9,
            "stream": False  # Set to False for regular JSON response
        }

        response = requests.post(api_url, headers=headers, json=data, timeout=30)
        logger.debug("#" * 100)
        logger.debug(f"Response Status: {response.status_code}")
        logger.debug(f"Response Headers: {dict(response.headers)}")
        logger.debug(f"Response Text (full): {response.text}")
        logger.debug(f"Response Content: {response.content}")
        logger.debug("#" * 100)

        if response.status_code == 200:
            try:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    if content:
                        # clean the content so that it can be rendered properly in chat box
                        content = clean_response_content(content)

                    return content
                else:
                    logger.error(f"Unexpected response format: {result}")
                    return "I apologize, but I received an unexpected response format from the LLM service."
            except Exception as e:
                logger.error(f"Error parsing JSON response: {str(e)}")
                logger.debug(f"Raw response: {response.text}")
                return "I apologize, but I couldn't parse the response from the LLM service."
        else:
            logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            return f"I apologize, but there was an error communicating with the LLM service (Status: {response.status_code}). Please try again later."

    except requests.exceptions.Timeout:
        logger.error("OpenRouter API request timed out")
        return "I apologize, but the request timed out. Please try again with a shorter question or try later."
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenRouter API request failed: {str(e)}")
        return "I apologize, but there was a network error. Please check your connection and try again."
    except Exception as e:
        logger.error(f"Error calling OpenRouter API: {str(e)}")
        return "I apologize, but I encountered an unexpected error. Please try again in a moment."


QUERY_OPTIONS = [
    {
        "description": "This query gets the count of the rapid release data.",
        "query": """
            SELECT (COUNT(DISTINCT ?s) AS ?datasetCount)
            WHERE {
              GRAPH <https://www.portal.brain-bican.org/grapidrelease> {
                ?s ?p ?o .
              }
            }
            """
    },
{
        "description": "This query selects the rapid release data from the database. It selects 1000 data points from the rapid release",
        "query": """
        SELECT ?s ?p ?o
        WHERE {
          GRAPH <https://www.portal.brain-bican.org/grapidrelease> {
            ?s ?p ?o .
          }
        } Limit 1000
        """
    },
    # more queries to be added
]

async def select_query_via_llm_user_question(user_question: str) -> str:
    """
    Selects the most relevant SPARQL query for a given user question using LLM.

    Args:
        user_question (str): The natural language question from the user.

    Returns:
        str: The selected SPARQL query string.

    Raises:
        ValueError: If the LLM response is invalid or out of bounds.
    """
    descriptions = "\n".join(
        [f"{i + 1}. {q['description']}" for i, q in enumerate(QUERY_OPTIONS)]
    )

    system_prompt = (
        "You are a helpful assistant that selects the most relevant SPARQL query "
        "based on a user's natural language question."
    )

    user_prompt = f"""
Given the user's question, choose the most appropriate SPARQL query description
from the numbered list below.

User Question:
"{user_question}"

Query Descriptions:
{descriptions}

Respond with only the number corresponding to the best-matching query (e.g., "3").
Do not include any explanation or additional text.
"""

    try:
        llm_response = (await call_llm_api(system_prompt, user_prompt)).strip()
        index = int(llm_response) - 1
        if 0 <= index < len(QUERY_OPTIONS):
            return QUERY_OPTIONS[index]["query"]
        else:
            return None
    except Exception as e:
        return None


def get_data_from_graph_db(sparql_query: str) -> str:
    """
    Retrieve the data from the graph database
    """
    try:
        jwt_username = config.jwt_login_username
        jwt_password = config.jwt_login_password
        bearer_token_url = config.jwt_bearer_token_url
        logger.info("Authenticating with JWT")
        credentials = {
            "email": jwt_username,
            "password": jwt_password
        }

        login_response = requests.post(bearer_token_url, json=credentials)
        login_response.raise_for_status()
        logger.debug("JWT authentication successful")

        access_token = login_response.json().get("access_token")
        logger.info("Sending SPARQL query to graph database")
        params = {
            "sparql_query": sparql_query
        }
        req = requests.get(
            config.query_url,
            params=params,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }
        )
        
        req.raise_for_status()
        logger.debug("Graph database query successful")
        
        # Parse and format the response
        response_data = req.json()
        
        # Check if the response contains results
        if 'results' in response_data and 'bindings' in response_data['results']:
            bindings = response_data['results']['bindings']
            print("$-"*100)
            print(bindings)
            print("$-" * 100)
            
            if not bindings:
                return "No data found for the given query."
            
            # Format the results for display
            formatted_results = []
            for i, binding in enumerate(bindings, 1):
                row_data = []
                for var_name, var_value in binding.items():
                    if 'value' in var_value:
                        row_data.append(f"{var_name}: {var_value['value']}")
                
                if row_data:
                    formatted_results.append(f"Row {i}: {' | '.join(row_data)}")
            
            if formatted_results:
                return f"Query Results:\n\n" + "\n\n".join(formatted_results)
            else:
                return "Query executed successfully but no data was returned."

        
        else:
            # Handle other response formats
            return f"Query Results: {response_data}"
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error in get_data_from_graph_db: {str(e)}")
        return f"Error connecting to graph database: {str(e)}"
    except Exception as e:
        logger.error(f"Error in get_data_from_graph_db: {str(e)}")
        return f"Error retrieving data from graph database: {str(e)}"
