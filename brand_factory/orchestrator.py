"""
Orchestrator - runs agents respecting dependencies
"""
from .models import Project, AgentStatus
from .storage import get_project, save_project
from .manifest import ALL_AGENTS
from .agents.phase1_agents import PHASE1_AGENT_CLASSES
from .agents.generic_agents import STUB_AGENTS
from datetime import datetime
import time
import traceback

ALL_AGENT_CLASSES = {**PHASE1_AGENT_CLASSES, **STUB_AGENTS}

def run_agent(pid: str, agent_id: str, context: dict = None):
    project = get_project(pid)
    if not project:
        raise ValueError(f"Project {pid} not found")
    
    AgentCls = ALL_AGENT_CLASSES.get(agent_id)
    if not AgentCls:
        raise ValueError(f"Agent {agent_id} not found")

    agent_instance = AgentCls()
    state = project.agent_states.get(agent_id)
    if not state:
        from .models import AgentRunState
        state = AgentRunState(agent_id=agent_id)
        project.agent_states[agent_id] = state

    # Validate inputs
    ok, msg = agent_instance.validate_inputs(project)
    if not ok:
        state.status = AgentStatus.waiting_input
        state.message = msg
        save_project(project)
        return project, False, msg

    state.status = AgentStatus.running
    state.started_at = datetime.utcnow().isoformat()
    state.message = f"Agent {agent_instance.manifest.name} запущен..."
    state.progress = 10
    save_project(project)

    try:
        # Simulate progress
        time.sleep(0.5)
        # reload to keep artifacts safe
        project = get_project(pid)
        state = project.agent_states.get(agent_id)
        state.progress = 50
        state.message = "Генерирую документы..."
        save_project(project)

        artifacts = agent_instance.run(project, context or {})

        # reload again after artifacts added
        project = get_project(pid)
        state = project.agent_states.get(agent_id)
        state.progress = 100
        state.status = AgentStatus.needs_review
        state.finished_at = datetime.utcnow().isoformat()
        state.message = f"Готово, {len(artifacts)} документов создано, ждет ревью"
        state.outputs = [a.filename for a in artifacts]
        save_project(project)

        project = get_project(pid)
        return project, True, "ok"

    except Exception as e:
        project = get_project(pid)
        state = project.agent_states.get(agent_id)
        state.status = AgentStatus.failed
        state.error = str(e) + "\n" + traceback.format_exc()
        state.message = f"Ошибка: {e}"
        save_project(project)
        return project, False, str(e)

def approve_agent(pid: str, agent_id: str, notes: str = ""):
    project = get_project(pid)
    if not project:
        raise ValueError("Project not found")
    state = project.agent_states.get(agent_id)
    if not state:
        raise ValueError("Agent state not found")
    state.status = AgentStatus.approved
    state.human_approved = True
    state.review_notes = notes
    state.finished_at = datetime.utcnow().isoformat()
    save_project(project)

    # Unlock dependent agents
    for dep_id, manifest in ALL_AGENTS.items():
        if agent_id in manifest.dependencies:
            dep_state = project.agent_states.get(dep_id)
            if dep_state and dep_state.status in [AgentStatus.idle, AgentStatus.waiting_input]:
                # check if all dependencies approved
                all_ok = True
                for d in manifest.dependencies:
                    s = project.agent_states.get(d)
                    if not s or s.status != AgentStatus.approved:
                        all_ok = False
                        break
                if all_ok:
                    dep_state.status = AgentStatus.ready
                    dep_state.message = "Готов к запуску, зависимости approved"
    save_project(project)
    return get_project(pid)

def reject_agent(pid: str, agent_id: str, notes: str = ""):
    project = get_project(pid)
    state = project.agent_states[agent_id]
    state.status = AgentStatus.ready
    state.message = f"Отправлено на доработку: {notes}"
    state.review_notes = notes
    save_project(project)
    return get_project(pid)
