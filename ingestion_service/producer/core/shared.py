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


import json

def has_context(json_obj):
    """Simple JSON-LD check for presence of the context"""
    return '@context' in json_obj


def is_valid_jsonld(jsonld_str):
    try:
        jsonld_obj = json.loads(jsonld_str)
        return has_context(jsonld_obj["kg_data"])
    except ValueError:
        return False

