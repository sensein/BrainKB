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
# @File    : structsense.py
# @Software: PyCharm

from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Depends
from typing import Optional
import logging
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import parse_yaml_or_json
from core.pydantic_models import AgentConfig, TaskConfig, EmbedderConfig, SearchKeyConfig
from structsense import kickoff
import os
import tempfile
import shutil
import asyncio
from concurrent.futures import ThreadPoolExecutor
from core.shared import upsert_ner_annotations

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Multi-agent Systems"])

@router.post("/multiagent/process/pdf/",
             dependencies=[Depends(require_scopes(["read"]))],
             summary="Run multi-agent systems with PDF and configuration files",
             description="""
             Process a PDF file to perform the task based on configuration files using multi-agent systems.

             Required Files

             - agent_config_file: YAML file containing agent configuration
             - task_config_file: YAML file containing task configuration 
             - embedder_config_file: YAML file containing embedder configuration
             - pdf_file: PDF file to process

             Optional Files

             - knowledge_config_file: Optional YAML file containing knowledge configuration. Needed if ENABLE_KG_SOURCE is enabled.

             Environment Settings

             - ENABLE_WEIGHTSANDBIAS: Enable Weights & Biases logging (default: false)
             - ENABLE_MLFLOW: Enable MLflow logging (default: false)
             - ENABLE_KG_SOURCE: Enable Knowledge Graph source (default: false)
               Required if ENABLE_KG_SOURCE is True
                 - ONTOLOGY_DATABASE: Ontology database name (default: "Ontology_database_agent_test")
                 - WEAVIATE_API_KEY: Weaviate API key (default: "")
                 - WEAVIATE_HTTP_HOST: Weaviate HTTP host (default: localhost)
                 - WEAVIATE_HTTP_PORT: Weaviate port number (default: 8080)
                 - WEAVIATE_HTTP_SECURE: Weaviate https access if enabled (default: False)
                 - WEAVIATE_GRPC_HOST: Weaviate grpc host (default: localhost)
                 - WEAVIATE_GRPC_PORT: Weaviate grpc port number (default:50051)
                 - WEAVIATE_GRPC_SECURE: Weaviate https access if enabled (default: false)
                 - OLLAMA_API_ENDPOINT: Ollama API endpoint (default: "http://localhost:11434")
                 - OLLAMA_MODEL: Ollama model name (default: "nomic-embed-text")
            - GROBID_SERVER_URL_OR_EXTERNAL_SERVICE: Grobid server or external PDF extraction service url (default: "http://localhost:8070").
            - EXTERNAL_PDF_EXTRACTION_SERVICE: To enable external PDF = extraction service (default: "False")

             Response

             Returns the result of the StructSense pipeline processing.
             """,
             responses={
                 200: {
                     "description": "Successful response",
                     "content": {
                         "application/json": {
                             "example": {"result": "Processing completed successfully"}
                         }
                     }
                 },
                 400: {
                     "description": "Bad Request",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Required configuration file is missing"}
                         }
                     }
                 },
                 422: {
                     "description": "Validation Error",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Error parsing configuration files: Invalid YAML format"}
                         }
                     }
                 },
                 500: {
                     "description": "Server Error",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Kickoff error: An unexpected error occurred"}
                         }
                     }
                 }
             })
async def run_structsense_with_pdf(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        agent_config_file: UploadFile = File(..., description="YAML file containing agent configuration"),
        task_config_file: UploadFile = File(..., description="YAML file containing task configuration"),
        embedder_config_file: UploadFile = File(..., description="YAML file containing embedder configuration"),
        knowledge_config_file: Optional[UploadFile] = File(None,
                                                           description="Optional YAML file containing knowledge configuration"),
        pdf_file: UploadFile = File(..., description="PDF file to process"),

        ENABLE_WEIGHTSANDBIAS: bool = Form(False, description="Enable Weights & Biases logging"),
        ENABLE_MLFLOW: bool = Form(False, description="Enable MLflow logging"),
        ENABLE_KG_SOURCE: bool = Form(False, description="Enable Knowledge Graph source"),
        ONTOLOGY_DATABASE: str = Form("Ontology_database_agent_test", description="Ontology database name"),
        WEAVIATE_API_KEY: str = Form("", description="Weaviate API key"),
        WEAVIATE_HTTP_HOST: str = Form("localhost", description="Weaviate HTTP host"),
        WEAVIATE_HTTP_PORT: str = Form("8080", description="Weaviate Port"),
        WEAVIATE_HTTP_SECURE: str = Form("False", description="Secure access to Weaviate. Note this needs to be supported by the Weaviate deployment"),
        WEAVIATE_GRPC_HOST: str = Form("localhost", description="Weaviate GRPC host address"),
        WEAVIATE_GRPC_PORT: str = Form("50051", description="Weaviate GRPC port"),
        WEAVIATE_GRPC_SECURE: str = Form("False", description="Secure GRPC access to Weaviate if enabled in Weaviate deployment"),
        OLLAMA_API_ENDPOINT: str = Form("http://localhost:11434", description="Ollama API endpoint"),
        OLLAMA_MODEL: str = Form("nomic-embed-text", description="Ollama model name"),
        GROBID_SERVER_URL_OR_EXTERNAL_SERVICE: str = Form("http://localhost:8070", description="Grobid server url"),
        EXTERNAL_PDF_EXTRACTION_SERVICE: str = Form("False", description="Enable external PDF extraction service"),
):
    # Parse configuration files
    logger.info("=" * 50)
    logger.info("Starting StructSense API endpoint")
    logger.info("=" * 50)
    try:
        # Parse YAML files
        agent = parse_yaml_or_json(None, agent_config_file, AgentConfig)
        task = parse_yaml_or_json(None, task_config_file, TaskConfig)
        embedder = parse_yaml_or_json(None, embedder_config_file, EmbedderConfig)

        # Parse optional knowledge config file
        knowledge = None
        if knowledge_config_file:
            knowledge = parse_yaml_or_json(None, knowledge_config_file, SearchKeyConfig)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Error parsing configuration files: {str(e)}")

    # Save the uploaded PDF file to a temporary directory
    temp_dir = tempfile.mkdtemp()
    try:
        temp_pdf_path = os.path.join(temp_dir, pdf_file.filename)
        with open(temp_pdf_path, "wb") as buffer:
            shutil.copyfileobj(pdf_file.file, buffer)

        # Reset file position for potential future use
        pdf_file.file.seek(0)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"PDF extraction error: {str(e)}")

    # Inject environment variables
    os.environ["ENABLE_WEIGHTSANDBIAS"] = str(ENABLE_WEIGHTSANDBIAS).lower()
    os.environ["ENABLE_MLFLOW"] = str(ENABLE_MLFLOW).lower()
    os.environ["ENABLE_KG_SOURCE"] = str(ENABLE_KG_SOURCE).lower()
    os.environ["ONTOLOGY_DATABASE"] = ONTOLOGY_DATABASE
    os.environ["WEAVIATE_API_KEY"] = WEAVIATE_API_KEY
    os.environ["WEAVIATE_HTTP_HOST"] = WEAVIATE_HTTP_HOST
    os.environ["WEAVIATE_HTTP_PORT"] = WEAVIATE_HTTP_PORT
    os.environ["WEAVIATE_HTTP_SECURE"] = WEAVIATE_HTTP_SECURE
    os.environ["WEAVIATE_GRPC_HOST"] = WEAVIATE_GRPC_HOST
    os.environ["WEAVIATE_GRPC_PORT"] = WEAVIATE_GRPC_PORT
    os.environ["WEAVIATE_GRPC_SECURE"] = WEAVIATE_GRPC_SECURE

    os.environ["OLLAMA_API_ENDPOINT"] = OLLAMA_API_ENDPOINT
    os.environ["OLLAMA_MODEL"] = OLLAMA_MODEL
    os.environ["GROBID_SERVER_URL_OR_EXTERNAL_SERVICE"] = GROBID_SERVER_URL_OR_EXTERNAL_SERVICE
    os.environ["EXTERNAL_PDF_EXTRACTION_SERVICE"] = EXTERNAL_PDF_EXTRACTION_SERVICE

    logger.info("*"*100)
    logger.info(os.getenv("GROBID_SERVER_URL_OR_EXTERNAL_SERVICE"))
    logger.info(os.getenv("EXTERNAL_PDF_EXTRACTION_SERVICE"))
    logger.info("*" * 100)

    try:
        # Log configuration details
        logger.info(f"Agent config: {agent.model_dump()}")
        logger.info(f"PDF file saved to: {temp_pdf_path}")

        # Run kickoff in a separate thread to avoid asyncio.run() conflicts
        def run_kickoff():
            return kickoff(
                agentconfig=agent.model_dump(),
                taskconfig=task.model_dump(),
                embedderconfig=embedder.model_dump(),
                input_source=temp_pdf_path,
                knowledgeconfig=knowledge.model_dump() if knowledge else None
            )


        # Use ThreadPoolExecutor to run the kickoff function in a separate thread
        with ThreadPoolExecutor() as executor:
            result = await asyncio.get_event_loop().run_in_executor(executor, run_kickoff)

        response_ingest = upsert_ner_annotations(result, user["email"])
        return response_ingest
    except Exception as e:
        logger.error(f"StructSense kickoff error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Kickoff error: {str(e)}")
    finally:
        # Clean up the temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/multiagent/process/raw-text/",
             dependencies=[Depends(require_scopes(["read"]))],
             summary="Run multi-agent systems with raw text and configuration files",
             description="""
             Process a raw text to perform the task based on configuration files using multi-agent systems.

             Required Files

             - agent_config_file: YAML file containing agent configuration
             - task_config_file: YAML file containing task configuration
             - flow_config_file: YAML file containing flow configuration
             - embedder_config_file: YAML file containing embedder configuration
             - pdf_file: PDF file to process

             Optional Files

             - knowledge_config_file: Optional YAML file containing knowledge configuration. Needed if ENABLE_KG_SOURCE is enabled.

             Environment Settings

             - ENABLE_WEIGHTSANDBIAS: Enable Weights & Biases logging (default: false)
             - ENABLE_MLFLOW: Enable MLflow logging (default: false)
             - ENABLE_KG_SOURCE: Enable Knowledge Graph source (default: false)
               Required if ENABLE_KG_SOURCE is True
                 - ONTOLOGY_DATABASE: Ontology database name (default: "Ontology_database_agent_test")
                 - WEAVIATE_API_KEY: Weaviate API key (default: "")
                 - WEAVIATE_HTTP_HOST: Weaviate HTTP host (default: localhost)
                 - WEAVIATE_HTTP_PORT: Weaviate port number (default: 8080)
                 - WEAVIATE_HTTP_SECURE: Weaviate https access if enabled (default: False)
                 - WEAVIATE_GRPC_HOST: Weaviate grpc host (default: localhost)
                 - WEAVIATE_GRPC_PORT: Weaviate grpc port number (default:50051)
                 - WEAVIATE_GRPC_SECURE: Weaviate https access if enabled (default: False)
                 - OLLAMA_API_ENDPOINT: Ollama API endpoint (default: "http://localhost:11434")
                 - OLLAMA_MODEL: Ollama model name (default: "nomic-embed-text")
                 

             Response

             Returns the result of the StructSense pipeline processing.
             """,
             responses={
                 200: {
                     "description": "Successful response",
                     "content": {
                         "application/json": {
                             "example": {"result": "Processing completed successfully"}
                         }
                     }
                 },
                 400: {
                     "description": "Bad Request",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Required configuration file is missing"}
                         }
                     }
                 },
                 422: {
                     "description": "Validation Error",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Error parsing configuration files: Invalid YAML format"}
                         }
                     }
                 },
                 500: {
                     "description": "Server Error",
                     "content": {
                         "application/json": {
                             "example": {"detail": "Kickoff error: An unexpected error occurred"}
                         }
                     }
                 }
             })
async def run_structsense_with_raw_text(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
        agent_config_file: UploadFile = File(..., description="YAML file containing agent configuration"),
        task_config_file: UploadFile = File(..., description="YAML file containing task configuration"),
        embedder_config_file: UploadFile = File(..., description="YAML file containing embedder configuration"),
        knowledge_config_file: Optional[UploadFile] = File(None,
                                                           description="Optional YAML file containing knowledge configuration"),
        input_text: str = Form(..., description="Raw neuroscience text input."),

        ENABLE_WEIGHTSANDBIAS: bool = Form(False, description="Enable Weights & Biases logging"),
        ENABLE_MLFLOW: bool = Form(False, description="Enable MLflow logging"),
        ENABLE_KG_SOURCE: bool = Form(False, description="Enable Knowledge Graph source"),
        ONTOLOGY_DATABASE: str = Form("Ontology_database_agent_test", description="Ontology database name"),
        WEAVIATE_API_KEY: str = Form("", description="Weaviate API key"),
        WEAVIATE_HTTP_HOST: str = Form("localhost", description="Weaviate HTTP host"),
        WEAVIATE_HTTP_PORT: str = Form("8080", description="Weaviate Port"),
        WEAVIATE_HTTP_SECURE: str = Form("False",
                                          description="Secure access to Weaviate. Note this needs to be supported by the Weaviate deployment"),
        WEAVIATE_GRPC_HOST: str = Form("localhost", description="Weaviate GRPC host address"),
        WEAVIATE_GRPC_PORT: str = Form("50051", description="Weaviate GRPC port"),
        WEAVIATE_GRPC_SECURE: str = Form("False",
                                          description="Secure GRPC access to Weaviate if enabled in Weaviate deployment"),

        OLLAMA_API_ENDPOINT: str = Form("http://localhost:11434", description="Ollama API endpoint"),
        OLLAMA_MODEL: str = Form("nomic-embed-text", description="Ollama model name")
):

    try:
        # Parse YAML files
        agent = parse_yaml_or_json(None, agent_config_file, AgentConfig)
        task = parse_yaml_or_json(None, task_config_file, TaskConfig)
        embedder = parse_yaml_or_json(None, embedder_config_file, EmbedderConfig)

        # Parse optional knowledge config file
        knowledge = None
        if knowledge_config_file:
            knowledge = parse_yaml_or_json(None, knowledge_config_file, SearchKeyConfig)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Error parsing configuration files: {str(e)}")

    # Inject environment variables
    os.environ["ENABLE_WEIGHTSANDBIAS"] = str(ENABLE_WEIGHTSANDBIAS).lower()
    os.environ["ENABLE_MLFLOW"] = str(ENABLE_MLFLOW).lower()
    os.environ["ENABLE_KG_SOURCE"] = str(ENABLE_KG_SOURCE).lower()
    os.environ["ONTOLOGY_DATABASE"] = ONTOLOGY_DATABASE
    os.environ["WEAVIATE_API_KEY"] = WEAVIATE_API_KEY
    os.environ["WEAVIATE_HTTP_HOST"] = WEAVIATE_HTTP_HOST
    os.environ["WEAVIATE_HTTP_PORT"] = WEAVIATE_HTTP_PORT
    os.environ["WEAVIATE_HTTP_SECURE"] = WEAVIATE_HTTP_SECURE
    os.environ["WEAVIATE_GRPC_HOST"] = WEAVIATE_GRPC_HOST
    os.environ["WEAVIATE_GRPC_PORT"] = WEAVIATE_GRPC_PORT
    os.environ["WEAVIATE_GRPC_SECURE"] = WEAVIATE_GRPC_SECURE
    os.environ["OLLAMA_API_ENDPOINT"] = OLLAMA_API_ENDPOINT
    os.environ["OLLAMA_MODEL"] = OLLAMA_MODEL

    try:

        # Run kickoff in a separate thread to avoid asyncio.run() conflicts
        def run_kickoff():
            return kickoff(
                agentconfig=agent.model_dump(),
                taskconfig=task.model_dump(),
                embedderconfig=embedder.model_dump(),
                input_source=input_text,
                knowledgeconfig=knowledge.model_dump() if knowledge else None
            )

        # Use ThreadPoolExecutor to run the kickoff function in a separate thread
        with ThreadPoolExecutor() as executor:
            result = await asyncio.get_event_loop().run_in_executor(executor, run_kickoff)

        response_ingest = upsert_ner_annotations(result,  user["email"])
        return response_ingest
    except Exception as e:
        logger.error(f"StructSense kickoff error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Kickoff error: {str(e)}")
