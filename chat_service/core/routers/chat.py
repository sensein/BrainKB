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
# @File    : chat.py
# @Software: PyCharm
from fastapi import Request
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Depends
from typing import Optional
import asyncio
import logging
from typing import Annotated, List, Dict, Any
from fastapi.responses import StreamingResponse
import json
from datetime import datetime
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import get_or_create_session, update_session_history, chat_sessions
from core.pydantic_models import ChatMessage, PageContext, ChatRequest, ChatResponse
from core.postgres_cache import get_cache_instance

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/chat")
async def chat(
        # user: Annotated[LoginUserIn, Depends(get_current_user)],
               request: ChatRequest, stream: bool = False):
    """
    Unified chat endpoint that processes messages and returns responses
    Supports both regular and streaming responses based on the 'stream' parameter
    """
    try:
        print("*"*100)
        print(f"Received chat request: {request.message[:100]}... (stream: {stream})")
        print("*" * 100)

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

        # Initialize cache
        try:
            cache = await get_cache_instance()
            
            # Create context for cache key generation (shared across users)
            cache_context = {
                "page_context": request.pageContext.dict() if request.pageContext else None,
                "page_content": request.pageContent,
                "selected_content": request.selectedPageContent,
                "chat_history": session_history[-5:] if session_history else []  # Last 5 messages for context
            }
            
            # Generate cache key (shared across users for better cache efficiency)
            cache_key = cache.generate_cache_key(request.message, cache_context)
            
            # Try to get cached response
            cached_entry = await cache.get(cache_key)
            if cached_entry:
                logger.info(f"Cache hit for key: {cache_key[:20]}...")
                response_content = cached_entry.cache_value
            else:
                logger.info(f"Cache miss for key: {cache_key[:20]}...")
                # Generate response based on message, context, and chat history
                response_content = generate_response(request, session_history)
                
                # Cache the response (TTL: 1 hour)
                await cache.set(cache_key, response_content, ttl=3600)
                logger.info(f"Cached response for key: {cache_key[:20]}...")
        except Exception as e:
            logger.warning(f"Cache operations failed: {str(e)}")
            # Generate response without caching
            response_content = generate_response(request, session_history)

        # Update session with new messages
        update_session_history(session_id, request.message, response_content)

        if stream:
            # Return streaming response
            async def generate_stream():
                """Generate streaming response"""
                try:
                    # Send initial connection message
                    yield f"data: {json.dumps({'type': 'connection', 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"

                    # Simulate streaming response by breaking it into chunks
                    words = response_content.split()
                    partial_response = ""

                    for i, word in enumerate(words):
                        partial_response += word + " "

                        # Send partial response every few words
                        if i % 3 == 0 or i == len(words) - 1:
                            yield f"data: {json.dumps({'type': 'partial', 'content': partial_response.strip(), 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"
                            await asyncio.sleep(0.1)  # Simulate processing time

                    # Send final complete message
                    yield f"data: {json.dumps({'type': 'complete', 'content': response_content, 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"

                    # Send session update
                    yield f"data: {json.dumps({'type': 'session_updated', 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"

                except Exception as e:
                    logger.error(f"Error in streaming response: {str(e)}")
                    yield f"data: {json.dumps({'type': 'error', 'error': str(e), 'timestamp': datetime.now().isoformat()})}\n\n"

            return StreamingResponse(
                generate_stream(),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "text/event-stream",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control"
                }
            )
        else:
            # Return regular response
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


def generate_response(request: ChatRequest, chat_history: List[Dict[str, Any]]) -> str:
    """
    Generate a contextual response based on the message, available context, and chat history
    """
    message = request.message.lower()

    # Check for specific patterns in the message
    if "hello" in message or "hi" in message:
        return "Hello! I'm your BrainKB Assistant. How can I help you today?"

    if "help" in message:
        return "I can help you with:\n- Analyzing knowledge graphs\n- Finding connections between entities\n- Exploring data patterns\n- Answering questions about your content\n\nWhat would you like to know?"

    # Check if this is a follow-up question based on chat history
    if chat_history and len(chat_history) > 0:
        # Get the last few messages for context
        recent_messages = chat_history[-6:]  # Last 3 exchanges (6 messages)

        # Check for follow-up patterns
        if any(word in message for word in ["more", "tell me more", "explain", "what about", "how about"]):
            last_assistant_message = None
            for msg in reversed(recent_messages):
                if msg["role"] == "assistant":
                    last_assistant_message = msg["content"]
                    break

            if last_assistant_message:
                if "knowledge graph" in last_assistant_message.lower():
                    return "I can provide more details about knowledge graphs. Would you like to know about:\n\n- **Entity Types**: Different types of entities in the graph\n- **Relationship Analysis**: How entities are connected\n- **Data Patterns**: Trends and patterns in the data\n- **Search Strategies**: How to find specific information\n\nWhat aspect interests you most?"

                if "analysis" in last_assistant_message.lower():
                    return "Let me provide a deeper analysis. I can help you with:\n\n- **Statistical Analysis**: Patterns and trends in your data\n- **Network Analysis**: How entities are interconnected\n- **Content Analysis**: Detailed examination of specific content\n- **Comparative Analysis**: Comparing different entities or time periods\n\nWhat type of analysis would you like me to perform?"

        # Check for clarification requests
        if any(word in message for word in ["what do you mean", "clarify", "explain that", "I don't understand"]):
            return "Let me clarify that for you. I'm here to help you explore and understand your knowledge graph data. Could you please:\n\n1. **Be more specific** about what you'd like to know\n2. **Ask a direct question** about entities, relationships, or data\n3. **Tell me what you're trying to accomplish**\n\nThis will help me provide a more targeted and helpful response."

    # Analysis and exploration queries
    if any(word in message for word in ["analyze", "analysis", "examine", "study", "investigate"]):
        if request.selectedPageContent:
            content_length = len(request.selectedPageContent)
            return f"I'll analyze the selected content ({content_length} characters). Here's what I found:\n\n- **Content Type**: Text selection\n- **Length**: {content_length} characters\n- **Analysis**: The selected content appears to be user-selected text that you want me to analyze.\n\nWhat specific aspects would you like me to focus on in this analysis?"

        if request.pageContent:
            content_length = len(request.pageContent)
            return f"I'll analyze the current page content ({content_length} characters). Here's my analysis:\n\n- **Page Type**: Knowledge Graph Dashboard\n- **Content Length**: {content_length} characters\n- **Key Topics**: Knowledge graphs, entities, relationships\n\nI can help you analyze:\n- Entity relationships\n- Data patterns\n- Connection networks\n- Knowledge structure\n\nWhat specific analysis would you like me to perform?"

        return "I can help you analyze knowledge graphs and data. To provide a detailed analysis, I need some content to work with. You can:\n\n1. **Select specific text** on the page and use the 📄 button\n2. **Enable page context** to analyze the full page\n3. **Ask specific questions** about what you want to analyze\n\nWhat would you like to analyze?"

    # Knowledge graph specific responses
    if any(word in message for word in ["knowledge", "graph", "data", "entities", "relationships"]):
        if request.pageContext and request.pageContext.entities:
            entities = request.pageContext.entities
            return f"I can help you explore the knowledge graph with these entities: {', '.join(entities)}. I can:\n\n- **Find connections** between entities\n- **Analyze relationships** and patterns\n- **Explore data** structure\n- **Identify insights** from the graph\n\nWhat specific aspect of the knowledge graph would you like to explore?"
        else:
            return "I can help you explore and analyze knowledge graph data. I can find connections, identify patterns, and provide insights about your data. What specific aspect would you like to explore?"

    # Context-aware responses
    if request.pageContext:
        page_title = request.pageContext.title or "this page"

        if "page" in message or "content" in message:
            return f"I can see you're on {page_title}. I have access to the page content and can help you analyze it. What specific questions do you have about this page?"

        if "entities" in message or "relationships" in message:
            entities = request.pageContext.entities or []
            if entities:
                return f"I can help you explore the entities on {page_title}: {', '.join(entities)}. What would you like to know about these entities?"
            else:
                return f"I can help you explore entities and relationships on {page_title}. What would you like to analyze?"

    # File/content analysis
    if request.selectedPageContent:
        content_length = len(request.selectedPageContent)
        return f"I can see you've selected {content_length} characters of content. I can help you analyze this specific content. What would you like to know about it?"

    if request.pageContent:
        content_length = len(request.pageContent)
        return f"I have access to {content_length} characters of page content. I can help you analyze this information. What would you like to explore?"

    # Default response for other queries
    return "I'm here to help you with knowledge graph analysis and data exploration. You can ask me about entities, relationships, patterns, or any specific content you'd like to analyze."


@router.get("/chat/sessions")
async def get_chat_sessions():
    """
    Get all active chat sessions (for demo purposes)
    """
    sessions_info = {}
    for session_id, session_data in chat_sessions.items():
        sessions_info[session_id] = {
            "message_count": len(session_data["messages"]),
            "created_at": session_data["created_at"],
            "last_updated": session_data["last_updated"]
        }

    return {
        "sessions": sessions_info,
        "total_sessions": len(chat_sessions)
    }


@router.get("/chat/sessions/{session_id}")
async def get_chat_session(session_id: str):
    """
    Get a specific chat session
    """
    if session_id in chat_sessions:
        return {
            "session_id": session_id,
            "messages": chat_sessions[session_id]["messages"],
            "created_at": chat_sessions[session_id]["created_at"],
            "last_updated": chat_sessions[session_id]["last_updated"]
        }
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """
    Delete a specific chat session
    """
    if session_id in chat_sessions:
        del chat_sessions[session_id]
        return {"message": f"Session {session_id} deleted"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/chat/cache/stats")
async def get_cache_stats():
    """
    Get cache statistics
    """
    try:
        cache = await get_cache_instance()
        stats = await cache.get_cache_stats()
        return {
            "cache_stats": stats,
            "message": "Cache statistics retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting cache stats: {str(e)}")


@router.delete("/chat/cache/clear")
async def clear_cache():
    """
    Clear all cache entries
    """
    try:
        cache = await get_cache_instance()
        # Get all cache keys and delete them
        # For now, we'll clear expired entries as a safe operation
        deleted_count = await cache.clear_expired()
        return {
            "message": f"Cleared {deleted_count} expired cache entries",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")


@router.delete("/chat/cache/clear-expired")
async def clear_expired_cache():
    """
    Clear only expired cache entries
    """
    try:
        cache = await get_cache_instance()
        deleted_count = await cache.clear_expired()
        return {
            "message": f"Cleared {deleted_count} expired cache entries",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.error(f"Error clearing expired cache: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error clearing expired cache: {str(e)}")


@router.get("/chat/cache/status")
async def get_cache_status():
    """
    Check cache status and health
    """
    try:
        cache = await get_cache_instance()
        status = await cache.check_cache_status()
        return {
            "cache_status": status,
            "message": "Cache status retrieved successfully"
        }
    except Exception as e:
        logger.error(f"Error getting cache status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting cache status: {str(e)}")