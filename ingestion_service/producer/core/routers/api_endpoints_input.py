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
# @File    : api_endpoints_input.py
# @Software: PyCharm

from fastapi import APIRouter, HTTPException, Body, Depends
from fastapi import File, Form, UploadFile, status
from typing import List
from fastapi.responses import JSONResponse
from core.configure_rabbit_mq import publish_message
import logging
from core.file_validator import validate_file_extension
from core.file_validator import is_valid_jsonld
import json
from core.pydantic_schema import InputJSONSLdchema, InputJSONSchema, InputTextSchema
from core.shared import is_valid_jsonld
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import convert_to_turtle
from core.shared import named_graph_exists

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ingest/raw-text",
             dependencies=[Depends(require_scopes(["write"]))],
             include_in_schema=False
             )
async def ingest_text(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        text:
        Annotated[
            InputTextSchema,
            Body(
                examples=[
                    {
                        "user": "U123r",
                        "type": "text",
                        "date_created": "2024-04-30T12:42:32.203447",
                        "date_modified": "2024-04-30T12:42:32.203451",
                        "text_data": "Lorem ipsum odor amet, consectetuer adipiscing elit. Scelerisque nostra potenti erat vivamus facilisis netus; egestas hac. Ullamcorper vivamus maecenas conubia nam dui felis at eu. Ac a fames velit penatibus adipiscing. Pulvinar imperdiet habitasse sed taciti venenatis posuere augue. Duis dolor massa curae interdum habitant ultrices aliquam adipiscing aliquet. Sapien eu parturient at curabitur ac ullamcorper suspendisse. Molestie imperdiet in turpis sit ullamcorper risus ipsum aliquet elit. Magnis libero cras potenti litora arcu nunc? Rhoncus enim ipsum cras sit semper accumsan. Tempor aliquam amet massa pharetra tristique metus imperdiet. Arcu vestibulum ex dapibus posuere augue conubia nullam faucibus. Erat sodales rhoncus tincidunt nascetur lacus neque. Lectus ante consequat ex ligula vel imperdiet. Natoque sollicitudin quam pretium; nibh duis malesuada. Consectetur augue tellus eget ligula class accumsan? Auctor id semper purus dignissim; montes posuere velit. Donec tempor tempus etiam litora integer. Viverra quam senectus ac, et dapibus inceptos adipiscing montes auctor. Integer convallis nisi himenaeos aliquet lacinia sodales. Eleifend nascetur viverra per libero a neque. Sagittis lorem ligula fusce elit blandit magnis turpis hendrerit. Blandit quisque etiam diam quisque vivamus. Conubia hac elementum porta dis hendrerit conubia sit. Cursus penatibus ridiculus arcu turpis mi vitae nostra. Vulputate blandit dui quam nibh congue curae magnis. Ridiculus sapien vel senectus augue tellus massa. Eu laoreet etiam placerat lobortis convallis metus efficitur metus. Laoreet non dui placerat nec magna. Conubia etiam in tellus vestibulum convallis erat. Orci elit volutpat felis dui venenatis nisi malesuada nec. Non dapibus suspendisse vitae inceptos viverra tellus eu. Ante volutpat enim interdum non pellentesque. Felis est curae maximus placerat eleifend phasellus quam in. Tortor senectus dictum proin aptent; tortor bibendum rhoncus. Varius nam semper nisi mus varius justo ridiculus. Molestie fusce etiam tellus diam fames. Sagittis orci ex efficitur, taciti sapien consequat condimentum viverra."
                    }
                ],
            ),
        ], ):
    text_data = text.json()
    publish_message(text_data)
    return JSONResponse(content={"message": "Text uploaded successfully to messaging server"})


@router.post("/ingest/raw-json",
             dependencies=[Depends(require_scopes(["write"]))],
             include_in_schema=False
             )
async def ingest_json(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        jsoninput: Annotated[
            InputJSONSchema,
            Body(
                examples=[
                    {
                        "user": "U123r",
                        "date_created": "2024-04-30T12:42:32.203447",
                        "date_modified": "2024-04-30T12:42:32.203451",
                        "type": "raw-json",
                        "json_data": {

                            "neuroscience_disorders": [
                                {
                                    "disorder": "Alzheimer's disease",
                                    "description": "A progressive neurodegenerative disorder that leads to memory loss and cognitive decline.",
                                    "symptoms": ["Memory loss", "Confusion",
                                                 "Trouble with language and reasoning"],
                                    "treatments": ["Medications (e.g., cholinesterase inhibitors)",
                                                   "Cognitive therapy"]
                                },
                                {
                                    "disorder": "Parkinson's disease",
                                    "description": "A neurodegenerative disorder characterized by tremors, rigidity, and difficulty with movement.",
                                    "symptoms": ["Tremors", "Bradykinesia", "Postural instability"],
                                    "treatments": ["Levodopa", "Deep brain stimulation (DBS)"]
                                },
                                {
                                    "disorder": "Schizophrenia",
                                    "description": "A chronic and severe mental disorder that affects how a person thinks, feels, and behaves.",
                                    "symptoms": ["Hallucinations", "Delusions", "Disorganized thinking"],
                                    "treatments": ["Antipsychotic medications", "Psychotherapy"]
                                }
                            ]

                        }
                    }
                ],
            ),
        ], ):
    try:
        main_model_schema = jsoninput.json()
        serialized_message_json = json.dumps(main_model_schema)
        encoded_message_json = serialized_message_json.encode('utf-8')
        publish_message(encoded_message_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON" + str(e))

    return JSONResponse(content={"message": "Data uploaded successfully to messaging server"})


@router.post("/ingest/raw-jsonld",
             dependencies=[Depends(require_scopes(["write"]))]
             )
async def ingest_raw_jsonld(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        jsonldinput:
        Annotated[
            InputJSONSLdchema,
            Body(
                examples=[
                    {
                        "user": "testuser",
                        "graph":"https://example.com/",
                        "kg_data": {
                            "@context": {
                                "bican": "https://identifiers.org/brain-bican/vocab/",
                                "biolink": "https://w3id.org/biolink/vocab/",
                                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                                "schema1": "http://schema.org/",
                                "NCBIGene": "http://identifiers.org/ncbigene/",
                                "label": "rdfs:label",
                                "identifier": "schema1:identifier",
                                "molecular_type": "bican:molecular_type",
                                "referenced_in": {
                                    "@id": "bican:referenced_in",
                                    "@type": "@id"
                                },
                                "category": {
                                    "@id": "biolink:category",
                                    "@type": "@id"
                                },
                                "in_taxon": {
                                    "@id": "biolink:in_taxon",
                                    "@type": "@id"
                                },
                                "in_taxon_label": "biolink:in_taxon_label",
                                "symbol": "biolink:symbol",
                                "xref": {
                                    "@id": "biolink:xref",
                                    "@type": "@id"
                                }
                            },
                            "@id": "bican:000015fd3d6a449b47e75651210a6cc74fca918255232c8af9e46d077034c84d",
                            "@type": "bican:GeneAnnotation",
                            "label": "LOC106504536",
                            "identifier": "106504536",
                            "molecular_type": "protein_coding",
                            "referenced_in": "bican:d5c45501b3b8e5d8b5b5ba0f4d72750d8548515c1b00c23473a03a213f15360a",
                            "category": "bican:GeneAnnotation",
                            "in_taxon": "bican:7d54dfcbd21418ea26d9bfd51015414b6ad1d3760d09672afc2e1e4e6c7da1dd",
                            "in_taxon_label": "Sus scrofa",
                            "symbol": "LOC106504536",
                            "xref": "NCBIGene:106504536"
                        }

                    }
                ],
            ),
        ], ):
    try:

        json_data = jsonldinput.json()
        if is_valid_jsonld(json_data):
            dict_procesable_jsonld = json.loads(json_data)
            named_graph_iri = named_graph_exists(dict_procesable_jsonld.get("graph"))


            if named_graph_iri["status"]==True:
                turtle_representation = convert_to_turtle(dict_procesable_jsonld.get("kg_data", {}))
                if turtle_representation:
                    dict_procesable_jsonld["data_type"] = "ttl"
                    dict_procesable_jsonld["named_graph"] = named_graph_iri["formatted_iri"]
                    dict_procesable_jsonld["kg_data"] = turtle_representation
                else:
                    logger.warning("Conversion to Turtle failed. Data remains unchanged.")

                serialized_message = json.dumps(dict_procesable_jsonld)
                encoded_message = serialized_message.encode('utf-8')
                publish_message(encoded_message)
                return JSONResponse(content={"message": "Data uploaded successfully to messaging server"})
            else:
                return JSONResponse(content={"message": named_graph_iri["message"]})
        else:
            return JSONResponse(content={"message": "Invalid format data! Please provide correct JSON-LD data."})

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON" + str(e))

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@router.post("/upload/knowledge-graph", summary="Ingest a either TTL, JSONLD files",
             dependencies=[Depends(require_scopes(["write"]))]
             )
async def ingest_kg_file(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        posting_user: str = Form(...),
        graph: str = Form(...),
        file: UploadFile = File(...)):
    """
    Handles ingestion of knowledge graph (KG) files in TTL or JSON-LD format.
    """
    logger.info("Started ingestion operation")
    logger.debug(f"Received file: {file.filename} with type: {file.content_type}")

    # Validate file extension
    if not validate_file_extension(file.filename, validation_type="kg"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file extension. Supported extensions: TTL and JSONLD"
        )
    named_graph_iri = named_graph_exists(graph)
    if named_graph_iri["status"] != True:
        return JSONResponse(content={"message": named_graph_iri["message"]})

    try:
        content = await file.read()
        file_extension = file.filename.split('.')[-1].lower()

        if file_extension == "jsonld":
            logger.debug("Processing JSON-LD file")
            dict_processable_jsonld = {"user": posting_user, "data_type": "ttl",
                                       "named_graph":named_graph_iri["formatted_iri"]}
            json_data = content.decode("utf-8")

            # Convert JSON-LD to Turtle format
            turtle_representation = convert_to_turtle(json.loads(json_data))
            if turtle_representation:
                dict_processable_jsonld["kg_data"] = turtle_representation
                serialized_message = json.dumps(dict_processable_jsonld)
                encoded_message = serialized_message.encode('utf-8')

                publish_message(encoded_message)
                logger.info("JSON-LD file ingested successfully")
                return JSONResponse(
                    content={
                        "message": "File uploaded successfully to messaging server",
                        "user": posting_user,
                        "filename": file.filename,
                        "extension": file_extension
                    }
                )
            else:
                logger.error("Failed to convert JSON-LD to Turtle")
                return JSONResponse(
                    content={"message": "Unable to process JSON-LD file"},
                    status_code=400
                )
        elif file_extension == "ttl":
            logger.debug("Processing TTL file")
            formatted_ttl_data = {
                "user": posting_user,
                "data_type": "ttl",
                "named_graph": named_graph_iri["formatted_iri"],
                "kg_data": content.decode("utf-8")
            }
            serialized_message_ttl = json.dumps(formatted_ttl_data)
            encoded_message_ttl = serialized_message_ttl.encode('utf-8')
            publish_message(encoded_message_ttl)
            logger.info("TTL file ingested successfully")
            return JSONResponse(
                content={
                    "message": "File uploaded successfully to messaging server",
                    "user": posting_user,
                    "filename": file.filename,
                    "extension": file_extension
                }
            )
        else:
            logger.error("Unsupported file extension encountered after validation")
            raise HTTPException(status_code=500, detail="Unexpected file extension")
    except Exception as e:
        logger.exception(f"An error occurred during file ingestion: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/upload/knowledge-graphs",
             summary="Batch ingest multiple files ( TTL and JSONLD)",
             status_code=status.HTTP_207_MULTI_STATUS,
             dependencies=[Depends(require_scopes(["write"]))]
             )
async def ingest_knowledge_graphs_batch(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        files: List[UploadFile] = File(...),
        posting_user: str = Form(...),
        graph: str = Form(...)

):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    named_graph_iri = named_graph_exists(graph)
    if named_graph_iri["status"] != True:
        return JSONResponse(content={"message": named_graph_iri["message"]})

    # Validate all files are of the same type
    first_file_ext = files[0].filename.split('.')[-1].lower()
    if not all(f.filename.split('.')[-1].lower() == first_file_ext for f in files):
        raise HTTPException(
            status_code=400,
            detail=f"All files in a batch must be of the same type. Expected: {first_file_ext}"
        )

    if not validate_file_extension(files[0].filename, validation_type="kg"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file extension. Supported extensions: TTL and JSONLD"
        )

    logger.info(f"Started batch ingestion operation for file type: {first_file_ext}")

    results = []
    for file in files:
        try:
            content = await file.read()

            if first_file_ext == "jsonld":
                # Convert JSON-LD content to Turtle
                json_data = content.decode("utf-8")
                turtle_representation = convert_to_turtle(json.loads(json_data))

                if turtle_representation:
                    formatted_data = {
                        "user": posting_user,
                        "kg_data": turtle_representation,
                        "named_graph": named_graph_iri["formatted_iri"],
                        "data_type": "ttl",
                    }

                    logger.info(f"Successfully converted JSON-LD to Turtle for file: {file.filename}")

                    serialized_message_jsonld_batch = json.dumps(formatted_data)
                    encoded_messagejsonld_batch = serialized_message_jsonld_batch.encode('utf-8')

                    publish_message(encoded_messagejsonld_batch)
                    results.append({
                        "filename": file.filename,
                        "status": "success",
                        "message": "File uploaded successfully with Turtle conversion to messaging server"
                    })
                else:
                    logger.warning(f"Failed to convert JSON-LD to Turtle for file: {file.filename}")
                    results.append({
                        "filename": file.filename,
                        "status": "failed",
                        "message": "Conversion to Turtle failed"
                    })
            elif first_file_ext == "ttl":
                # Directly process TTL files
                formatted_data = {
                    "user": posting_user,
                    "kg_data": content.decode("utf-8"),
                    "named_graph": named_graph_iri["formatted_iri"],
                    "data_type": "ttl",
                }
                serialized_message_ttl_batch = json.dumps(formatted_data)
                encoded_message_ttl_batch = serialized_message_ttl_batch.encode('utf-8')
                publish_message(encoded_message_ttl_batch)
                results.append({
                    "filename": file.filename,
                    "status": "success",
                    "message": "File uploaded successfully to messaging server"
                })
            else:
                # This shouldn't occur due to earlier validation
                logger.error(f"Unexpected file extension for file: {file.filename}", exc_info=True)
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "message": "Unsupported file extension"
                })

        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}", exc_info=True)
            results.append({
                "filename": file.filename,
                "status": "failed",
                "message": f"Error processing file: {str(e)}"
            })

    logger.info("Completed batch ingestion operation")

    return JSONResponse(
        content={
            "posting_user": posting_user,
            "total_files": len(files),
            "successful": len([r for r in results if r["status"] == "success"]),
            "failed": len([r for r in results if r["status"] == "failed"]),
            "results": results
        }
    )


@router.post("/upload/document", summary="Ingest a either TXT, JSON and PDF files",
             dependencies=[Depends(require_scopes(["write"]))],
             include_in_schema=False
             )
async def ingest_raw_file(
        user: Annotated[LoginUserIn, Depends(get_current_user)],

        posting_user: str = Form(...),
        file: UploadFile = File(...)):
    logger.info("Started ingestion operation")

    logger.debug(f"Received file: {file.filename} with type: {file.content_type}")
    if not validate_file_extension(file.filename, validation_type="raw"):
        raise HTTPException(status_code=400,
                            detail="Unsupported file extension. Supported extensions: TXT, JSON and PDF")

    content = await file.read()

    formatted_data = {
        "user": posting_user,
        "file": content.hex()
    }

    publish_message(json.dumps(formatted_data))
    logger.info("Successful ingestion operation")
    return JSONResponse(
        content={
            "message": "File uploaded successfully to messaging server",
            "user": posting_user,
            "filename": file.filename,
            "extension": file.filename.split('.')[-1].lower()
        })


@router.post("/upload/documents",
             summary="Batch ingest multiple files (JSON, PDF and TXT)",
             status_code=status.HTTP_207_MULTI_STATUS,
             dependencies=[Depends(require_scopes(["write"]))],
             include_in_schema=False
             )
async def ingest_document_batch(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        files: List[UploadFile] = File(...),
        posting_user: str = Form(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Validate all files are of the same type
    first_file_ext = files[0].filename.split('.')[-1].lower()
    if not all(f.filename.split('.')[-1].lower() == first_file_ext for f in files):
        raise HTTPException(
            status_code=400,
            detail=f"All files in a batch must be of the same type. Expected: {first_file_ext}"
        )

    if not validate_file_extension(files[0].filename):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file extension. Supported extensions: JSON,  PDF and TEXT"
        )

    logger.info(f"Started batch ingestion operation for file type: {first_file_ext}")

    results = []
    for file in files:
        try:
            content = await file.read()

            formatted_data = {
                "user": posting_user,
                "file": content.hex()
            }
            publish_message(json.dumps(formatted_data))

            results.append({
                "filename": file.filename,
                "status": "success",
                "message": "File uploaded successfully to messaging server"
            })

        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}", exc_info=True)
            results.append({
                "filename": file.filename,
                "status": "failed",
                "message": f"Error processing file: {str(e)}"
            })

    logger.info("Completed batch ingestion operation")

    return JSONResponse(
        content={
            "posting_user": posting_user,
            "total_files": len(files),
            "successful": len([r for r in results if r["status"] == "success"]),
            "failed": len([r for r in results if r["status"] == "failed"]),
            "results": results
        }
    )
