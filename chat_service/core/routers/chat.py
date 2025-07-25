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
from datetime import datetime, timezone
import os
from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from core.shared import get_or_create_session, update_session_history, chat_sessions
from core.pydantic_models import ChatMessage, PageContext, ChatRequest, ChatResponse
from core.postgres_cache import get_cache_instance
import requests

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/chat")
async def chat(
        # user: Annotated[LoginUserIn, Depends(get_current_user)],
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
            print(f"🔍 Detected streaming from header: {auto_stream}")
        
        # Check for streaming in request body (if it exists)
        if hasattr(request, 'streaming') and request.streaming is not None:
            auto_stream = request.streaming
            print(f"🔍 Detected streaming from request body: {auto_stream}")
        
        # Check for Accept header indicating streaming
        if req and req.headers.get("accept") == "text/event-stream":
            auto_stream = True
            print(f"🔍 Detected streaming from Accept header: {auto_stream}")
        
        # Use explicit stream parameter if provided, otherwise use auto-detected
        final_stream = stream if stream is not None else auto_stream
        
        # Log query parameter detection
        if stream is not None:
            print(f"🔍 Detected streaming from query parameter: {stream}")
        
        # Log all headers for debugging
        if req:
            print(f"🔍 Request headers: {dict(req.headers)}")
            print(f"🔍 Query params: {dict(req.query_params)}")
        
        # Log request body for debugging
        print(f"🔍 Request body streaming field: {getattr(request, 'streaming', 'NOT_FOUND')}")
        print(f"🔍 Request body type: {type(request)}")
        print(f"🔍 Request body dir: {[attr for attr in dir(request) if not attr.startswith('_')]}")
        
        print("*"*100)
        print(f"Received chat request: {request.message[:100]}...")
        print(f"Stream detection: explicit={stream}, auto={auto_stream}, final={final_stream}")
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
            
            # Try to get cached response (unless force_fresh is True)
            cached_entry = None if force_fresh else await cache.get(cache_key)
            if cached_entry and not force_fresh:
                logger.info(f"Cache hit for key: {cache_key[:20]}...")
                print(f"🔍 CACHE HIT - Using cached response")
                response_content = cached_entry.cache_value
            else:
                if force_fresh:
                    logger.info(f"Force fresh response requested")
                    print(f"🔄 FORCE FRESH - Calling LLM despite cache")
                else:
                    logger.info(f"Cache miss for key: {cache_key[:20]}...")
                    print(f"🆕 CACHE MISS - Calling LLM for fresh response")
                # Generate response based on message, context, and chat history
                response_content = await generate_response(request, session_history)
                print(f"✅ LLM Response Generated: {len(response_content)} characters")
                print(f"📝 Response Preview: {response_content[:200]}...")
                
                # Ensure response content is not empty and clean
                if not response_content or response_content.strip() == "":
                    response_content = "I apologize, but I couldn't generate a response. Please try again."
                    print("⚠️ Empty response detected, using fallback message")
                else:
                    # Clean up response content using the dedicated function
                    response_content = clean_response_content(response_content)
                    print(f"✅ Cleaned response content: {len(response_content)} characters")
                
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
                    "llm_model": os.getenv('OPENROUTER_MODEL', 'openai/gpt-4'),
                    "freshness": {
                        "created_at": datetime.now().isoformat(),
                        "ttl_seconds": 3600,
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
                await cache.set(cache_key, response_content, ttl=3600, metadata=cache_metadata)
                logger.info(f"Cached response for key: {cache_key[:20]}...")
        except Exception as e:
            logger.warning(f"Cache operations failed: {str(e)}")
            # Generate response without caching
            response_content = await generate_response(request, session_history)

        # Update session with new messages
        update_session_history(session_id, request.message, response_content)

        print(f"🎯 RESPONSE TYPE: {'STREAMING' if final_stream else 'REGULAR'}")
        
        if final_stream:
            # Return streaming response
            print(f"🎯 Starting streaming response...")
            async def generate_stream():
                """Generate streaming response"""
                try:
                    print(f"🎯 Streaming: Sending connection message")
                    # Send initial connection message
                    yield f"data: {json.dumps({'type': 'connection', 'session_id': session_id, 'timestamp': datetime.now().isoformat()})}\n\n"

                    # Simulate streaming response by breaking it into chunks
                    print(f"🎯 Streaming: Response content length: {len(response_content)}")
                    print(f"🎯 Streaming: Response preview: {response_content[:100]}...")
                    
                    # Clean the response content first to remove any duplicates
                    clean_content = clean_response_content(response_content)
                    print(f"🎯 Streaming: Clean content length: {len(clean_content)}")
                    
                    # Additional check: if the content is still problematic, try a more aggressive approach
                    if len(clean_content) > 1500 or "Certainly! Here's an analysis" in clean_content:
                        print("⚠️ Content still seems problematic, applying aggressive cleaning...")
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
                            print(f"🎯 Streaming: Aggressively cleaned content length: {len(clean_content)}")
                    
                    # Split response into sentences for better streaming
                    import re
                    sentences = re.split(r'(?<=[.!?])\s+', clean_content)
                    sentences = [s.strip() for s in sentences if s.strip()]  # Remove empty sentences
                    
                    print(f"🎯 Streaming: Found {len(sentences)} sentences")
                    
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
                            print(f"🎯 Streaming: Sending partial response {i+1}/{len(sentences)} sentences")
                            print(f"🎯 Streaming: Partial content: {accumulated_content[:100]}...")
                            
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
                        print("⚠️ Content still too long, sending simplified version...")
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
                    print(f"🎯 Streaming: Error occurred: {str(e)}")
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

            # Return regular response
            response = ChatResponse(
                content=response_content,
                timestamp=datetime.now().isoformat(),
                context_used=context_info,
                session_id=session_id,
                metadata=metadata
            )

            logger.info(f"Generated response: {response_content[:100]}...")
            print(f"🎯 FINAL RESPONSE TO USER: {response_content[:300]}...")
            
            # Return just the content for frontend compatibility
            return {
                "content": response_content,
                "session_id": session_id,
                "metadata": metadata
            }

    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


def clean_response_content(content: str) -> str:
    """
    Clean up response content to remove duplicates and artifacts
    """
    if not content:
        return content
    
    content = content.strip()
    
    # First, handle the specific pattern you're seeing - repeated "Certainly! Here's an analysis..."
    if "Certainly! Here's an analysis" in content:
        # Find the first occurrence and everything after it
        first_occurrence = content.find("Certainly! Here's an analysis")
        if first_occurrence >= 0:
            # Take everything from the first occurrence onwards
            content = content[first_occurrence:]
            
            # Now remove any subsequent repetitions
            parts = content.split("Certainly! Here's an analysis")
            if len(parts) > 1:
                # Take only the first part (which includes the first occurrence)
                content = "Certainly! Here's an analysis" + parts[1]
    
    # Split into lines and remove duplicates
    lines = content.split('\n')
    cleaned_lines = []
    seen_lines = set()
    
    for line in lines:
        line = line.strip()
        if line and line not in seen_lines:
            cleaned_lines.append(line)
            seen_lines.add(line)
    
    # Join lines back together
    cleaned_content = '\n'.join(cleaned_lines)
    
    # Remove obvious duplicate patterns (like repeated sentences)
    sentences = cleaned_content.split('. ')
    unique_sentences = []
    seen_sentences = set()
    
    for sentence in sentences:
        sentence = sentence.strip()
        if sentence and sentence not in seen_sentences:
            unique_sentences.append(sentence)
            seen_sentences.add(sentence)
    
    cleaned_content = '. '.join(unique_sentences)
    
    # Additional aggressive cleaning for repeated content blocks
    # Look for repeated paragraphs or sections
    paragraphs = cleaned_content.split('\n\n')
    unique_paragraphs = []
    seen_paragraphs = set()
    
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if paragraph and paragraph not in seen_paragraphs:
            unique_paragraphs.append(paragraph)
            seen_paragraphs.add(paragraph)
    
    cleaned_content = '\n\n'.join(unique_paragraphs)
    
    # Remove any trailing incomplete sentences
    if cleaned_content.endswith('...'):
        cleaned_content = cleaned_content[:-3].strip()
    
    # Final check: if the content is still too long, take only the first reasonable chunk
    if len(cleaned_content) > 2000:  # If still very long, there might be hidden duplicates
        # Try to find a natural break point
        sentences = cleaned_content.split('. ')
        if len(sentences) > 10:
            # Take first 10 sentences
            cleaned_content = '. '.join(sentences[:10]) + '.'
    
    return cleaned_content


async def generate_response(request: ChatRequest, chat_history: List[Dict[str, Any]]) -> str:
    """
    Generate a contextual response using an LLM based on the message, available context, and chat history
    """
    try:
        print("*"*100)
        print("Generating--llm")
        print("*" * 100)

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

        # Prepare the prompt for the LLM
        system_prompt = """You are BrainKB Assistant, an AI-powered chat service specialized in knowledge graph analysis and data exploration. 

Your capabilities include:
- Analyzing knowledge graphs and entity relationships
- Exploring data patterns and connections
- Providing insights from content and context
- Answering questions about entities, relationships, and data structures
- Helping users navigate and understand complex information

Always provide helpful, accurate, and contextual responses. If you don't have enough information to provide a detailed answer, ask clarifying questions or suggest what additional context would be helpful."""

        user_prompt = f"""Context Information:
{full_context}

User Message: {request.message}

Please provide a helpful response based on the user's message and the available context. If the user is asking about knowledge graphs, entities, relationships, or data analysis, focus on those topics. Be conversational but informative."""

        # Call the LLM API (you can replace this with your preferred LLM service)
        print("About to call LLM API...")
        llm_response = await call_llm_api(system_prompt, user_prompt)
        print(f"LLM Response received: {llm_response[:200]}...")

        # Clean the response to remove any duplicates or artifacts
        cleaned_response = clean_response_content(llm_response)
        print(f"Cleaned response: {cleaned_response[:200]}...")
        
        # Log if there was significant cleaning
        if len(cleaned_response) != len(llm_response):
            print(f"⚠️ Response was cleaned: {len(llm_response)} -> {len(cleaned_response)} characters")
            print(f"Original preview: {llm_response[:100]}...")
            print(f"Cleaned preview: {cleaned_response[:100]}...")

        return cleaned_response

    except Exception as e:
        logger.error(f"Error generating LLM response: {str(e)}")
        # Fallback to a simple response
        return f"I apologize, but I encountered an error while processing your request. Please try again or rephrase your question. Error: {str(e)}"


async def call_llm_api(system_prompt: str, user_prompt: str) -> str:
    """
    Call the OpenRouter API to generate a response
    OpenRouter provides access to multiple LLM models through a single API
    """
    try:
        import os
        
        # OpenRouter API configuration
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = os.getenv('OPENROUTER_API_KEY')
        print(f"API Key found: {'Yes' if api_key else 'No'}")
        print(f"API Key length: {len(api_key) if api_key else 0}")
        
        if not api_key:
            logger.error("OPENROUTER_API_KEY not found in environment variables")
            return "I apologize, but the LLM service is not properly configured. Please check your API key settings."
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://brainkb.com",  # Your application URL
            "X-Title": "BrainKB Chat Service"  # Your application name
        }
        
        # You can choose different models available through OpenRouter
        # Popular options: gpt-4, gpt-3.5-turbo, claude-3-sonnet, claude-3-haiku, etc.
        model = os.getenv('OPENROUTER_MODEL', 'openai/gpt-4')  # Default to GPT-4
        print(f"Using model: {model}")
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.7,
            "top_p": 0.9,
            "stream": False  # Set to False for regular JSON response
        }
        
        # Make the API call
        print(f"Making request to: {api_url}")
        print(f"Headers: {headers}")
        print(f"Data: {data}")
        
        response = requests.post(api_url, headers=headers, json=data, timeout=30)
        print("#"*100)
        print(f"Response Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"Response Text (full): {response.text}")
        print(f"Response Content: {response.content}")
        print("#" * 100)
        
        if response.status_code == 200:
            try:
                result = response.json()
                print(f"Parsed JSON: {result}")
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    print(f"Generated content: {content[:200]}...")
                    
                    # Clean up the content to remove any artifacts
                    if content:
                        content = clean_response_content(content)
                    
                    return content
                else:
                    logger.error(f"Unexpected response format: {result}")
                    return "I apologize, but I received an unexpected response format from the LLM service."
            except Exception as e:
                logger.error(f"Error parsing JSON response: {str(e)}")
                print(f"Raw response: {response.text}")
                return "I apologize, but I couldn't parse the response from the LLM service."
        else:
            logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
            return f"I apologize, but there was an error communicating with the LLM service (Status: {response.status_code}). Please try again later."

    except requests.exceptions.Timeout:
        logger.error("OpenRouter API request timed out")
        return "I apologize, but the request timed out. Please try again with a shorter question or try later."
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenRouter API request failed: {str(e)}")
        return "I apologize, but there was a network error. Please check your connection and try again."
    except Exception as e:
        logger.error(f"Error calling OpenRouter API: {str(e)}")
        return "I apologize, but I encountered an unexpected error. Please try again in a moment."


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


@router.get("/chat/cache/debug")
async def debug_cache():
    """
    Debug cache status and contents
    """
    try:
        cache = await get_cache_instance()
        stats = await cache.get_cache_stats()
        
        # Try to get some sample cache entries
        sample_entries = await cache.get_sample_entries(5)
        
        # Get cache keys
        cache_keys = await cache.get_cache_keys(10)
        
        # Get cache status
        cache_status = await cache.check_cache_status()
        
        return {
            "cache_stats": stats,
            "sample_entries": sample_entries,
            "cache_keys": cache_keys,
            "cache_status": cache_status,
            "message": "Cache debug information retrieved"
        }
    except Exception as e:
        logger.error(f"Error getting cache debug info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting cache debug info: {str(e)}")


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


@router.delete("/chat/cache/delete/{cache_key}")
async def delete_cache_entry(cache_key: str):
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


@router.delete("/chat/cache/delete-pattern/{pattern}")
async def delete_cache_by_pattern(pattern: str):
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


@router.get("/test/stream")
async def test_stream():
    """
    Simple test endpoint for streaming
    """
    async def generate_test_stream():
        yield f"data: {json.dumps({'type': 'connection', 'message': 'Test connection established'})}\n\n"
        await asyncio.sleep(0.1)
        
        for i in range(5):
            yield f"data: {json.dumps({'type': 'partial', 'content': f'Test message {i+1}', 'progress': f'{i+1}/5'})}\n\n"
            await asyncio.sleep(0.5)
        
        yield f"data: {json.dumps({'type': 'complete', 'content': 'Test streaming completed successfully!', 'final': True})}\n\n"
    
    return StreamingResponse(
        generate_test_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )


@router.get("/test/stream/duplicate")
async def test_stream_duplicate():
    """
    Test endpoint that simulates the duplicate content issue
    """
    async def generate_test_stream():
        yield f"data: {json.dumps({'type': 'connection', 'message': 'Test connection established'})}\n\n"
        await asyncio.sleep(0.1)
        
        # Simulate the problematic content
        problematic_content = "Certainly! Here's an analysis of the page content with a focus on knowledge graphs, entities, and relationships: 1.Certainly! Here's an analysis of the page content with a focus on knowledge graphs, entities, and relationships: 1. Entities Identified: Person Organization Location Barcoded Cell Sample Library Aliquot Library Pool Fastq File 2. Relationships and Data Structure: The content describes how biological samples (specifically, libraries and their aliquots) are tracked and analyzed: Library Aliquot is a sub-portion of a larger Library.Certainly! Here's an analysis of the page content with a focus on knowledge graphs, entities, and relationships: 1. Entities Identified: Person Organization Location Barcoded Cell Sample Library Aliquot Library Pool Fastq File 2. Relationships and Data Structure: The content describes how biological samples (specifically, libraries and their aliquots) are tracked and analyzed: Library Aliquot is a sub-portion of a larger Library."
        
        # Clean the content
        cleaned_content = clean_response_content(problematic_content)
        
        # Stream the cleaned content
        sentences = cleaned_content.split('. ')
        accumulated_content = ""
        last_sent_content = ""
        
        for i, sentence in enumerate(sentences):
            if accumulated_content:
                accumulated_content += " " + sentence
            else:
                accumulated_content = sentence
            
            if i % 2 == 0 or i == len(sentences) - 1:
                if (accumulated_content and 
                    len(accumulated_content) > 10 and 
                    accumulated_content != last_sent_content and
                    accumulated_content != cleaned_content):
                    
                    yield f"data: {json.dumps({'type': 'partial', 'content': accumulated_content})}\n\n"
                    last_sent_content = accumulated_content
                    await asyncio.sleep(0.3)
        
        yield f"data: {json.dumps({'type': 'complete', 'content': cleaned_content, 'final': True})}\n\n"
    
    return StreamingResponse(
        generate_test_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )


@router.post("/test/clean")
async def test_clean_content(request: dict):
    """
    Test endpoint to test the cleaning function directly
    """
    content = request.get("content", "")
    original_length = len(content)
    
    cleaned_content = clean_response_content(content)
    cleaned_length = len(cleaned_content)
    
    return {
        "original_length": original_length,
        "cleaned_length": cleaned_length,
        "original_content": content[:500] + "..." if len(content) > 500 else content,
        "cleaned_content": cleaned_content[:500] + "..." if len(cleaned_content) > 500 else cleaned_content,
        "reduction_percentage": round((original_length - cleaned_length) / original_length * 100, 2) if original_length > 0 else 0
    }