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
# @File    : pydantic_models.py
# @Software: PyCharm

from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# === Pydantic Models ===

class LLMConfig(BaseModel):
    model: str
    base_url: str
    frequency_penalty: float
    temperature: float
    seed: int
    api_key: str

class Agent(BaseModel):
    id: str
    output_variable: str
    role: str
    goal: str
    backstory: str
    llm: LLMConfig

class AgentConfig(BaseModel):
    agents: List[Agent]

class Task(BaseModel):
    id: str
    description: str
    expected_output: str
    agent_id: str

class TaskConfig(BaseModel):
    tasks: List[Task]

class FlowStep(BaseModel):
    id: str
    agent_key: str
    task_key: str
    inputs: Dict[str, str]
    knowledge_source: Optional[str] = None

class FlowConfig(BaseModel):
    flow: List[FlowStep]

class ProviderConfig(BaseModel):
    api_base: str
    model: str

class EmbedderInnerConfig(BaseModel):
    provider: str
    config: ProviderConfig

class EmbedderConfig(BaseModel):
    embedder_config: EmbedderInnerConfig

class SearchKeyConfig(BaseModel):
    search_key: List[str]


