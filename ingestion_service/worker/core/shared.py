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

from core.configuration import load_environment

ingest_url = load_environment()["INGEST_URL"]


def get_endpoints(endpoint_type: str) -> str:
    """
    Retrieve the URL endpoint based on the specified type.

    Parameters:
        endpoint_type (str): The type of endpoint needed.
        ingest_url (str): The base URL to which the endpoint types will be appended.

    Returns:
        str: The full URL for the specified endpoint type.

    Raises:
        ValueError: If the specified endpoint type is not supported.
    """
    endpoints = {
        "jsonld": f"{ingest_url}/query/insert-jsonld",
    }

    if endpoint_type not in endpoints:
        raise ValueError("Unsupported endpoint type specified.")

    return endpoints[endpoint_type]


