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
from core.file_validator import validate_file_extension, validate_mime_type
from core.file_validator import is_valid_jsonld
import json
from core.pydantic_schema import InputJSONSLdchema, InputJSONSchema, InputTextSchema, InputTurtleSchema
from core.shared import is_valid_jsonld
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload/knowledge-graph", summary="Ingest a either TTL, JSONLD files",
             dependencies=[Depends(require_scopes(["write"]))]
             )
async def ingest_kg_file(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        type: str = "file",
        posting_user: str = Form(...),
        file: UploadFile = File(...)):
    logger.info("Started ingestion operation")

    logger.debug(f"Received file: {file.filename} with type: {file.content_type}")
    if not validate_file_extension(file.filename, validation_type="kg"):
        raise HTTPException(status_code=400,
                            detail="Unsupported file extension. Supported extensions: TTL and JSONLD")

    content = await file.read()
    publish_message(content)
    logger.info("Successful ingestion operation")
    return JSONResponse(
        content={
            "message": "File uploaded successfully",
            "user": posting_user,
            "type": type,
            "filename": file.filename,
            "extension": file.filename.split('.')[-1].lower()
        })


@router.post("/upload/document", summary="Ingest a either TXT, JSON and PDF files",
             dependencies=[Depends(require_scopes(["write"]))]
             )
async def ingest_raw_file(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        type: str = "file",
        posting_user: str = Form(...),
        file: UploadFile = File(...)):
    logger.info("Started ingestion operation")

    logger.debug(f"Received file: {file.filename} with type: {file.content_type}")
    if not validate_file_extension(file.filename, validation_type="raw"):
        raise HTTPException(status_code=400,
                            detail="Unsupported file extension. Supported extensions: TXT, JSON and PDF")

    content = await file.read()
    publish_message(content)
    logger.info("Successful ingestion operation")
    return JSONResponse(
        content={
            "message": "File uploaded successfully",
            "user": posting_user,
            "type": type,
            "filename": file.filename,
            "extension": file.filename.split('.')[-1].lower()
        })


@router.post("/ingest/raw-json",
             dependencies=[Depends(require_scopes(["write"]))]
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
        publish_message(main_model_schema)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON" + str(e))

    return JSONResponse(content={"message": "Data uploaded successfully"})


@router.post("/ingest/raw-jsonld",
             dependencies=[Depends(require_scopes(["write"]))]
             )
async def ingest_raw_json(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        jsonldinput:
        Annotated[
            InputJSONSLdchema,
            Body(
                examples=[
                    {
                        "user": "testuser",
                        "kg_data": {"@context": "https://schema.org", "@type": "Person",
                                    "name": "John Doe"}
                    }
                ],
            ),
        ], ):
    try:

        json_data = jsonldinput.json()
        if is_valid_jsonld(json_data):
            publish_message(json_data)
            return JSONResponse(content={"message": "Data uploaded successfully"})
        else:
            return JSONResponse(content={"message": "Invalid format data! Please provide correct JSON-LD data."})

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON" + str(e))


@router.post("/upload/knowledge-graphs",
             summary="Batch ingest multiple files ( TTL and JSONLD)",
             status_code=status.HTTP_207_MULTI_STATUS,
             dependencies=[Depends(require_scopes(["write"]))]
             )
async def ingest_knowledge_graphs_batch(
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



    if not validate_file_extension(files[0].filename,
                                   validation_type="kg"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file extension. Supported extensions: TTL and JSONLD"
        )


    logger.info(f"Started batch ingestion operation for file type: {first_file_ext}")

    results = []
    for file in files:
        try:
            content = await file.read()

            logger.info(f"Publishing batch knowledge graphs content - {file}")

            publish_message(content)
            results.append({
                "filename": file.filename,
                "status": "success",
                "message": "File uploaded successfully"
            })

        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}")
            results.append({
                "filename": file.filename,
                "status": "failed",
                "message": f"Error processing file: {str(e)}"
            })

    logger.info(f"Completed batch ingestion operation")

    return JSONResponse(
        content={
            "posting_user": posting_user,
            "total_files": len(files),
            "successful": len([r for r in results if r["status"] == "success"]),
            "failed": len([r for r in results if r["status"] == "failed"]),
            "results": results
        }
    )


@router.post("/upload/documents",
             summary="Batch ingest multiple files (JSON, PDF and TXT)",
             status_code=status.HTTP_207_MULTI_STATUS,
             dependencies=[Depends(require_scopes(["write"]))]
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

    # Validate first file to ensure type is supported
    if not validate_mime_type(files[0].content_type):
        raise HTTPException(
            status_code=400,
            detail="Only JSON,  PDF and TEXT files are supported."
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

            publish_message(content)

            results.append({
                "filename": file.filename,
                "status": "success",
                "message": "File uploaded successfully"
            })

        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}")
            results.append({
                "filename": file.filename,
                "status": "failed",
                "message": f"Error processing file: {str(e)}"
            })

    logger.info(f"Completed batch ingestion operation")

    return JSONResponse(
        content={
            "posting_user": posting_user,
            "total_files": len(files),
            "successful": len([r for r in results if r["status"] == "success"]),
            "failed": len([r for r in results if r["status"] == "failed"]),
            "results": results
        }
    )


@router.post("/ingest/raw/text/",
             dependencies=[Depends(require_scopes(["write"]))]
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
    return JSONResponse(content={"message": "Text uploaded successfully"})
