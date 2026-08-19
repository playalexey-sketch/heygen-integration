"""
Brand Factory - Unified models
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
from datetime import datetime

class AgentStatus(str, Enum):
    idle = "idle"
    waiting_input = "waiting_input"
    ready = "ready"
    running = "running"
    needs_review = "needs_review"
    approved = "approved"
    failed = "failed"
    skipped = "skipped"

class ArtifactType(str, Enum):
    md = "md"
    json = "json"
    image = "image"
    video = "video"
    manifest = "manifest"
    txt = "txt"

class Artifact(BaseModel):
    id: str
    filename: str
    type: ArtifactType
    path: str
    created_by: str
    description: str
    size: int = 0
    preview_url: str = ""

class AgentManifest(BaseModel):
    id: str
    name: str
    icon: str
    phase_id: str
    role: str
    description: str
    inputs_required: List[str] = []
    outputs_produced: List[str] = []
    dependencies: List[str] = []  # previous agent ids
    tasks: List[str] = []
    estimated_time: str = "5-10 min"
    human_checkpoints: List[str] = []
    ui_hints: Dict[str, Any] = {}

class TaskItem(BaseModel):
    id: str
    title: str
    description: str
    done: bool = False
    agent_id: Optional[str] = None

class SubPhase(BaseModel):
    id: str
    title: str
    goal: str
    problems_before: List[str] = []
    improvements: List[str] = []
    tasks: List[TaskItem] = []
    agents: List[str] = []
    artifacts: List[str] = []

class Phase(BaseModel):
    id: str
    title: str
    subtitle: str
    icon: str
    color: str
    goal: str
    outcome: str
    subphases: List[SubPhase] = []
    agents: List[AgentManifest] = []

class ProjectInput(BaseModel):
    niche: str = ""
    expert_name: str = ""
    expert_current: str = ""  # who they are now
    big_goal: str = ""
    target_revenue: str = ""
    socials: Dict[str, str] = {}
    superpowers: str = ""
    stories: str = ""
    proof_existing: str = ""
    competitors: str = ""
    tone_of_voice: str = ""

class AgentRunState(BaseModel):
    agent_id: str
    status: AgentStatus = AgentStatus.idle
    progress: int = 0
    message: str = ""
    inputs: Dict[str, Any] = {}
    outputs: List[str] = []
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    human_approved: bool = False
    review_notes: str = ""

class Project(BaseModel):
    id: str
    name: str
    created_at: str
    input: ProjectInput = ProjectInput()
    agent_states: Dict[str, AgentRunState] = {}
    artifacts: List[Artifact] = []
    current_phase: str = "phase_1"
    completion: float = 0.0
