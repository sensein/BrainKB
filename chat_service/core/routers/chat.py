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
from fastapi import Request
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Depends
from typing import Optional
from fastapi.responses import JSONResponse
import logging
from typing import Annotated
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import get_or_create_session, update_session_history


logger = logging.getLogger(__name__)


@app.post("/chat")
async def chat(request: ChatRequest,
               dependencies=[Depends(require_scopes(["write"]))],
               ):
    """
    Main chat endpoint that processes messages and returns responses
    """
    try:
        logger.info(f"Received chat request: {request.message[:100]}...")

        # Get or create session
        session_id = get_or_create_session(request.session_id)

        # Get existing chat history for this session
        session_history = chat_sessions[session_id]["messages"] if session_id in chat_sessions else []

        # Log context information
        context_info = {
            "has_page_context": bool(request.pageContext),
            "has_page_content": bool(request.pageContent),
            "has_selected_content": bool(request.selectedPageContent),
            "chat_history_length": len(session_history),
            "session_id": session_id
        }

        logger.info(f"Context info: {context_info}")

        # Generate response based on message, context, and chat history
        response_content = generate_response(request, session_history)

        # Update session with new messages
        update_session_history(session_id, request.message, response_content)

        # Create response
        response = ChatResponse(
            content=response_content,
            timestamp=datetime.now().isoformat(),
            context_used=context_info,
            session_id=session_id
        )

        logger.info(f"Generated response: {response_content[:100]}...")
        return response

    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

