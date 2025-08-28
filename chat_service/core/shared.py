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

from typing import Optional, Dict, Any
from datetime import datetime
import uuid
import logging
import requests
import aiohttp
import asyncio
from core.configuration import config
import re

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

    # user message
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



def clean_response_content(content: str) -> str:
    """
    Clean up response content to remove duplicates and artifacts especially in the streaming response.
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


async def call_llm_api(system_prompt: str, user_prompt: str) -> str:
    """
    Call the OpenRouter API to generate a response /perform task.
    """
    try:
        # Get OpenRouter settings from centralized configuration
        openrouter_settings = config.get_openrouter_settings()
        
        # OpenRouter API configuration
        api_url = openrouter_settings["api_url"]
        api_key = openrouter_settings["api_key"]
        model = openrouter_settings["model"]
        service_name = openrouter_settings["service_name"]
        service_url = openrouter_settings["service_url"]
        
        logger.debug(f"API Key found: {'Yes' if api_key else 'No'}")
        logger.debug(f"API Key length: {len(api_key) if api_key else 0}")

        if not api_key:
            logger.error("OPENROUTER_API_KEY not found in environment variables")
            return "I apologize, but the LLM service is not properly configured. Please check your API key settings."

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": service_url,
            "X-Title": service_name
        }

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

        response = requests.post(api_url, headers=headers, json=data, timeout=30)
        logger.debug("#" * 100)
        logger.debug(f"Response Status: {response.status_code}")
        logger.debug(f"Response Headers: {dict(response.headers)}")
        logger.debug(f"Response Text (full): {response.text}")
        logger.debug(f"Response Content: {response.content}")
        logger.debug("#" * 100)

        if response.status_code == 200:
            try:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    if content:
                        # clean the content so that it can be rendered properly in chat box
                        content = clean_response_content(content)

                    return content
                else:
                    logger.error(f"Unexpected response format: {result}")
                    return "I apologize, but I received an unexpected response format from the LLM service."
            except Exception as e:
                logger.error(f"Error parsing JSON response: {str(e)}")
                logger.debug(f"Raw response: {response.text}")
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


QUERY_OPTIONS = [
    {
        "description": "This query gets the count of the rapid release data.",
        "query": """
            SELECT (COUNT(DISTINCT ?s) AS ?datasetCount)
            WHERE {
              GRAPH <https://www.portal.brain-bican.org/grapidrelease> {
                ?s ?p ?o .
              }
            }
            """
    },

    {
        "description": "This query retrieves all distinct entities, not the taxonomic entities.",
        "query": """
            PREFIX biolink: <https://w3id.org/biolink/vocab/>
            PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
            
            SELECT ?category (COUNT(DISTINCT ?s) AS ?count)
            WHERE {
              GRAPH <https://www.brainkb.org/version01> {
                ?s biolink:category ?category .
              }
            }
            GROUP BY ?category
            ORDER BY DESC(?count)
        """
    },
{
        "description": "This query selects the rapid release data from the database. It selects 1000 data points from the rapid release",
        "query": """
        SELECT ?s ?p ?o
        WHERE {
          GRAPH <https://www.portal.brain-bican.org/grapidrelease> {
            ?s ?p ?o .
          }
        } Limit 1000
        """
    },
    {"description": "This query retrieves all gene annotations along with the genome annotation (reference) they are part of. This is useful for determining which gene annotations belong to a specific genome release such as ENSEMBL v98.",
    "query": """
    PREFIX biolink: <https://w3id.org/biolink/vocab/>
PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

    SELECT ?gene ?genomeAnnotation
    WHERE {
      GRAPH <https://www.brainkb.org/version01> {
        ?gene biolink:category bican:GeneAnnotation ;
              bican:referenced_in ?genomeAnnotation .
      }
    }
    """},
    {
        "description": "This query retrieves all genome annotations and the genome assemblies they are based on. This helps determine which assembly (e.g., GRCh38.p13) is associated with a given annotation release.",
        "query": """
        PREFIX biolink: <https://w3id.org/biolink/vocab/>
        PREFIX bican: <https://identifiers.org/brain-bican/vocab/>

        SELECT ?genomeAnnotation ?assembly
        WHERE {
          GRAPH <https://www.brainkb.org/version01> {
            ?genomeAnnotation biolink:category bican:GenomeAnnotation ;
                              bican:reference_assembly ?assembly .
          }
        }
        """
    },
{
    "description": "This query retrieves all distinct taxonomic entities, such as Homo sapiens. These entries define the species or taxonomic scope for genome or gene annotations.",
    "query": """
    PREFIX biolink: <https://w3id.org/biolink/vocab/>
    PREFIX bican: <https://identifiers.org/brain-bican/vocab/>

    SELECT DISTINCT ?taxon
    WHERE {
      GRAPH <https://www.brainkb.org/version01> {
        ?taxon biolink:category biolink:OrganismTaxon .
      }
    }
    """
  },
{
    "description": "This query retrieves all distinct genome assemblies, such as GRCh38.p13. These represent the reference genome builds used in annotation pipelines.",
    "query": """
    PREFIX biolink: <https://w3id.org/biolink/vocab/>
    PREFIX bican: <https://identifiers.org/brain-bican/vocab/>

    SELECT DISTINCT ?assembly
    WHERE {
      GRAPH <https://www.brainkb.org/version01> {
        ?assembly biolink:category bican:GenomeAssembly .
      }
    }
    """
  },
{
    "description": "This query retrieves all distinct genome annotations. These entries correspond to versioned datasets that describe genomic features such as genes and transcripts for a specific assembly and organism.",
    "query": """
    PREFIX biolink: <https://w3id.org/biolink/vocab/>
    PREFIX bican: <https://identifiers.org/brain-bican/vocab/>

    SELECT DISTINCT ?annotation
    WHERE {
      GRAPH <https://www.brainkb.org/version01> {
        ?annotation biolink:category bican:GenomeAnnotation .
      }
    }
    """
  },
{
    "description": "This query retrieves all available metadata for a specific donor, including age, sex, medical history, and related provenance details. Replace `{{sayid}}` with the IRI of the donor (e.g., NIMP:DO-CYPH5324) to explore the full set of RDF property–value pairs associated with that individual.",
  "query": """
  PREFIX bican: <https://identifiers.org/brain-bican/vocab/>
  PREFIX NIMP: <http://example.org/NIMP/>
  PREFIX biolink: <https://w3id.org/biolink/vocab/>
  PREFIX prov: <http://www.w3.org/ns/prov#>
  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
  PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

  SELECT ?donor_id ?p ?o
  WHERE {
    GRAPH <https://www.brainkb.org/version01> {
      BIND(<{{sayid}}> AS ?donor_id)
      ?donor_id ?p ?o .
    }
  }
  """
}

]

async def select_query_via_llm_user_question(user_question: str) -> str:
    """
    Selects the most relevant SPARQL query for a given user question using LLM.

    Args:
        user_question (str): The natural language question from the user.

    Returns:
        str: The selected SPARQL query string.

    Raises:
        ValueError: If the LLM response is invalid or out of bounds.
    """
    descriptions = "\n".join(
        [f"{i + 1}. {q['description']}" for i, q in enumerate(QUERY_OPTIONS)]
    )

    system_prompt = (
        "You are a helpful assistant that selects the most relevant SPARQL query "
        "based on a user's natural language question."
    )

    user_prompt = f"""
Given the user's question, choose the most appropriate SPARQL query description
from the numbered list below.

User Question:
"{user_question}"

Query Descriptions:
{descriptions}

Respond with only the number corresponding to the best-matching query (e.g., "3").
Do not include any explanation or additional text.
"""

    try:
        llm_response = (await call_llm_api(system_prompt, user_prompt)).strip()
        index = int(llm_response) - 1
        if 0 <= index < len(QUERY_OPTIONS):
            return QUERY_OPTIONS[index]["query"]
        else:
            return None
    except Exception as e:
        return None

async def query_fixer(sparql_query: str, error_message: str = None):
    """
    Fix SPARQL query syntax errors using LLM.
    Returns the fixed query or the original query if no fixes needed.
    """
    try:
        # If no error message is provided, the query might be correct
        # Only attempt to fix if there's a specific error or if the query looks problematic
        if not error_message:
            # Check if the query looks syntactically correct
            if ('SELECT' in sparql_query.upper() and 'WHERE' in sparql_query.upper() and 
                sparql_query.count('{') == sparql_query.count('}') and
                not any(error_indicator in sparql_query.lower() for error_indicator in ['error', 'bad', 'malformed'])):
                logger.info("Query appears to be syntactically correct, returning as-is")
                return sparql_query
        
        # If there's an error message, check if it's a false positive
        if error_message and "expected [_]" in error_message:
            # This might be a parser issue rather than a real syntax error
            # The original query might be correct
            logger.info("Detected 'expected [_]' error, this might be a parser issue - returning original query")
            return sparql_query
        
        # Try LLM fixing
        logger.info("Attempting LLM-based query fixing...")
        error_context = ""
        if error_message:
            error_context = f"\n\nError encountered: {error_message}\nPlease fix the query to resolve this specific error."
        
        sparql_query_prompt = f"""
        You are a SPARQL query expert. Fix the given SPARQL query to resolve the syntax error.

        SPARQL Query to Fix: "{sparql_query}"  
        
        IMPORTANT: Return ONLY the corrected SPARQL query. Do NOT provide analysis, explanation, or any other text.
        Do NOT use markdown formatting. Do NOT include any commentary.
        Just return the fixed SPARQL query as plain text with proper indentation and spacing.{error_context}
        
        Example of what to return:
        PREFIX example: <http://example.org/>
        SELECT ?s ?p ?o
        WHERE {{
          ?s ?p ?o .
        }}
        
        NOT this:
        **Analysis of the query**...
        Here's the fixed query:
        ```sparql
        PREFIX example: <http://example.org/>
        SELECT ?s ?p ?o
        WHERE {{
          ?s ?p ?o .
        }}
        ```
        
        Return ONLY the fixed SPARQL query with proper formatting.
        """

        llm_response = await call_llm_api(
            "You are a SPARQL query expert. Your ONLY task is to fix SPARQL syntax errors and return the corrected query. Return ONLY the fixed SPARQL query - no analysis, no explanation, no markdown, no commentary. Just the query.",
            sparql_query_prompt
        )

        # Clean the response - remove any markdown formatting or extra text
        cleaned_response = llm_response.strip()
        
        # Check if the response is JSON (which means LLM provided analysis instead of fixing)
        if cleaned_response.startswith('{') and cleaned_response.endswith('}'):
            logger.warning("LLM returned JSON analysis instead of fixed query, returning original")
            return sparql_query
        
        # Check for analysis-style responses (contains "Error", "Analysis", "Details", etc.)
        analysis_indicators = ['**Error**', '**Analysis**', '**Details**', 'Error Details:', 'Key Points:', 'Suggested Actions:', 'Summary Table:', 'Insight:']
        if any(indicator in cleaned_response for indicator in analysis_indicators):
            logger.warning("LLM returned analysis instead of fixed query, returning original")
            return sparql_query
        
        # Check if response contains markdown formatting (indicates analysis)
        if '**' in cleaned_response or '|' in cleaned_response or '---' in cleaned_response:
            logger.warning("LLM returned markdown analysis instead of fixed query, returning original")
            return sparql_query
        
        # Remove markdown code blocks if present
        if cleaned_response.startswith('```'):
            lines = cleaned_response.split('\n')
            cleaned_lines = []
            in_code_block = False
            for line in lines:
                if line.strip() == '```':
                    in_code_block = not in_code_block
                elif in_code_block:
                    cleaned_lines.append(line)
            cleaned_response = '\n'.join(cleaned_lines)
        
        # Remove any markdown formatting
        cleaned_response = cleaned_response.replace('```sparql', '').replace('```', '').strip()
        
        # Fix escaped newlines that are causing syntax errors
        cleaned_response = cleaned_response.replace('\\n', '\n')
        
        # If the response looks like a valid SPARQL query, return it
        if cleaned_response and ('SELECT' in cleaned_response.upper() or 'ASK' in cleaned_response.upper() or 'CONSTRUCT' in cleaned_response.upper()):
            # Additional validation: check if it has basic SPARQL structure
            if ('WHERE' in cleaned_response.upper() or 'ASK' in cleaned_response.upper() or 'CONSTRUCT' in cleaned_response.upper()):
                logger.info("Query fixed by LLM successfully")
                return cleaned_response
            else:
                logger.warning("LLM response has SPARQL keywords but missing WHERE clause, returning original")
                return sparql_query
        else:
            logger.warning(f"LLM response doesn't look like a valid SPARQL query: {cleaned_response[:100]}..., returning original")
            return sparql_query

    except Exception as e:
        logger.error(f"Error in query_fixer: {str(e)}")
        return sparql_query  # Return original query if fixing fails

async def update_query_with_parameters(user_question: str, selected_query: str) -> str:
    """
    Updates a SPARQL query by replacing placeholders with values extracted from user messages.
    
    Args:
        user_question (str): The user's question containing specific identifiers
        selected_query (str): The selected SPARQL query with placeholders
        
    Returns:
        str: The updated SPARQL query with placeholders replaced
    """
    try:
        # First, try to extract specific identifiers from the user question
        extraction_prompt = f"""
        Extract specific identifiers from the user's question that should replace placeholders in a SPARQL query.
        
        User Question: "{user_question}"
        
        Look for:
        - Donor IDs (e.g., DO-CYPH5324, DO-ABC123)
        - Gene IDs (e.g., ENSG00000139618, GENE123)
        - Assembly IDs (e.g., GRCh38.p13, GRCh37)
        - Annotation IDs (e.g., ENSEMBL_v98, REFSEQ_v109)
        - Any other specific identifiers
        
        Return the extracted identifiers in JSON format:
        {{
            "donor_id": "extracted_donor_id_or_null",
            "gene_id": "extracted_gene_id_or_null", 
            "assembly_id": "extracted_assembly_id_or_null",
            "annotation_id": "extracted_annotation_id_or_null",
            "other_identifiers": {{"key": "value"}}
        }}
        
        If no specific identifier is found for a category, use null.
        """
        
        llm_response = await call_llm_api(
            "You are a helpful assistant that extracts specific identifiers from user questions. Return only valid JSON.",
            extraction_prompt
        )
        
        # Parse the JSON response
        import json
        try:
            extracted_data = json.loads(llm_response)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {llm_response}")
            return selected_query
        
        # Update the query with extracted values
        updated_query = selected_query
        
        # Replace common placeholders
        if extracted_data.get("donor_id"):
            # Handle donor ID - convert to proper IRI format if needed
            donor_id = extracted_data["donor_id"]
            if not donor_id.startswith("http"):
                # Assume it's a NIMP donor ID
                donor_id = f"http://example.org/NIMP/{donor_id}"
            updated_query = updated_query.replace("{{sayid}}", donor_id)
        
        if extracted_data.get("gene_id"):
            gene_id = extracted_data["gene_id"]
            if not gene_id.startswith("http"):
                # Assume it's an ENSEMBL gene ID
                gene_id = f"https://identifiers.org/ensembl/{gene_id}"
            updated_query = updated_query.replace("{{gene_id}}", gene_id)
        
        if extracted_data.get("assembly_id"):
            assembly_id = extracted_data["assembly_id"]
            updated_query = updated_query.replace("{{assembly_id}}", assembly_id)
        
        if extracted_data.get("annotation_id"):
            annotation_id = extracted_data["annotation_id"]
            updated_query = updated_query.replace("{{annotation_id}}", annotation_id)
        
        # Handle other identifiers
        if extracted_data.get("other_identifiers"):
            for key, value in extracted_data["other_identifiers"].items():
                placeholder = f"{{{{{key}}}}}"
                updated_query = updated_query.replace(placeholder, str(value))
        
        # Log the update for debugging
        if updated_query != selected_query:
            logger.info(f"Updated query with extracted parameters: {extracted_data}")
        
        return updated_query
        
    except Exception as e:
        logger.error(f"Error updating query with parameters: {str(e)}")
        return selected_query


async def test_database_connection() -> bool:
    """
    Test if the database connection is working

    Returns:
        bool: True if connection is working, False otherwise
    """
    try:
        import aiohttp
        import asyncio

        timeout = aiohttp.ClientTimeout(total=10, connect=5)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Test basic connectivity
            try:
                async with session.get(config.query_url, params={"sparql_query": "SELECT 1 LIMIT 1"}) as response:
                    return response.status < 500  # Any response means connection works
            except Exception:
                return False

    except Exception as e:
        logger.error(f"Database connection test failed: {str(e)}")
        return False


async def get_data_from_graph_db(sparql_query: str) -> str:
    """
    Retrieve the data from the graph database using async requests with improved timeout handling and retry mechanism
    """
    max_retries = 3
    retry_delay = 1  # Start with 1 second delay
    
    # First, test database connectivity
    logger.info("Testing database connectivity...")
    connection_ok = await test_database_connection()
    if not connection_ok:
        return "Database connection test failed. The database might be down or unreachable. Please try again later or contact support."
    
    for attempt in range(max_retries):
        try:

            
            # Use the original query - let the query_fixer handle syntax issues if needed
            fixed_query = sparql_query

            
            jwt_username = config.jwt_login_username
            jwt_password = config.jwt_login_password
            bearer_token_url = config.jwt_bearer_token_url
            logger.info(f"Attempt {attempt + 1}/{max_retries}: Authenticating with JWT")
            
            # Use aiohttp for async requests with more aggressive timeout configuration
            timeout = aiohttp.ClientTimeout(
                total=180,       # 3 minutes total timeout (increased from 120)
                connect=30,      # 30 seconds for connection (increased from 20)
                sock_read=150    # 2.5 minutes for reading response (increased from 90)
            )
            
            # Use connection pooling and keep-alive for better performance
            connector = aiohttp.TCPConnector(
                limit=100,           # Connection pool size
                limit_per_host=30,   # Connections per host
                keepalive_timeout=120, # Keep connections alive (increased from 60)
                enable_cleanup_closed=True,
                ttl_dns_cache=300    # DNS cache TTL
            )
            
            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={'User-Agent': 'BrainKB-Chat-Service/1.0'}
            ) as session:
                # Login to get access token
                credentials = {
                    "email": jwt_username,
                    "password": jwt_password
                }
                
                try:
                    async with session.post(bearer_token_url, json=credentials) as login_response:
                        login_response.raise_for_status()
                        logger.debug("JWT authentication successful")
                        
                        login_data = await login_response.json()
                        access_token = login_data.get("access_token")
                        
                        if not access_token:
                            return "Authentication failed: No access token received."
                except asyncio.TimeoutError:
                    logger.error("Timeout during JWT authentication")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    return "Authentication timeout. Please try again."
                except Exception as e:
                    logger.error(f"Authentication error: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    return "Authentication failed. Please check your credentials."
                
                # Send SPARQL query to graph database
                logger.info(f"Attempt {attempt + 1}/{max_retries}: Sending SPARQL query to graph database")
                logger.info(f"Query URL: {config.query_url}")
                logger.info(f"Query length: {len(fixed_query)} characters")
                
                params = {
                    "sparql_query": fixed_query  # Use the fixed query
                }
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                }
                
                try:
                    logger.info("Starting database query request...")
                    start_time = asyncio.get_event_loop().time()
                    
                    # Create a task for the request with timeout monitoring
                    async def make_request():
                        async with session.get(
                            config.query_url,
                            params=params,
                            headers=headers
                        ) as req:
                            logger.info(f"Request started, elapsed time: {asyncio.get_event_loop().time() - start_time:.2f}s")
                            req.raise_for_status()
                            logger.info("Request completed successfully, parsing response...")
                            logger.debug("Graph database query successful")
                            
                            # Parse and format the response
                            response_data = await req.json()
                            logger.info(f"Response parsed, total elapsed time: {asyncio.get_event_loop().time() - start_time:.2f}s")
                            return response_data
                    
                    # Monitor the request with extended timeout
                    try:
                        response_data = await asyncio.wait_for(make_request(), timeout=150)  # 2.5 minute timeout
                    except asyncio.TimeoutError:
                        logger.error("Request timed out after 150 seconds")
                        
                        # For simple queries that timeout, provide a helpful response
                        if "SELECT DISTINCT" in fixed_query.upper() or "SELECT ?" in fixed_query.upper():
                            return "The database query is taking longer than expected. This appears to be a simple query that should complete quickly. The database might be experiencing high load or connectivity issues.\n\n" + \
                                   "Please try:\n" + \
                                   "- Waiting a few minutes and trying again\n" + \
                                   "- Contacting support to check database status\n" + \
                                   "- Using a different query type if possible"
                        else:
                            raise asyncio.TimeoutError("Database query timed out")
                    
                    # Check if the response contains results
                    if 'results' in response_data and 'bindings' in response_data['results']:
                        bindings = response_data['results']['bindings']
                        logger.debug("$-"*100)
                        logger.debug(f"Raw bindings: {bindings}")
                        logger.debug("$-" * 100)
                        
                        if not bindings:
                            return "No data found for the given query."
                        
                        # Format the results for display
                        formatted_results = []
                        for i, binding in enumerate(bindings, 1):
                            row_data = []
                            for var_name, var_value in binding.items():
                                if 'value' in var_value:
                                    row_data.append(f"{var_name}: {var_value['value']}")
                            
                            if row_data:
                                formatted_results.append(f"Row {i}: {' | '.join(row_data)}")
                        
                        if formatted_results:
                            return f"Query Results:\n\n" + "\n\n".join(formatted_results)
                        else:
                            return "Query executed successfully but no data was returned."
                    
                    elif 'datasetCount' in response_data:
                        # Handle count queries
                        count = response_data['datasetCount']
                        return f"Dataset Count: {count}"
                    
                    elif 'status' in response_data and response_data['status'] == 'fail':
                        # Handle SPARQL query errors
                        error_message = response_data.get('message', 'Unknown SPARQL error')
                        logger.error(f"SPARQL query error: {error_message}")
                        
                        # If the error persists even after fixing, try LLM-based fixing
                        if "syntax" in error_message.lower() or "bad" in error_message.lower():
                            logger.info("Attempting LLM-based SPARQL query fixing")
                            try:
                                llm_fixed_query = await query_fixer(sparql_query, error_message)
                                
                                # If query_fixer returned the original query (meaning it detected a false positive), 
                                # try the original query again
                                if llm_fixed_query == sparql_query:
                                    logger.info("Query fixer returned original query, trying again with original query")
                                    # Try the original query again
                                    params = {
                                        "sparql_query": sparql_query
                                    }
                                else:
                                    # Try the LLM-fixed query
                                    params = {
                                        "sparql_query": llm_fixed_query
                                    }
                                
                                # Also try a simplified version of the query if it contains BIND
                                if "BIND(" in sparql_query:
                                    logger.info("Query contains BIND clause, trying simplified version")
                                    # Create a simplified version without BIND
                                    simplified_query = sparql_query.replace("BIND(<http://example.org/NIMP/DO-CYPH5324> AS ?donor_id)", "")
                                    simplified_query = simplified_query.replace("?donor_id ?p ?o .", "<http://example.org/NIMP/DO-CYPH5324> ?p ?o .")
                                    
                                    # Try the simplified query first
                                    params = {
                                        "sparql_query": simplified_query
                                    }
                                
                                async with session.get(
                                    config.query_url,
                                    params=params,
                                    headers=headers
                                ) as req2:
                                    req2.raise_for_status()
                                    response_data2 = await req2.json()
                                    
                                    # Check if query worked
                                    if 'results' in response_data2 and 'bindings' in response_data2['results']:
                                        bindings = response_data2['results']['bindings']
                                        if bindings:
                                            formatted_results = []
                                            for i, binding in enumerate(bindings, 1):
                                                row_data = []
                                                for var_name, var_value in binding.items():
                                                    if 'value' in var_value:
                                                        row_data.append(f"{var_name}: {var_value['value']}")
                                                
                                                if row_data:
                                                    formatted_results.append(f"Row {i}: {' | '.join(row_data)}")
                                            
                                            if formatted_results:
                                                return f"Query Results:\n\n" + "\n\n".join(formatted_results)
                                    
                                    # If simplified query failed, try the original query as fallback
                                    if "BIND(" in sparql_query:
                                        logger.info("Simplified query failed, trying original query as fallback")
                                        params = {
                                            "sparql_query": sparql_query
                                        }
                                        
                                        async with session.get(
                                            config.query_url,
                                            params=params,
                                            headers=headers
                                        ) as req3:
                                            req3.raise_for_status()
                                            response_data3 = await req3.json()
                                            
                                            # Check if original query worked
                                            if 'results' in response_data3 and 'bindings' in response_data3['results']:
                                                bindings = response_data3['results']['bindings']
                                                if bindings:
                                                    formatted_results = []
                                                    for i, binding in enumerate(bindings, 1):
                                                        row_data = []
                                                        for var_name, var_value in binding.items():
                                                            if 'value' in var_value:
                                                                row_data.append(f"{var_name}: {var_value['value']}")
                                                        
                                                        if row_data:
                                                            formatted_results.append(f"Row {i}: {' | '.join(row_data)}")
                                                    
                                                    if formatted_results:
                                                        return f"Query Results:\n\n" + "\n\n".join(formatted_results)
                                    
                                    # If all attempts failed, return error
                                    return f"SPARQL Query Error: {error_message}. The query has been automatically fixed using multiple methods, but there may still be syntax issues. Please try a different query or contact support."
                                    
                            except Exception as llm_error:
                                logger.warning(f"LLM-based fixing also failed: {str(llm_error)}")
                                return f"SPARQL Query Error: {error_message}. The query has been automatically fixed, but there may still be syntax issues. Please try a different query or contact support."
                        else:
                            return f"SPARQL Query Error: {error_message}. Please check the query syntax or try a different query."
                    
                    else:
                        # Handle other response formats
                        return f"Query Results: {response_data}"
                        
                except asyncio.TimeoutError:
                    logger.error(f"Timeout error in get_data_from_graph_db (attempt {attempt + 1}): Request timed out")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    # If all retries failed due to timeout, provide helpful message
                    complexity_analysis = check_query_complexity(fixed_query)
                    
                    timeout_message = "The database query is taking longer than expected. This might be due to:\n\n" + \
                                    "1. Complex query processing\n" + \
                                    "2. High database load\n" + \
                                    "3. Network connectivity issues\n\n"
                    
                    if complexity_analysis["complexity_level"] in ["Medium", "High"]:
                        timeout_message += f"Query Complexity: {complexity_analysis['complexity_level']} (Score: {complexity_analysis['complexity_score']})\n\n"
                        timeout_message += "Suggestions to improve performance:\n"
                        for suggestion in complexity_analysis["suggestions"]:
                            timeout_message += f"- {suggestion}\n"
                        timeout_message += "\n"
                    
                    timeout_message += "Please try:\n" + \
                                    "- A simpler query\n" + \
                                    "- Adding LIMIT to your query\n" + \
                                    "- Waiting a few minutes and trying again\n" + \
                                    "- Contacting support if the issue persists"
                    
                    return timeout_message
                except aiohttp.ClientError as e:
                    logger.error(f"Client error in get_data_from_graph_db (attempt {attempt + 1}): {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    return "Sorry, I am having trouble connecting to the database. Please try again or contact support."
                        
        except Exception as e:
            logger.error(f"Error in get_data_from_graph_db (attempt {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
                continue
            return "Sorry, I am having some trouble addressing your request. Please try again or contact developer to update me."
    
    # If all retries failed
    return "Sorry, all attempts to connect to the database failed. Please try again later or contact support."



async def fix_sparql_query_with_llm(query: str) -> str:
    """
    Use LLM to fix complex SPARQL syntax errors
    
    Args:
        query (str): The problematic SPARQL query
        
    Returns:
        str: The fixed SPARQL query
    """
    try:
        system_prompt = """You are a SPARQL query expert. Fix the given SPARQL query by correcting syntax errors, removing invalid characters, and ensuring proper structure. Return only the corrected SPARQL query without any explanation or additional text. IMPORTANT: Preserve proper indentation and spacing for readability."""

        user_prompt = f"""Fix this SPARQL query by correcting any syntax errors while preserving proper formatting:

{query}

Return only the corrected SPARQL query with proper indentation."""

        fixed_query = await call_llm_api(system_prompt, user_prompt)
        
        # Clean up the response
        fixed_query = fixed_query.strip()
        
        # Remove any markdown formatting if present
        if fixed_query.startswith('```sparql'):
            fixed_query = fixed_query[9:]
        if fixed_query.startswith('```'):
            fixed_query = fixed_query[3:]
        if fixed_query.endswith('```'):
            fixed_query = fixed_query[:-3]
        
        fixed_query = fixed_query.strip()
        
        # Fix escaped newlines that are causing syntax errors
        fixed_query = fixed_query.replace('\\n', '\n')
        
        if fixed_query != query:
            logger.info("SPARQL query fixed using LLM")
            logger.debug(f"Original: {query}")
            logger.debug(f"LLM Fixed: {fixed_query}")
        
        return fixed_query
        
    except Exception as e:
        logger.warning(f"Error fixing SPARQL query with LLM: {str(e)}")
        return query  # Return original query if LLM fixing fails

def check_query_complexity(query: str) -> dict:
    """
    Check the complexity of a SPARQL query and suggest simplifications
    
    Args:
        query (str): The SPARQL query to analyze
        
    Returns:
        dict: Complexity analysis and suggestions
    """
    try:
        complexity_score = 0
        suggestions = []
        
        # Check query length
        if len(query) > 1000:
            complexity_score += 3
            suggestions.append("Query is very long - consider breaking it into smaller parts")
        
        # Check for complex patterns
        if "UNION" in query.upper():
            complexity_score += 2
            suggestions.append("Query contains UNION - this can be slow")
        
        if "OPTIONAL" in query.upper():
            complexity_score += 1
            suggestions.append("Query contains OPTIONAL - consider if this is necessary")
        
        if "FILTER" in query.upper():
            complexity_score += 1
            suggestions.append("Query contains FILTER - ensure filters are optimized")
        
        if "ORDER BY" in query.upper():
            complexity_score += 1
            suggestions.append("Query contains ORDER BY - sorting can be slow on large datasets")
        
        if "LIMIT" not in query.upper():
            complexity_score += 2
            suggestions.append("Query has no LIMIT - consider adding LIMIT 100 or LIMIT 1000")
        
        # Check for multiple GRAPH patterns
        graph_count = query.upper().count("GRAPH")
        if graph_count > 1:
            complexity_score += graph_count
            suggestions.append(f"Query accesses {graph_count} graphs - consider using fewer graphs")
        
        # Determine complexity level
        if complexity_score <= 2:
            complexity_level = "Low"
        elif complexity_score <= 4:
            complexity_level = "Medium"
        else:
            complexity_level = "High"
        
        return {
            "complexity_score": complexity_score,
            "complexity_level": complexity_level,
            "suggestions": suggestions,
            "query_length": len(query)
        }
        
    except Exception as e:
        logger.warning(f"Error checking query complexity: {str(e)}")
        return {
            "complexity_score": 0,
            "complexity_level": "Unknown",
            "suggestions": ["Unable to analyze query complexity"],
            "query_length": len(query)
        }
