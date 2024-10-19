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

from rdflib import Graph

class ValueNotSetException(Exception):
    def __init__(self):
        Exception.__init__(self)
        self.message = "Required value is not set"

    def __str__(self):
        return self.message

def convert_to_turtle(jsonlddata):

        return Graph().parse(data=jsonlddata, format='json-ld').serialize(format="turtle")