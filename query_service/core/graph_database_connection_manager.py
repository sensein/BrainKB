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
from rdflib import Graph
from core.shared import ValueNotSetException
import logging
from core.configuration import load_environment
import concurrent.futures
from typing import List, Dict, Any
from core.shared import contains_ip

logger = logging.getLogger(__name__)


def convert_to_turtle(jsonlddata):
    return Graph().parse(data=jsonlddata, format="json-ld").serialize(format="turtle")


def _connectionmanager(request_type="get"):
    """
    Connects to a graph database using the provided connection details.

    Parameters:
    - request_type (str): The type of request ('get' or 'post').

    Returns:
    - SPARQLWrapper: An instance of SPARQLWrapper configured for the specified request type.
    """
    graphdatabase_username = load_environment()["GRAPHDATABASE_USERNAME"]
    graphdatabase_password = load_environment()["GRAPHDATABASE_PASSWORD"]
    graphdatabase_hostname = load_environment()["GRAPHDATABASE_HOSTNAME"]
    graphdatabase_port = load_environment()["GRAPHDATABASE_PORT"]
    graphdatabase_type = load_environment()["GRAPHDATABASE_TYPE"]
    graphdatabase_repository = load_environment()["GRAPHDATABASE_REPOSITORY"]
    print(
        f"Connecting to {graphdatabase_type}-{graphdatabase_username}-{graphdatabase_password}-{graphdatabase_hostname} Repository: {graphdatabase_repository}"
    )

    if not (
        graphdatabase_username
        and graphdatabase_password
        and graphdatabase_hostname
        and graphdatabase_type
    ):
        raise ValueNotSetException()

    if graphdatabase_type == "GRAPHDB":
        if request_type == "get":
            endpoint = f"{graphdatabase_hostname}:{graphdatabase_port}/repositories/{graphdatabase_repository}"
        elif request_type == "post":
            endpoint = f"{graphdatabase_hostname}:{graphdatabase_port}/repositories/{graphdatabase_repository}/statements"
        else:
            raise ValueError("Invalid request type. Use 'get' or 'post'.")

    elif graphdatabase_type == "OXIGRAPH":
        print("Connecting to OXIGRAPH")
        if contains_ip(graphdatabase_hostname):
            endpoint_set = f"{graphdatabase_hostname}:{graphdatabase_port}"
        else:
            endpoint_set = f"{graphdatabase_hostname}"
        if request_type == "get":
            endpoint = f"{endpoint_set}/query"
            print(f"Connecting to OXIGRAPH endpoing: {endpoint}")
        elif request_type == "post":
            endpoint = f"{endpoint_set}/update"
        else:
            raise ValueError("Invalid request type. Use 'get' or 'post'.")

    elif graphdatabase_type == "BLAZEGRAPH":
        if "bigdata/sparql" in graphdatabase_hostname:
            endpoint = graphdatabase_hostname
        elif (
            "bigdata/" in graphdatabase_hostname or "bigdata" in graphdatabase_hostname
        ):
            hostname = (
                graphdatabase_hostname[:-1]
                if "bigdata/" in graphdatabase_hostname
                else graphdatabase_hostname
            )
            endpoint = f"{hostname}/sparql"
    else:
        raise ValueError("Unsupport database.")

    try:
        sparql = SPARQLWrapper(endpoint)
        if graphdatabase_username and graphdatabase_password:
            sparql.setHTTPAuth(BASIC)
            sparql.setCredentials(graphdatabase_username, graphdatabase_password)
        return sparql
    except Exception as e:
        raise ConnectionError(f"Failed to connect to the graph database: {str(e)}")


def test_connection():
    connectionmanager = _connectionmanager()
    connectionmanager.setQuery("SELECT ?s ?p ?o WHERE {?s ?p ?o} LIMIT 1")
    connectionmanager.setReturnFormat(JSON)
    try:
        results = connectionmanager.query().convert()
        if len(results["results"]["bindings"]) > 0:
            return True
        else:
            return False
    except Exception as e:
        print(f"Error-test conn:{e}")
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
            print(response)
            return {
                "status": "success",
                "message": "Data inserted to graph database successfully",
            }
        except Exception as e:
            return {"status": "fail", "message": {str(e)}}
    else:
        return "Not connected! or Connection error"


def fetch_data_gdb(sparql_query):
    sparql = _connectionmanager("get")
    # Set SPARQL query parameters
    sparql.setMethod(GET)
    sparql.setQuery(sparql_query)
    sparql.setReturnFormat(JSON)
    try:
        result = sparql.query().convert()
        return {"status": "success", "message": result}
    except Exception as e:
        return {"status": "fail", "message": str(e)}


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
                print(f"Query timed out for {query_key}")
                results.append({query_key: None})
            except Exception as e:
                print(f"Error occurred during query execution for {query_key}: {e}")
                results.append(
                    {"query_key": query_key, "result": None}
                )  # Optional: Handle failure case

    return results
