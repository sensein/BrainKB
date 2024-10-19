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

ALLOWED_MIME_TYPES = {"application/json",  # JSON file
                      "application/vnd.ms-excel",  # Excel file
                      "text/plain",  # Plain text file
                      "text/csv",  # CSV file
                      "application/pdf",  # PDF file
                      "application/rdf+xml",  # RDF/XML
                      "application/ld+json",  # JSON-LD
                      "text/turtle"  # Turtle
                      }
ALLOWED_EXTENSIONS = {".json",
                      ".xls",
                      ".txt",
                      ".csv",
                      ".pdf",
                      ".ttl",
                      ".rdf",
                      "jsonld"}


def validate_file_extension(filename: str) -> bool:
    return any(filename.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def validate_mime_type(mime_type: str) -> bool:
    return mime_type in ALLOWED_MIME_TYPES
