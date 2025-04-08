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

from typing import List, Optional, Dict
from pydantic import BaseModel


# === LLM Configuration ===
class LLMConfig(BaseModel):
    model: str
    base_url: str
    seed: Optional[int] = None
    frequency_penalty: Optional[float] = 0.0
    temperature: Optional[float] = 0.0
    api_key: Optional[str] = None


# === Agent Definition ===
class Agent(BaseModel):
    role: str
    goal: str
    backstory: str
    llm: LLMConfig


# === AgentConfig with named agents (e.g., extractor_agent) ===
class AgentConfig(BaseModel):
    extractor_agent: Agent
    alignment_agent: Agent
    judge_agent: Agent


# === Task Definition ===
class Task(BaseModel):
    description: str
    expected_output: str
    agent_id: str


# === TaskConfig with named tasks (e.g., extraction_task) ===
class TaskConfig(BaseModel):
    extraction_task: Task
    alignment_task: Task
    judge_task: Task


# === (Optional) Supporting Classes for embedding and search config ===
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
