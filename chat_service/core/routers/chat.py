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
import re
from typing import Annotated, List, Dict, Any
from fastapi.responses import StreamingResponse
import json
from datetime import datetime, timezone
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import (get_or_create_session, update_session_history, chat_sessions, call_llm_api,
                         clean_response_content, select_query_via_llm_user_question, get_data_from_graph_db,
                         update_query_with_parameters, query_fixer)
from core.pydantic_models import ChatMessage, PageContext, ChatRequest, ChatResponse
from core.postgres_cache import get_cache_instance
from core.configuration import config


logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/chat", dependencies=[Depends(require_scopes(["write"]))],)
async def chat(
        user: Annotated[LoginUserIn, Depends(get_current_user)],
               request: ChatRequest, stream: bool = False, force_fresh: bool = False, req: Request = None):
    """
    Unified chat endpoint that processes messages and returns responses
    Supports both regular and streaming responses based on:
    1. 'stream' query parameter (explicit)
    2. 'X-Streaming' header (from frontend config)
    3. 'streaming' field in request body (from frontend config)
    """

    try:
        # Auto-detect streaming preference from multiple sources
        auto_stream = False

        # Check for streaming header
        if req and req.headers.get("X-Streaming"):
            auto_stream = req.headers.get("X-Streaming").lower() == "true"
            logger.debug(f"🔍 Detected streaming from header: {auto_stream}")

        # Check for streaming in request body (if it exists)
        if hasattr(request, 'streaming') and request.streaming is not None:
            auto_stream = request.streaming
            logger.debug(f"🔍 Detected streaming from request body: {auto_stream}")

        # Check for Accept header indicating streaming
        if req and req.headers.get("accept") == "text/event-stream":
            auto_stream = True
            logger.debug(f"🔍 Detected streaming from Accept header: {auto_stream}")

        # Use explicit stream parameter if provided, otherwise use auto-detected
        final_stream = stream if stream is not None else auto_stream

        # Log query parameter detection
        if stream is not None:
            logger.debug(f"🔍 Detected streaming from query parameter: {stream}")

        # Log all headers for debugging
        if req:
            logger.debug(f"🔍 Request headers: {dict(req.headers)}")
            logger.debug(f"🔍 Query params: {dict(req.query_params)}")

        # Log request body for debugging
        logger.debug(f"🔍 Request body streaming field: {getattr(request, 'streaming', 'NOT_FOUND')}")
        logger.debug(f"🔍 Request body type: {type(request)}")
        logger.debug(f"🔍 Request body dir: {[attr for attr in dir(request) if not attr.startswith('_')]}")

        logger.info("*"*100)
        logger.info(f"Received chat request: {request.message[:100]}...")
        logger.info(f"Stream detection: explicit={stream}, auto={auto_stream}, final={final_stream}")
        logger.info("*" * 100)

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

        # Handle simple greetings and help requests
        message_lower = request.message.lower().strip()
        
        # Greeting patterns
        greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings"]
        help_patterns = ["help", "what can you do", "how can you help", "what are your capabilities"]
        
        # Check for greetings
        if any(greeting in message_lower for greeting in greetings):
            return """Hello! 👋 I'm your BrainKB assistant, designed to help you explore and analyze biological knowledge graphs and data.

I can help you with:
• Querying donor information and metadata
• Exploring gene annotations and genome assemblies  
• Analyzing biological relationships and pathways
• Retrieving data from the BrainKB knowledge graph
• Answering questions about biological entities

Just ask me anything about the data, like:
- "Give me donor details for DO-CYPH5324"
- "Show me genome assemblies"
- "What gene annotations are available?"
- "Tell me about taxonomic entities"

How can I assist you today?"""

        # Check for help requests
        elif any(pattern in message_lower for pattern in help_patterns):
            return """I'm here to help you explore the BrainKB knowledge graph! 🧠

**What I can do:**
• **Donor Information**: Get detailed metadata about biological donors
• **Gene Data**: Explore gene annotations and their relationships
• **Genome Assemblies**: Find reference genome builds and annotations
• **Taxonomic Data**: Discover organism and species information
• **Rapid Release Data**: Access the latest biological datasets

**Example queries you can try:**
• "Give me donor details for DO-CYPH5324"
• "Show me all genome assemblies"
• "What gene annotations are available?"
• "Tell me about taxonomic entities"
• "Get rapid release data count"

**Features:**
• Intelligent query understanding and parameter extraction
• Automatic error fixing for SPARQL queries
• Streaming responses for real-time interaction
• Context-aware follow-up question handling

Just ask me anything about the biological data, and I'll help you find what you're looking for!"""

        # Check if this is a follow-up question to previous template data
        if session_id in chat_sessions and "template_data" in chat_sessions[session_id]:
            template_data = chat_sessions[session_id]["template_data"]
            
            # Check if there's stored template data
            if template_data and template_data.get("last_data"):
                stored_data = template_data["last_data"]
                user_message_lower = request.message.lower()
                
                # First, try LLM-based detection for more accurate results
                try:
                    follow_up_detection_prompt = f"""
                    Determine if the user's message is asking about or referring to the previously fetched data.
                    
                    Previous Data Context:
                    {stored_data[:500]}...
                    
                    User's Current Message:
                    {request.message}
                    
                    Answer with only 'YES' if the user is asking about the previous data, or 'NO' if they are asking about something else entirely.
                    """
                    
                    llm_follow_up_response = await call_llm_api(
                        "You are a helpful assistant that determines if a user message is referring to previously provided data. Respond with only YES or NO.",
                        follow_up_detection_prompt
                    )
                    
                    is_follow_up = llm_follow_up_response.strip().upper() == "YES"
                    
                    if is_follow_up:
                        logger.info("Detected follow-up question to previous template data")
                        # Use the stored data for follow-up analysis
                        stored_data = template_data["last_data"]
                        response_content = await handle_template_query(stored_data, session_history)
                        return response_content
                        
                except Exception as e:
                    logger.warning(f"LLM follow-up detection failed: {str(e)}")
                
                # Fallback: Check for common follow-up patterns
                follow_up_patterns = [
                    'more', 'details', 'analysis', 'insights', 'explain', 'describe',
                    'break down', 'summarize', 'overview', 'summary', 'what', 'how', 'why',
                    'tell me more', 'can you explain', 'show me', 'give me', 'what else',
                    'additional', 'further', 'deeper', 'expand', 'elaborate'
                ]
                
                # Check if the message contains follow-up indicators
                has_follow_up_indicator = any(pattern in user_message_lower for pattern in follow_up_patterns)
                
                if has_follow_up_indicator:
                    logger.info("Detected follow-up request based on patterns")
                    response_content = await handle_template_query(stored_data, session_history)
                    return response_content
                
                # Additional check: if user mentions specific entities from the stored data
                data_lower = stored_data.lower()
                data_words = set(data_lower.split())
                user_words = set(user_message_lower.split())
                common_words = data_words.intersection(user_words)
                
                # Filter for meaningful common words (more than 3 characters, not common stop words)
                stop_words = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those', 'a', 'an', 'as', 'so', 'if', 'then', 'else', 'when', 'where', 'why', 'how', 'what', 'which', 'who', 'whom', 'whose'}
                meaningful_common_words = [word for word in common_words if len(word) > 3 and word not in stop_words]
                
                # If user mentions specific entities from the data, treat as follow-up
                if len(meaningful_common_words) > 0:
                    logger.info(f"Detected follow-up based on common terms: {meaningful_common_words}")
                    response_content = await handle_template_query(stored_data, session_history)
                    return response_content

        template_query = await select_query_via_llm_user_question(request.message)
        if template_query is not None:
            """
            Before checking the cache and further processing we first wanted to check the query template. 
            The query template consists or is expected to consist some of the top queries that people requests for.
            """
            logger.info("#"*100)
            logger.info(f"fetched sparql query: {template_query}")
            logger.info("#"*100)
            
            # Update the query with parameters extracted from user message
            updated_query = await update_query_with_parameters(request.message, template_query)
            
            # Only fix the query if it's different from the template (indicating parameters were added)
            if updated_query != template_query:
                logger.info("Query updated with parameters, checking for syntax issues...")
                # Only call query_fixer if there's a specific error, not proactively
                fixed_query = updated_query  # Start with the updated query
                logger.info("#" * 100)
                print(fixed_query)
                logger.info("#" * 100)
            else:
                # No parameters were added, use the template query as-is
                fixed_query = template_query
                logger.info("Using template query as-is (no parameters added)")
            
            if fixed_query != template_query:
                logger.info(f"Updated query with parameters: {fixed_query}")
            
            # First attempt: Fetch data from graph database using the updated query
            try:
                data = await get_data_from_graph_db(fixed_query)
                print("^"*100)
                print(data)
                print("^" * 100)
            except Exception as e:
                logger.warning(f"First database query failed: {str(e)}")
                
                # Second attempt: Try to fix the query with error information and retry
                logger.info("Attempting to fix query with error context and retry...")
                error_fixed_query = await query_fixer(fixed_query, str(e))
                
                if error_fixed_query != fixed_query:
                    logger.info("Query was fixed with error context, retrying database query...")
                    try:
                        data = await get_data_from_graph_db(error_fixed_query)
                        print("^"*100)
                        print("RETRY SUCCESS:")
                        print(data)
                        print("^" * 100)
                    except Exception as retry_error:
                        logger.error(f"Retry also failed: {str(retry_error)}")
                        data = f"Database query failed after retry. Error: {str(retry_error)}"
                else:
                    logger.warning("Query fixer returned same query, using original error")
                    data = f"Database query failed. Error: {str(e)}"
            
            # Store the fetched data in session context for follow-up questions
            if session_id not in chat_sessions:
                chat_sessions[session_id] = {
                    "messages": [],
                    "created_at": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat(),
                    "template_data": {}
                }
            
            # Store the current query and data in session context
            chat_sessions[session_id]["template_data"] = {
                "last_query": template_query,
                "last_data": data
            }
            
            # Pass chat history to handle_template_query for context
            response_content = await handle_template_query(data, session_history)
            return response_content
        else:
            response_content = None
            
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

                # Try to get cached response (unless force_fresh is True)
                cached_entry = None if force_fresh else await cache.get(cache_key)
                if cached_entry and not force_fresh:
                    logger.info(f"Cache hit for key: {cache_key[:20]}...")
                    logger.debug(f"🔍 CACHE HIT - Using cached response")
                    response_content = cached_entry.cache_value
                else:
                    if force_fresh:
                        logger.info(f"Force fresh response requested")
                        logger.debug(f"🔄 FORCE FRESH - Calling LLM despite cache")
                    else:
                        logger.info(f"Cache miss for key: {cache_key[:20]}...")
                        logger.debug(f"🆕 CACHE MISS - Calling LLM for fresh response")
                    # Generate response based on message, context, and chat history
                    response_content = await generate_response(request, session_history)
                    logger.info(f"✅ LLM Response Generated: {len(response_content)} characters")
                    logger.debug(f"📝 Response Preview: {response_content[:200]}...")

                    # Ensure response content is not empty and clean
                    if not response_content or response_content.strip() == "":
                        response_content = "I apologize, but I couldn't generate a response. Please try again."

                    else:
                        # Clean up response content using the dedicated function
                        response_content = clean_response_content(response_content)


                # Prepare cache metadata with freshness info
                cache_metadata = {
                    "response_length": len(response_content),
                    "has_page_context": bool(request.pageContext),
                    "has_page_content": bool(request.pageContent),
                    "has_selected_content": bool(request.selectedPageContent),
                    "chat_history_length": len(session_history),
                    "cached_at": datetime.now().isoformat(),
                    "cache_type": "contextual_response",
                    "llm_provider": "openrouter",
                    "llm_model": config.openrouter_model,
                    "freshness": {
                        "created_at": datetime.now().isoformat(),
                        "ttl_seconds": config.cache_ttl_seconds,
                        "is_fresh": True,
                        "last_updated": datetime.now().isoformat(),
                        "update_count": 1
                    },
                    "data_context": {
                        "page_context_version": getattr(request.pageContext, 'version', '1.0') if request.pageContext else None,
                        "page_content_hash": hash(request.pageContent) if request.pageContent else None,
                        "selected_content_hash": hash(request.selectedPageContent) if request.selectedPageContent else None,
                        "session_context_hash": hash(str(session_history[-5:])) if session_history else None
                    }
                }

                # Cache the response with metadata (TTL: 1 hour)
                await cache.set(cache_key, response_content, ttl=config.cache_ttl_seconds, metadata=cache_metadata)
                logger.info(f"Cached response for key: {cache_key[:20]}...")
            except Exception as e:
                logger.warning(f"Cache operations failed: {str(e)}")
                # Generate response without caching
                try:
                    response_content = await generate_response(request, session_history)
                    # Clean the response
                    if response_content:
                        response_content = clean_response_content(response_content)
                except Exception as gen_error:
                    logger.error(f"Failed to generate response: {str(gen_error)}")
                    response_content = "I apologize, but I encountered an error while processing your request. Please try again."

        # Update session with new messages
        update_session_history(session_id, request.message, response_content)

        logger.info(f"🎯 RESPONSE TYPE: {'STREAMING' if final_stream else 'REGULAR'}")
        
        # Safety check: ensure response_content is not None
        if response_content is None:
            logger.error("Response content is None - this should not happen")
            response_content = "I apologize, but I encountered an error while processing your request. Please try again."

        if final_stream:
            # Return streaming response
            logger.info(f"🎯 Starting streaming response...")
            async def generate_stream():
                """Generate streaming response"""
                try:
                    logger.info(f"🎯 Streaming: Sending connection message")
                    # Send initial connection message
                    yield f"data: {json.dumps({'type': 'connection', 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"

                    # Clean the response content first to remove any duplicates
                    clean_content = clean_response_content(response_content)

                    # Additional check: if the content is still problematic, try a more aggressive approach
                    if len(clean_content) > 1500 or "Certainly! Here's an analysis" in clean_content:
                        logger.warning("⚠️ Content still seems problematic, applying aggressive cleaning...")
                        # Try to extract just the first meaningful section
                        if "Certainly! Here's an analysis" in clean_content:
                            # Find the first occurrence and take everything up to the next major section
                            start_idx = clean_content.find("Certainly! Here's an analysis")
                            # Look for the next major section break
                            remaining = clean_content[start_idx:]
                            # Try to find a natural ending point
                            end_markers = ["###", "##", "---", "\n\n\n"]
                            end_idx = len(remaining)
                            for marker in end_markers:
                                marker_idx = remaining.find(marker, 100)  # Start looking after first 100 chars
                                if marker_idx > 0 and marker_idx < end_idx:
                                    end_idx = marker_idx

                            clean_content = remaining[:end_idx].strip()
                            logger.info(f"🎯 Streaming: Aggressively cleaned content length: {len(clean_content)}")

                    # Split response into sentences for better streaming
                    sentences = re.split(r'(?<=[.!?])\s+', clean_content)
                    sentences = [s.strip() for s in sentences if s.strip()]  # Remove empty sentences

                    # Stream the content sentence by sentence
                    accumulated_content = ""
                    last_sent_content = ""  # Track last sent content to avoid duplicates
                    for i, sentence in enumerate(sentences):
                        # Add the current sentence to accumulated content
                        if accumulated_content:
                            accumulated_content += " " + sentence
                        else:
                            accumulated_content = sentence

                        # Send partial response every 2 sentences or at the end
                        if i % 2 == 0 or i == len(sentences) - 1:
                            logger.info(f"🎯 Streaming: Sending partial response {i+1}/{len(sentences)} sentences")
                            logger.debug(f"🎯 Streaming: Partial content: {accumulated_content[:100]}...")

                            # Only send if we have meaningful content, it's not the complete response yet, and it's different from last sent
                            if (accumulated_content and
                                len(accumulated_content) > 10 and
                                accumulated_content != last_sent_content and
                                accumulated_content != clean_content):

                                yield f"data: {json.dumps({'type': 'partial', 'content': accumulated_content, 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"
                                last_sent_content = accumulated_content
                                await asyncio.sleep(0.3)  # Slightly longer delay for better readability

                    # Get cache entry details for freshness info
                    cache_entry_details = None
                    if cached_entry:
                        try:
                            cache_entry_details = await cache.get_details(cache_key)
                        except Exception as e:
                            logger.warning(f"Could not get cache details for streaming: {str(e)}")

                    # Prepare metadata for streaming response
                    stream_metadata = {
                        "cache_hit": cached_entry is not None,
                        "response_length": len(response_content),
                        "session_message_count": len(session_history) + 1,
                        "has_page_context": bool(request.pageContext),
                        "has_page_content": bool(request.pageContent),
                        "has_selected_content": bool(request.selectedPageContent),
                        "processing_time": "real-time",
                        "model_info": {
                            "type": "contextual_response",
                            "version": "1.0.0"
                        },
                        "freshness": {
                            "is_fresh": True,
                            "cached_at": cache_entry_details.get("created_at") if cache_entry_details else None,
                            "last_accessed": cache_entry_details.get("last_hit") if cache_entry_details else None,
                            "hit_count": cache_entry_details.get("hit_count", 0) if cache_entry_details else 0,
                            "ttl_remaining": cache_entry_details.get("ttl_remaining") if cache_entry_details else None,
                            "cache_age_seconds": cache_entry_details.get("age_seconds") if cache_entry_details else None
                        },
                        "data_updates": {
                            "last_page_update": request.pageContext.last_updated if request.pageContext and hasattr(request.pageContext, 'last_updated') else None,
                            "content_freshness": "real-time",
                            "context_version": request.pageContext.version if request.pageContext and hasattr(request.pageContext, 'version') else "1.0",
                            "session_last_updated": chat_sessions[session_id]["last_updated"] if session_id in chat_sessions else None
                        },
                        "cache_status": {
                            "is_stale": False,
                            "needs_refresh": False,
                            "cache_strategy": "contextual_with_ttl"
                        }
                    }

                    # Update freshness based on cache details for streaming
                    if cache_entry_details:
                        created_at = cache_entry_details.get("created_at")
                        ttl = cache_entry_details.get("ttl", 3600)
                        if created_at:
                            try:
                                # Handle different datetime formats
                                if 'Z' in created_at:
                                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                else:
                                    created_time = datetime.fromisoformat(created_at)

                                current_time = datetime.now(timezone.utc)
                                age_seconds = (current_time - created_time).total_seconds()
                                ttl_remaining = max(0, ttl - age_seconds)

                                stream_metadata["freshness"]["cache_age_seconds"] = age_seconds
                                stream_metadata["freshness"]["ttl_remaining"] = ttl_remaining
                                stream_metadata["cache_status"]["is_stale"] = ttl_remaining <= 0
                                stream_metadata["cache_status"]["needs_refresh"] = ttl_remaining < 300
                            except Exception as e:
                                logger.warning(f"Error calculating cache age for streaming: {str(e)}")
                                stream_metadata["freshness"]["cache_age_seconds"] = None
                                stream_metadata["freshness"]["ttl_remaining"] = None

                    # Final validation: if content is still too problematic, send a simplified version
                    if len(clean_content) > 2000:
                        logger.warning("⚠️ Content still too long, sending simplified version...")
                        # Take just the first few sentences
                        sentences = clean_content.split('. ')
                        if len(sentences) > 5:
                            clean_content = '. '.join(sentences[:5]) + '.'

                    # Send final complete message with metadata
                    yield f"data: {json.dumps({'type': 'complete', 'content': clean_content, 'session_id': session_id, 'timestamp': datetime.now().isoformat(), 'metadata': stream_metadata})}\n\n"

                    # Send session update
                    yield f"data: {json.dumps({'type': 'session_updated', 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"

                except Exception as e:
                    logger.error(f"Error in streaming response: {str(e)}")
                    logger.debug(f"🎯 Streaming: Error occurred: {str(e)}")
                    yield f"data: {json.dumps({'type': 'error', 'error': str(e), 'timestamp': datetime.now().isoformat()})}\n\n"

            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control"
                }
            )
        else:
            # Get cache entry details for freshness info
            cache_entry_details = None
            if cached_entry:
                try:
                    cache_entry_details = await cache.get_details(cache_key)
                except Exception as e:
                    logger.warning(f"Could not get cache details: {str(e)}")

            # Prepare metadata for the response
            metadata = {
                "cache_hit": cached_entry is not None,
                "cache_key": cache_key[:50] + "..." if len(cache_key) > 50 else cache_key,
                "response_length": len(response_content),
                "session_message_count": len(session_history) + 1,
                "has_page_context": bool(request.pageContext),
                "has_page_content": bool(request.pageContent),
                "has_selected_content": bool(request.selectedPageContent),
                "processing_time": "real-time",
                "model_info": {
                    "type": "contextual_response",
                    "version": "1.0.0"
                },
                "freshness": {
                    "is_fresh": True,  # Always fresh for new responses
                    "cached_at": cache_entry_details.get("created_at") if cache_entry_details else None,
                    "last_accessed": cache_entry_details.get("last_hit") if cache_entry_details else None,
                    "hit_count": cache_entry_details.get("hit_count", 0) if cache_entry_details else 0,
                    "ttl_remaining": cache_entry_details.get("ttl_remaining") if cache_entry_details else None,
                    "cache_age_seconds": cache_entry_details.get("age_seconds") if cache_entry_details else None
                },
                "data_updates": {
                    "last_page_update": request.pageContext.last_updated if request.pageContext and hasattr(request.pageContext, 'last_updated') else None,
                    "content_freshness": "real-time",
                    "context_version": request.pageContext.version if request.pageContext and hasattr(request.pageContext, 'version') else "1.0",
                    "session_last_updated": chat_sessions[session_id]["last_updated"] if session_id in chat_sessions else None
                },
                "cache_status": {
                    "is_stale": False,  # Will be updated based on TTL
                    "needs_refresh": False,
                    "cache_strategy": "contextual_with_ttl"
                }
            }

            # Update freshness based on cache details
            if cache_entry_details:
                created_at = cache_entry_details.get("created_at")
                ttl = cache_entry_details.get("ttl", 3600)
                if created_at:
                    try:
                        # Handle different datetime formats
                        if 'Z' in created_at:
                            created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        else:
                            created_time = datetime.fromisoformat(created_at)

                        current_time = datetime.now(timezone.utc)
                        age_seconds = (current_time - created_time).total_seconds()
                        ttl_remaining = max(0, ttl - age_seconds)

                        metadata["freshness"]["cache_age_seconds"] = age_seconds
                        metadata["freshness"]["ttl_remaining"] = ttl_remaining
                        metadata["cache_status"]["is_stale"] = ttl_remaining <= 0
                        metadata["cache_status"]["needs_refresh"] = ttl_remaining < 300  # Refresh if less than 5 minutes left
                    except Exception as e:
                        logger.warning(f"Error calculating cache age: {str(e)}")
                        metadata["freshness"]["cache_age_seconds"] = None
                        metadata["freshness"]["ttl_remaining"] = None

            # Return just the content for frontend compatibility
            return {
                "content": response_content,
                "session_id": session_id,
                "metadata": metadata
            }

    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")



async def handle_template_query(data, chat_history: List[Dict[str, Any]] = None) -> str:
    """
    Format the data in order to display in a chat with context awareness for follow-up questions
    """
    try:
        # Prepare context from chat history for follow-up questions
        context_info = ""
        if chat_history and len(chat_history) > 0:
            # Get recent conversation context (last 3 exchanges)
            recent_history = chat_history[-6:]  # Last 3 exchanges (6 messages: 3 user + 3 assistant)
            context_info = "\n\nRecent Conversation Context:\n"
            for msg in recent_history:
                role = "User" if msg['role'] == 'user' else "Assistant"
                context_info += f"{role}: {msg['content']}\n"
        
        # Prepare the prompt for the LLM with template query
        system_prompt = """You are BrainKB Assistant — an AI-powered chat service specialized in data formatting, pattern discovery, and knowledge navigation.

            Your capabilities include:
            
            Reading and intelligently formatting data for clear and concise chat presentation
            
            Identifying data patterns, relationships, and connections
            
            Extracting and providing insights from both content and context
            
            Answering questions about entities, relationships, schemas, and data structures
            
            Helping users navigate, interpret, and understand complex datasets or knowledge graphs
            
            For any given data, your primary goals are:
            
            Format it in a way that is easy to understand in a chat environment
            
            Highlight key insights, patterns, and anomalies
            
            Enable smooth exploration of the data's structure and meaning
            
            Stay accurate, concise, and user-friendly in your responses.
            
            Important: Only give insights based on the data and do not generate anything on your own.
            
            If this is a follow-up question, use the conversation context to provide more specific and relevant answers."""

        user_prompt = f"""Data: {data}{context_info}"""
        if "error" in user_prompt.lower() or "bad request" in user_prompt.lower():
            return "Sorry, there's been some problem and that needs to be fixed from the developer side. Please try again later."
        llm_response = await call_llm_api(system_prompt, user_prompt)
        cleaned_response = clean_response_content(llm_response)
        return cleaned_response

    except Exception as e:
        logger.error(f"Error handling template query: {str(e)}")
        return f"I apologize, but I encountered an error while processing your template query. Please try again or rephrase your question. Error: {str(e)}"


async def generate_response(request: ChatRequest, chat_history: List[Dict[str, Any]]) -> str:
    """
    Generate a contextual response using an LLM based on the message, available context, and chat history
    """
    try:
        logger.info("*"*100)
        logger.info("Generating--llm")
        logger.info("*" * 100)

        # Prepare context for the LLM
        context_parts = []

        # Add page context if available
        if request.pageContext:
            context_parts.append(f"Page Title: {request.pageContext.title or 'Unknown'}")
            if request.pageContext.description:
                context_parts.append(f"Page Description: {request.pageContext.description}")
            if request.pageContext.entities:
                context_parts.append(f"Page Entities: {', '.join(request.pageContext.entities)}")
            if request.pageContext.keywords:
                context_parts.append(f"Page Keywords: {', '.join(request.pageContext.keywords)}")

        # Add page content if available
        if request.pageContent:
            context_parts.append(f"Page Content: {request.pageContent[:1000]}...")  # Limit to first 1000 chars

        # Add selected content if available
        if request.selectedPageContent:
            context_parts.append(f"Selected Content: {request.selectedPageContent}")

        # Add chat history for context
        if chat_history:
            recent_history = chat_history[-6:]  # Last 3 exchanges
            history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_history])
            context_parts.append(f"Recent Chat History:\n{history_text}")

        # Build the full context
        full_context = "\n\n".join(context_parts) if context_parts else "No additional context available."


        logger.debug("##"*100)
        logger.debug(request.message)
        logger.debug("##" * 100)

        # Prepare the prompt for the LLM
        system_prompt = """You are BrainKB Assistant, an AI-powered chat service specialized in knowledge graph analysis and data exploration. 

Your capabilities include:
- Analyzing knowledge graphs and entity relationships
- Exploring data patterns and connections
- Providing insights from content and context
- Answering questions about entities, relationships, and data structures
- Helping users navigate and understand complex information

Always provide helpful, accurate, and contextual responses. If you don't have enough information to provide a detailed answer, ask clarifying questions or suggest what additional context would be helpful.

"""


        user_prompt = f"""Context Information:
{full_context}

User Message: {request.message}

Please provide a helpful response based on the user's message and the available context. If the user is asking about knowledge graphs, entities, relationships, or data analysis, focus on those topics. Be conversational but informative."""

        # Call the LLM API (you can replace this with your preferred LLM service)
        logger.debug("About to call LLM API...")
        llm_response = await call_llm_api(system_prompt, user_prompt)
        logger.debug(f"LLM Response received: {llm_response[:200]}...")

        # Clean the response to remove any duplicates or artifacts
        cleaned_response = clean_response_content(llm_response)
        logger.debug(f"Cleaned response: {cleaned_response[:200]}...")
        
        # Log if there was significant cleaning
        if len(cleaned_response) != len(llm_response):
            logger.info(f"⚠️ Response was cleaned: {len(llm_response)} -> {len(cleaned_response)} characters")
            logger.info(f"Original preview: {llm_response[:100]}...")
            logger.info(f"Cleaned preview: {cleaned_response[:100]}...")

        return cleaned_response

    except Exception as e:
        logger.error(f"Error generating LLM response: {str(e)}")
        # Fallback to a simple response
        return f"I apologize, but I encountered an error while processing your request. Please try again or rephrase your question. Error: {str(e)}"




@router.get("/chat/sessions",  dependencies=[Depends(require_scopes(["read"]))],)
async def get_chat_sessions(user: Annotated[LoginUserIn, Depends(get_current_user)],):
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


@router.get("/chat/sessions/{session_id}", dependencies=[Depends(require_scopes(["read"]))],)
async def get_chat_session(user: Annotated[LoginUserIn, Depends(get_current_user)],
                           session_id: str):
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


@router.delete("/chat/sessions/{session_id}",
               dependencies=[Depends(require_scopes(["write"]))],)
async def delete_chat_session(user: Annotated[LoginUserIn, Depends(get_current_user)],
                              session_id: str):
    """
    Delete a specific chat session
    """
    if session_id in chat_sessions:
        del chat_sessions[session_id]
        return {"message": f"Session {session_id} deleted"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/chat/cache/stats",
            dependencies=[Depends(require_scopes(["read"]))],)
async def get_cache_stats(user: Annotated[LoginUserIn, Depends(get_current_user)],
                          ):
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


@router.delete("/chat/cache/clear",
               dependencies=[Depends(require_scopes(["write"]))],)
async def clear_cache(user: Annotated[LoginUserIn, Depends(get_current_user)],
                      ):
    """
    Clear all cache entries
    """
    try:
        cache = await get_cache_instance()
        # Get all cache keys and delete them
        # For now, we'll clear expired entries as a safe operation
        deleted_count = await cache.clear_expired()
        
        # Also try to clear all entries if possible
        try:
            # This is a more aggressive clear - you might need to implement this in your cache class
            all_cleared = await cache.clear_all()
            return {
                "message": f"Cleared {deleted_count} expired cache entries and {all_cleared} total entries",
                "deleted_count": deleted_count,
                "total_cleared": all_cleared
            }
        except:
            return {
                "message": f"Cleared {deleted_count} expired cache entries",
                "deleted_count": deleted_count,
                "note": "Only expired entries were cleared"
            }
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")


@router.delete("/chat/cache/clear-expired", dependencies=[Depends(require_scopes(["write"]))],)
async def clear_expired_cache(user: Annotated[LoginUserIn, Depends(get_current_user)],
                              ):
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


@router.delete("/chat/cache/delete/{cache_key}", dependencies=[Depends(require_scopes(["write"]))],)
async def delete_cache_entry(user: Annotated[LoginUserIn, Depends(get_current_user)],
                             cache_key: str):
    """
    Delete a specific cache entry
    """
    try:
        cache = await get_cache_instance()
        deleted = await cache.delete(cache_key)
        if deleted:
            return {
                "message": f"Deleted cache entry: {cache_key[:20]}...",
                "deleted": True
            }
        else:
            return {
                "message": f"Cache entry not found: {cache_key[:20]}...",
                "deleted": False
            }
    except Exception as e:
        logger.error(f"Error deleting cache entry: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting cache entry: {str(e)}")


@router.delete("/chat/cache/delete-pattern/{pattern}", dependencies=[Depends(require_scopes(["write"]))],)
async def delete_cache_by_pattern(user: Annotated[LoginUserIn, Depends(get_current_user)],
                                  pattern: str):
    """
    Delete cache entries matching a pattern
    """
    try:
        cache = await get_cache_instance()
        deleted_count = await cache.delete_by_pattern(pattern)
        return {
            "message": f"Deleted {deleted_count} cache entries matching pattern: {pattern}",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.error(f"Error deleting cache by pattern: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting cache by pattern: {str(e)}")


@router.get("/chat/cache/status", dependencies=[Depends(require_scopes(["read"]))],)
async def get_cache_status(user: Annotated[LoginUserIn, Depends(get_current_user)],
                           ):
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


@router.get("/chat/template-debug/{session_id}", dependencies=[Depends(require_scopes(["write"]))],)
async def debug_template_data(user: Annotated[LoginUserIn, Depends(get_current_user)],
                              session_id: str):
    """
    Debug endpoint to check template data storage for a session
    """
    try:
        if session_id in chat_sessions:
            session_data = chat_sessions[session_id]
            template_data = session_data.get("template_data", {})
            
            return {
                "session_id": session_id,
                "has_template_data": bool(template_data),
                "template_data": template_data,
                "session_created": session_data.get("created_at"),
                "last_updated": session_data.get("last_updated"),
                "message_count": len(session_data.get("messages", [])),
                "stored_query": template_data.get("last_query", "None"),
                "has_stored_data": bool(template_data.get("last_data"))
            }
        else:
            return {"error": "Session not found"}
    except Exception as e:
        logger.error(f"Error in debug_template_data: {str(e)}")
        return {"error": str(e)}

