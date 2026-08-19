"""
Base Agent with unified interface
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from ..models import Project, Artifact
from ..storage import add_artifact, get_project
from ..manifest import get_agent
import time

class BaseAgent(ABC):
    id: str
    manifest = None

    def __init__(self):
        self.manifest = get_agent(self.id)

    @abstractmethod
    def run(self, project: Project, context: Dict[str, Any]) -> List[Artifact]:
        """Should generate artifacts and return them"""
        pass

    def validate_inputs(self, project: Project) -> (bool, str):
        """Check if required inputs are present"""
        if not self.manifest:
            return False, "No manifest"
        # For simplicity, check project input has niche etc for phase1
        # Also check dependencies approved
        for dep in self.manifest.dependencies:
            state = project.agent_states.get(dep)
            if not state or state.status.value != "approved":
                return False, f"Dependency {dep} not approved yet"
        return True, "ok"

    def build_prompt(self, project: Project) -> str:
        return f"Agent {self.id} running for project {project.name}"
