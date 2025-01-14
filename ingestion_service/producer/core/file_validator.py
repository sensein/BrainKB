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
# @File    : file_validator.py
# @Software: PyCharm

from rdflib import Graph, exceptions
from pyld import jsonld
from json import JSONDecodeError

import logging

logger = logging.getLogger(__name__)

ALLOWED_RAW_FILE_MIME_TYPES = {
    "application/json",        # JSON file
    "application/vnd.ms-excel",# Excel file
    "text/plain",             # Plain text file, also used for TTL
    "text/csv",               # CSV file
    "application/pdf",        # PDF file
}

ALLOWED_KG_MIME_TYPES = {
    "application/ld+json",    # JSON-LD
    "text/turtle",            # Turtle (TTL)
    "application/x-turtle",   # Alternative MIME type for Turtle
    "application/turtle"      # Another common MIME type for Turtle
}

ALLOWED_KG_EXTENSIONS = {
    ".ttl",
    ".jsonld",
}

ALLOWED_RAW_FILE_EXTENSIONS = {
    ".json",
    # ".xls",
    ".txt",
    # ".csv",
    ".pdf",

}


def validate_file_extension(filename: str, validation_type="raw") -> bool:
    logger.info(f"Running validate_file_extension")
    if validation_type=="kg":
        return any(filename.endswith(ext) for ext in ALLOWED_KG_EXTENSIONS)

    return any(filename.endswith(ext) for ext in ALLOWED_RAW_FILE_EXTENSIONS)


def validate_mime_type(mime_type: str, validation_type="raw") -> bool:
    logger.info(f"Running validate_mime_type")
    if validation_type == "kg":
        return mime_type in ALLOWED_KG_MIME_TYPES

    return mime_type in ALLOWED_RAW_FILE_MIME_TYPES

def is_valid_turtle(turtle_data: str) -> bool:
    """Validates whether the given string is a valid Turtle format."""
    try:
        graph = Graph()
        graph.parse(data=turtle_data, format="turtle")
        return True
    except exceptions.ParserError:
        logger.error(f"ParserError error")
        return False
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return False

def is_valid_jsonld(jsonld_data: dict) -> bool:
    """Validates whether the given dictionary is a valid JSON-LD format."""
    logger.info(f"Running is_valid_jsonld")
    try:
        compacted = jsonld.compact(jsonld_data, jsonld_data.get("@context", {}))
        return "@context" in compacted and "@type" in compacted
    except JSONDecodeError:
        logger.error(f"JSONDecodeError error")
        return False
    except Exception as e:
        logger.error(f"Validation error: {e}")
        return False