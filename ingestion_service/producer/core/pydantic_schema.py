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
# @File    : pydantic_schema.py
# @Software: PyCharm
from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Any


class BaseSchema(BaseModel):
    user: str
    type: str
    date_created: datetime = datetime.now()
    date_modified: datetime = datetime.now()


class InputJSONSchema(BaseSchema):
    json_data: Dict[Any, Any]

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class InputJSONSLdchema(BaseModel):
    type: str
    kg_data: Dict[Any, Any]


class InputTextSchema(BaseSchema):
    type: str = "text"
    text_data: str


if __name__ == "__main__":
    """Test pydantic schema"""
    import json
    print(InputJSONSchema.model_validate_json(
        json.dumps(
            {
                "id": "1BCD",
                "user": "U123r",
                "date_created": "2024-04-30T12:42:32.203447",
                "date_modified": "2024-04-30T12:42:32.203451",
                "json_data": {
                    "neuroscience_disorders": [
                        {
                            "disorder": "Alzheimer's disease",
                            "description": "A progressive neurodegenerative disorder that leads to memory loss and cognitive decline.",
                            "symptoms": [
                                "Memory loss",
                                "Confusion",
                                "Trouble with language and reasoning"
                            ],
                            "treatments": [
                                "Medications (e.g., cholinesterase inhibitors)",
                                "Cognitive therapy"
                            ]
                        },
                        {
                            "disorder": "Parkinson's disease",
                            "description": "A neurodegenerative disorder characterized by tremors, rigidity, and difficulty with movement.",
                            "symptoms": [
                                "Tremors",
                                "Bradykinesia",
                                "Postural instability"
                            ],
                            "treatments": [
                                "Levodopa",
                                "Deep brain stimulation (DBS)"
                            ]
                        },
                        {
                            "disorder": "Schizophrenia",
                            "description": "A chronic and severe mental disorder that affects how a person thinks, feels, and behaves.",
                            "symptoms": [
                                "Hallucinations",
                                "Delusions",
                                "Disorganized thinking"
                            ],
                            "treatments": [
                                "Antipsychotic medications",
                                "Psychotherapy"
                            ]
                        }
                    ]
                }
            }
        )
    )
    )
