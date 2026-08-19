"""
Simple file storage for projects + artifacts
"""
import json
import os
from pathlib import Path
from datetime import datetime
import uuid
from typing import List
from .models import Project, AgentRunState, ProjectInput, Artifact, ArtifactType, AgentStatus
from .manifest import ALL_AGENTS

BASE_DIR = Path(__file__).parent
PROJECTS_DIR = BASE_DIR / "projects"
PROJECTS_DIR.mkdir(exist_ok=True)

def list_projects() -> List[Project]:
    projects = []
    for folder in PROJECTS_DIR.iterdir():
        if folder.is_dir():
            meta = folder / "meta.json"
            if meta.exists():
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    projects.append(Project(**data))
                except Exception:
                    continue
    projects.sort(key=lambda x: x.created_at, reverse=True)
    return projects

def create_project(name: str, input_data: ProjectInput) -> Project:
    pid = f"proj_{uuid.uuid4().hex[:8]}"
    folder = PROJECTS_DIR / pid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "artifacts").mkdir(exist_ok=True)
    
    agent_states = {}
    for aid, manif in ALL_AGENTS.items():
        # initially idle, but first agent in phase1 ready if dependencies met
        status = AgentStatus.idle
        if aid == "market_researcher":
            status = AgentStatus.waiting_input
        agent_states[aid] = AgentRunState(agent_id=aid, status=status)
    
    proj = Project(
        id=pid,
        name=name,
        created_at=datetime.utcnow().isoformat(),
        input=input_data,
        agent_states=agent_states,
        artifacts=[],
        current_phase="phase_1",
        completion=0.0
    )
    save_project(proj)
    return proj

def get_project(pid: str) -> Project | None:
    folder = PROJECTS_DIR / pid
    meta = folder / "meta.json"
    if not meta.exists():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        return Project(**data)
    except Exception as e:
        print(f"Error loading project {pid}: {e}")
        return None

def save_project(proj: Project):
    folder = PROJECTS_DIR / proj.id
    folder.mkdir(parents=True, exist_ok=True)
    meta = folder / "meta.json"
    # update completion
    total = len(proj.agent_states)
    approved = sum(1 for s in proj.agent_states.values() if s.status == AgentStatus.approved)
    proj.completion = round((approved / total * 100) if total else 0, 1)
    meta.write_text(json.dumps(proj.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")

def add_artifact(pid: str, filename: str, content: str, created_by: str, description: str, artifact_type: ArtifactType = ArtifactType.md) -> Artifact:
    folder = PROJECTS_DIR / pid / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(content, encoding="utf-8")
    artifact = Artifact(
        id=f"art_{uuid.uuid4().hex[:6]}",
        filename=filename,
        type=artifact_type,
        path=str(path),
        created_by=created_by,
        description=description,
        size=len(content.encode('utf-8')),
        preview_url=f"/api/projects/{pid}/artifacts/{filename}"
    )
    proj = get_project(pid)
    if proj:
        # replace if exists
        proj.artifacts = [a for a in proj.artifacts if a.filename != filename]
        proj.artifacts.append(artifact)
        save_project(proj)
    return artifact

def get_artifact_content(pid: str, filename: str) -> str | None:
    path = PROJECTS_DIR / pid / "artifacts" / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None

def save_uploaded_file(pid: str, file_bytes: bytes, filename: str) -> Artifact:
    folder = PROJECTS_DIR / pid / "artifacts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_bytes(file_bytes)
    # determine type
    ext = Path(filename).suffix.lower()
    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
        atype = ArtifactType.image
    elif ext in [".mp4", ".mov"]:
        atype = ArtifactType.video
    elif ext == ".json":
        atype = ArtifactType.json
    else:
        atype = ArtifactType.md
    artifact = Artifact(
        id=f"art_{uuid.uuid4().hex[:6]}",
        filename=filename,
        type=atype,
        path=str(path),
        created_by="user_upload",
        description=f"Uploaded {filename}",
        size=len(file_bytes),
        preview_url=f"/api/projects/{pid}/artifacts/{filename}"
    )
    proj = get_project(pid)
    if proj:
        proj.artifacts = [a for a in proj.artifacts if a.filename != filename]
        proj.artifacts.append(artifact)
        save_project(proj)
    return artifact
