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
# @File    : pydantic_models.py
# @Software: PyCharm

from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[str] = None

class PageContext(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    entities: Optional[List[str]] = None
    version: Optional[str] = "1.0"
    last_updated: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None  # Add session ID for tracking
    currentPage: Optional[str] = None
    pageContext: Optional[PageContext] = None
    pageContent: Optional[str] = None
    selectedPageContent: Optional[str] = None
    chatHistory: Optional[List[ChatMessage]] = None
    timestamp: Optional[str] = None
    streaming: Optional[bool] = None  # Frontend streaming preference

class ChatResponse(BaseModel):
    content: str
    timestamp: str
    context_used: Dict[str, Any]
    session_id: str
    metadata: Optional[Dict[str, Any]] = None