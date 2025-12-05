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
# @File    : graph_database_connection_manager.py
# @Software: PyCharm

from SPARQLWrapper import SPARQLWrapper, BASIC, GET, JSON, POST
from rdflib import Graph, URIRef, Literal, RDF, XSD
from core.shared import ValueNotSetException
import logging
import sys
from core.configuration import load_environment
import concurrent.futures
from typing import List, Dict, Any, Optional, Tuple
from core.shared import contains_ip
import asyncio
from functools import lru_cache

logger = logging.getLogger(__name__)

# Cache environment variables to avoid repeated file system operations
# This is loaded once at module import time and cached
_ENV_CACHE: Optional[Dict[str, Any]] = None

def _get_cached_env() -> Dict[str, Any]:
    """Get cached environment variables, loading once if needed."""
    global _ENV_CACHE
    if _ENV_CACHE is None:
        _ENV_CACHE = load_environment()
    return _ENV_CACHE

# Cache endpoint configurations to avoid repeated string operations
_ENDPOINT_CACHE: Dict[Tuple[str, str], str] = {}

def _get_endpoint(request_type: str) -> str:
    """
    Get cached endpoint URL for the given request type.
    This avoids repeated string operations and environment lookups.
    """
    cache_key = (request_type, "endpoint")
    if cache_key in _ENDPOINT_CACHE:
        return _ENDPOINT_CACHE[cache_key]
    
    env = _get_cached_env()
    graphdatabase_hostname = env["GRAPHDATABASE_HOSTNAME"]
    graphdatabase_port = env["GRAPHDATABASE_PORT"]
    graphdatabase_type = env["GRAPHDATABASE_TYPE"]
    graphdatabase_repository = env.get("GRAPHDATABASE_REPOSITORY")
    
    if graphdatabase_type == "GRAPHDB":
        if request_type == "get":
            endpoint = f"{graphdatabase_hostname}:{graphdatabase_port}/repositories/{graphdatabase_repository}"
        elif request_type == "post":
            endpoint = f"{graphdatabase_hostname}:{graphdatabase_port}/repositories/{graphdatabase_repository}/statements"
        else:
            raise ValueError("Invalid request type. Use 'get' or 'post'.")
    elif graphdatabase_type == "OXIGRAPH":
        # Construct endpoint URL properly
        if graphdatabase_hostname.startswith("http://") or graphdatabase_hostname.startswith("https://"):
            base_url = graphdatabase_hostname
        elif contains_ip(graphdatabase_hostname):
            base_url = f"http://{graphdatabase_hostname}:{graphdatabase_port}"
        else:
            # Docker service name or hostname - construct full URL
            base_url = f"http://{graphdatabase_hostname}:{graphdatabase_port}"
        
        if request_type == "get":
            endpoint = f"{base_url}/query"
        elif request_type == "post":
            endpoint = f"{base_url}/update"
        else:
            raise ValueError("Invalid request type. Use 'get' or 'post'.")
    elif graphdatabase_type == "BLAZEGRAPH":
        if "bigdata/sparql" in graphdatabase_hostname:
            endpoint = graphdatabase_hostname
        elif "bigdata/" in graphdatabase_hostname or "bigdata" in graphdatabase_hostname:
            hostname = (
                graphdatabase_hostname[:-1]
                if "bigdata/" in graphdatabase_hostname
                else graphdatabase_hostname
            )
            endpoint = f"{hostname}/sparql"
        else:
            raise ValueError("Invalid Blazegraph hostname configuration.")
    else:
        raise ValueError("Unsupported database type.")
    
    _ENDPOINT_CACHE[cache_key] = endpoint
    return endpoint

def _connectionmanager(request_type="get"):
    """
    Connects to a graph database using the provided connection details.
    Optimized to use cached environment variables and endpoint configuration.

    Parameters:
    - request_type (str): The type of request ('get' or 'post').

    Returns:
    - SPARQLWrapper: An instance of SPARQLWrapper configured for the specified request type.
    """
    env = _get_cached_env()
    graphdatabase_username = env["GRAPHDATABASE_USERNAME"]
    graphdatabase_password = env["GRAPHDATABASE_PASSWORD"]
    graphdatabase_hostname = env["GRAPHDATABASE_HOSTNAME"]
    graphdatabase_type = env["GRAPHDATABASE_TYPE"]

    if not (
        graphdatabase_username
        and graphdatabase_password
        and graphdatabase_hostname
        and graphdatabase_type
    ):
        raise ValueNotSetException()

    endpoint = _get_endpoint(request_type)

    try:
        sparql = SPARQLWrapper(endpoint)
        # Only use authentication if credentials are provided and we're going through nginx
        # Direct access to oxigraph (without nginx) doesn't require authentication
        if graphdatabase_username and graphdatabase_password:
            # Check if we're using nginx (oxigraph-nginx) or direct access (oxigraph)
            if "oxigraph-nginx" in endpoint or "nginx" in graphdatabase_hostname.lower():
                sparql.setHTTPAuth(BASIC)
                sparql.setCredentials(graphdatabase_username, graphdatabase_password)
        return sparql
    except Exception as e:
        raise ConnectionError(f"Failed to connect to the graph database: {str(e)}")


def test_connection():
    """
        Check if the SPARQL response indicates a successful connection.

        Args:
            response (dict): The JSON response from the SPARQL query.

        Returns:
            bool: True if the response indicates a successful connection, False otherwise.
        """
    connectionmanager = _connectionmanager()
    connectionmanager.setQuery("SELECT ?s ?p ?o WHERE {?s ?p ?o} LIMIT 1")
    connectionmanager.setReturnFormat(JSON)
    try:
        response = connectionmanager.query().convert()
        return isinstance(response, dict) and "head" in response and "results" in response and "bindings" in response["results"]

    except Exception as e:
        logger.error(f"Connection test failed: {e}", exc_info=True)
        return False


def insert_data_gdb(turtle_data):
    if test_connection():
        try:
            sparql = _connectionmanager("post")
            sparql.setMethod(POST)
            sparql_query = (
                """
                    INSERT DATA {
                    %s
                    }
                    """
                % turtle_data
            )
            sparql.setQuery(sparql_query)
            response = sparql.query()
            # QueryResult object - convert to string for logging if needed
            # For INSERT operations, response is typically empty or contains status info
            logger.debug("Graph DB insert operation completed")
            return {
                "status": "success",
                "message": "Data inserted to graph database successfully",
            }
        except Exception as e:
            return {"status": "fail", "message": {str(e)}}
    else:
        return "Not connected! or Connection error"


async def insert_data_gdb_async(turtle_data):
    """
    Async wrapper for insert_data_gdb that runs the blocking operation in a thread pool.
    This prevents blocking the event loop during long-running database operations.
    """
    loop = asyncio.get_event_loop()
    # Run the blocking operation in a thread pool executor
    result = await loop.run_in_executor(None, insert_data_gdb, turtle_data)
    return result


def fetch_data_gdb(sparql_query):
    """
    Synchronous function to fetch data from graph database.
    Note: This is a blocking operation. Use fetch_data_gdb_async for async contexts.
    """
    sparql = _connectionmanager("get")
    # Set SPARQL query parameters
    sparql.setMethod(GET)
    sparql.setQuery(sparql_query)
    sparql.setReturnFormat(JSON)
    try:
        result = sparql.query().convert()
        return {"status": "success", "message": result}
    except Exception as e:
        logger.error(f"SPARQL query failed: {e}", exc_info=True)
        return {"status": "fail", "message": str(e)}


async def fetch_data_gdb_async(sparql_query):
    """
    Async wrapper for fetch_data_gdb that runs the blocking operation in a thread pool.
    This prevents blocking the event loop during SPARQL queries.
    """
    loop = asyncio.get_event_loop()
    # Run the blocking operation in a thread pool executor
    result = await loop.run_in_executor(None, fetch_data_gdb, sparql_query)
    return result


async def check_named_graph_exists(named_graph_iri: str) -> bool:
    """
    Check if a named graph is registered in the metadata graph.
    
    Args:
        named_graph_iri: The IRI of the named graph to check
        
    Returns:
        bool: True if the graph is registered, False otherwise
    """
    METADATA_GRAPH_URI = "https://brainkb.org/metadata/named-graph"
    
    try:
        # Ensure named_graph_iri ends with '/' for consistency
        graph_iri = named_graph_iri
        if not graph_iri.endswith('/'):
            graph_iri = graph_iri + '/'
        
        query = f"""
        ASK WHERE {{
          GRAPH <{METADATA_GRAPH_URI}> {{
            ?s ?p ?o.
            FILTER(?s = <{graph_iri}>)
          }}
        }}
        """
        result = await fetch_data_gdb_async(query)
        
        if isinstance(result, dict):
            return result.get("message", {}).get("boolean", False)
        return False
    except Exception as e:
        logger.error(f"Error checking named graph existence: {e}", exc_info=True)
        return False


def concurrent_query(
    querylist: List[Dict[str, Any]], max_workers: int = None, timeout: int = 10
) -> List[Dict[str, Any]]:
    """
    Executes a list of SPARQL queries concurrently and returns the results with the corresponding query_key.

    :param querylist: List of dictionaries, each containing one key-value pair representing the query.
        Example: [
        {'query_one': 'SELECT ?subject ?predicate ?object\nWHERE {\n  ?subject ?predicate ?object .\n}\nLIMIT 1'},
        {'donor': 'SELECT ?subject ?predicate ?object\n  WHERE {\n ?subject ?predicate ?object .\n FILTER(?subject = <http://example.org/subject1>)\n  }\n  LIMIT 2'},
        {'structure': 'PREFIX bican: <https://identifiers.org/brain-bican/vocab/> \nSELECT DISTINCT (COUNT (?id) as ?count)\nWHERE {\n  ?id bican:structure ?o; \n}\nLIMIT 3'}
        ]
    :param max_workers: Maximum number of worker threads. Defaults to None (automatically determined).
    :param timeout: Time limit for each query in seconds. Defaults to 30 seconds.
    :return: List of dictionaries, where each contains 'query_key' and 'result' for each query.
    """
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Create a mapping of futures to their corresponding query_key
        future_to_query_key = {
            executor.submit(fetch_data_gdb, query_value): query_key
            for query_dict in querylist
            for query_key, query_value in query_dict.items()
        }

        for future in concurrent.futures.as_completed(future_to_query_key):
            query_key = future_to_query_key[future]
            try:
                result = future.result(timeout=timeout)
                results.append({query_key: result})
            except concurrent.futures.TimeoutError:
                sys.stdout.write(f"Query timed out for {query_key}")
                results.append({query_key: None})
            except Exception as e:
                sys.stdout.write(f"Error occurred during query execution for {query_key}: {e}")
                results.append(
                    {"query_key": query_key, "result": None}
                )  # Optional: Handle failure case

    return results


def initialize_metadata_graph():
    """
    Check if the metadata named graph exists and create it if it doesn't.
    This should be called once on service startup.
    
    Returns:
        bool: True if metadata graph exists or was created successfully, False otherwise
    """
    import time
    
    metadata_graph_uri = "https://brainkb.org/metadata/named-graph"
    
    # Wait a bit for Oxigraph to be ready (if it's starting up)
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            # Check if the metadata graph exists
            check_metadata_graph_query = f"""
            ASK WHERE {{
              GRAPH <{metadata_graph_uri}> {{
                ?s ?p ?o.
              }}
            }}
            """
            
            metadata_graph_exists = fetch_data_gdb(check_metadata_graph_query)
            
            # Handle both dict and string responses
            if isinstance(metadata_graph_exists, dict):
                if metadata_graph_exists.get("status") == "success":
                    metadata_exists = metadata_graph_exists.get("message", {}).get("boolean", False)
                else:
                    # Query failed, assume graph doesn't exist
                    metadata_exists = False
            else:
                # If response is not a dict, assume graph doesn't exist
                logger.warning(f"Unexpected response type from fetch_data_gdb: {type(metadata_graph_exists)}")
                metadata_exists = False
            
            if metadata_exists:
                logger.info(f"Metadata graph <{metadata_graph_uri}> already exists.")
                return True
            else:
                # Graph doesn't exist, break and create it
                break
                
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries}: Could not check metadata graph existence: {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.warning("Max retries reached. Will attempt to create metadata graph anyway.")
                metadata_exists = False
    
    # If metadata graph doesn't exist, create it with an initialization triple
    logger.info(f"Metadata graph <{metadata_graph_uri}> does not exist. Creating it...")
    for attempt in range(max_retries):
        try:
            # Create the metadata graph by inserting a minimal initialization statement
            init_graph = Graph()
            init_uri = URIRef(f"{metadata_graph_uri}#init")
            prov_entity = URIRef("http://www.w3.org/ns/prov#Entity")
            dcterms_desc = URIRef("http://purl.org/dc/terms/description")
            
            init_graph.add((init_uri, RDF.type, prov_entity))
            init_graph.add((init_uri, dcterms_desc, 
                           Literal("Metadata graph for BrainKB named graph registry", datatype=XSD.string)))
            
            # Serialize to N-Triples format (s p o .)
            init_nt = init_graph.serialize(format='nt')
            
            # Create SPARQL INSERT DATA query with GRAPH clause for Oxigraph
            # Format: INSERT DATA { GRAPH <uri> { triples } }
            insert_query = f"""
            INSERT DATA {{
              GRAPH <{metadata_graph_uri}> {{
                {init_nt}
              }}
            }}
            """
            
            # Execute the insert query directly
            sparql = _connectionmanager("post")
            sparql.setMethod(POST)
            sparql.setQuery(insert_query)
            response = sparql.query()
            logger.debug("Metadata graph insert operation completed")
            
            # Verify the graph was created
            verify_query = f"""
            ASK WHERE {{
              GRAPH <{metadata_graph_uri}> {{
                ?s ?p ?o.
              }}
            }}
            """
            verify_result = fetch_data_gdb(verify_query)
            if isinstance(verify_result, dict) and verify_result.get("status") == "success":
                verified = verify_result.get("message", {}).get("boolean", False)
                if verified:
                    logger.info(f"Metadata graph <{metadata_graph_uri}> created and verified successfully.")
                    return True
            
            logger.warning(f"Metadata graph created but verification failed. Response: {verify_result}")
            return False
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{max_retries}: Failed to create metadata graph: {str(e)}", exc_info=True)
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                return False
    
    return False
