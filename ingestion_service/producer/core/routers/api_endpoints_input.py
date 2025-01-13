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
# from typing import List
from fastapi.responses import JSONResponse
from core.configure_rabbit_mq import publish_message
import logging
from core.file_validator import validate_file_extension, validate_mime_type
import json
from core.pydantic_schema import InputJSONSLdchema, InputJSONSchema, InputTextSchema
from core.shared import is_valid_jsonld
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/ingest/file", summary="Ingest a either CSV, JSON, EXCEL, PDF, RDF, TTL, JSONLD or TEXT files",
             dependencies=[Depends(require_scopes(["write"]))])
async def ingest_file(user: Annotated[LoginUserIn, Depends(get_current_user)],
                      id: str = Form(...),
                      type: str = "file",
                      posting_user: str = Form(...),
                      file: UploadFile = File(...)):
    logger.info("Started ingestion operation")

    logger.debug(f"Received file: {file.filename} with type: {file.content_type}")
    if not validate_file_extension(file.filename):
        raise HTTPException(status_code=400,
                            detail="Unsupported file extension. Supported extensions: csv, json, xls, txt and pdf")

    content = await file.read()
    publish_message(content)
    logger.info("Successful ingestion operation")
    return JSONResponse(
        content={
            "message": "File uploaded successfully",
            "id": id,
            "user": posting_user,
            "type": type,
            "filename": file.filename,
            "extension": file.filename.split('.')[-1].lower()
        })

@router.post("/ingest/raw/json", dependencies=[Depends(require_scopes(["write"]))])
async def ingest_json(user: Annotated[LoginUserIn, Depends(get_current_user)],
                      jsoninput: Annotated[
                          InputJSONSchema,
                          Body(
                              examples=[
                                  {
                                      "id": "1BCD",
                                      "user": "U123r",
                                      "type": "json",
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

    return JSONResponse(content={"message": f"Data uploaded successfully {main_model_schema}"})


@router.post("/ingest/raw/jsonld")
async def ingest_json(user: Annotated[LoginUserIn, Depends(get_current_user)],
                      jsonldinput: Annotated[
                          InputJSONSLdchema,
                          Body(
                              examples=[
                                  {
                                      "type": "jsonld",
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


@router.post("/ingest/raw/text/", dependencies=[Depends(require_scopes(["write"]))])
async def ingest_text(user: Annotated[LoginUserIn, Depends(get_current_user)],
                      text:
                      Annotated[
                          InputTextSchema,
                          Body(
                              examples=[
                                  {
                                      "id": "1BCD",
                                      "user": "U123r",
                                      "type":"text",
                                      "date_created": "2024-04-30T12:42:32.203447",
                                      "date_modified": "2024-04-30T12:42:32.203451",
                                      "text_data": "This is sample text data for KGs construction"
                                  }
                              ],
                          ),
                      ], ):
    text_data = text.json()
    publish_message(text_data)
    return JSONResponse(content={"message": "File uploaded successfully"})
