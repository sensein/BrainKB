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
# @File    : resource-extraction-ingest.py
# @Software: PyCharm
import fitz  # PyMuPDF
import requests
from io import BytesIO
from datetime import datetime, timezone
from fastapi import Request
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Depends
from typing import Optional
from fastapi.responses import JSONResponse
import logging
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import (download_open_access_pdf,
fetch_open_access_pdf,
upsert_structured_resources,
                         call_openrouter_llm,
                         extract_full_text_fitz)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Resource Extraction"])
@router.post("/structured-resource-extraction")
async def structured_resource_extraction(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
pdf_file: UploadFile = File(None, description="PDF file for resource extraction"),
json_file: UploadFile = File(None, description="Upload JSON file for resource extraction"),
doi: str = Form(None, description="DOI or URL for resource extraction"),
        text_content: str = Form(None, description=""),
        input_type: str = Form(..., description="")
):

    if input_type == "doi" and doi:
       pdf_bytes = fetch_open_access_pdf( doi)
       pdf_content = extract_full_text_fitz(pdf_bytes)
       response = await call_openrouter_llm(pdf_content)
    elif input_type == "pdf" and pdf_file:
        file_bytes = await pdf_file.read()
        full_text = extract_full_text_fitz(file_bytes)
        response = await call_openrouter_llm(full_text)
    elif input_type == "text" and text_content:
        response = await call_openrouter_llm(text_content)
    elif input_type == "json" and json_file:
        pass



    return JSONResponse(content={"message": response}, status_code=200)


@router.post("/save/structured-resource")
async def save_structured_resource(
        request: Request,
        user: Annotated[LoginUserIn, Depends(get_current_user)],
):
    try:
        data = await request.json()

        # Extract data from frontend
        structured_data = data.get("data", [])
        endpoint = data.get("endpoint", "")

        # Get metadata from request or set defaults
        document_name = data.get("documentName", f"structured_resource_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        processed_at = data.get("processedAt", datetime.now(timezone.utc).isoformat())
        source_type = data.get("sourceType", "unknown")
        source_content = data.get("sourceContent", "")

        input_data = {
            "data": structured_data,
            "documentName": document_name,
            "processedAt": processed_at,
            "sourceType": source_type,
            "sourceContent": source_content,
            "endpoint": endpoint,
            "user_id": user.id if hasattr(user, 'id') else None,
            "user_email": user.email if hasattr(user, 'email') else None
        }
        print("*"*100)
        print(type(input_data))
        print("*"*100)
        result = upsert_structured_resources(input_data=input_data)
        return JSONResponse(content=result, status_code=200)

    except Exception as e:
        logger.error(f"Error saving structured resource: {str(e)}")
        return JSONResponse(
            content={"error": f"Failed to save structured resource: {str(e)}"},
            status_code=500
        )