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


import json
from rdflib import Graph
import requests
import logging
import uuid
from datetime import datetime
from typing import Optional
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

    # Add user message
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