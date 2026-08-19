"""
Brand Factory Server - FastAPI + Static UI
Port 8002 by default
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import os, json

from .manifest import PHASES, ALL_AGENTS, get_phase
from .models import ProjectInput, AgentStatus
from .storage import list_projects, create_project, get_project, save_project, get_artifact_content, PROJECTS_DIR, add_artifact, save_uploaded_file
from .orchestrator import run_agent, approve_agent, reject_agent

BASE_DIR = Path(__file__).parent
UI_DIR = BASE_DIR / "ui"

app = FastAPI(title="Brand Factory - Agent OS", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve artifacts as static for preview
# We will serve via endpoint not static

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = UI_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))

@app.get("/app.js")
def app_js():
    p = UI_DIR / "app.js"
    if not p.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="application/javascript")

@app.get("/api/phases")
def api_phases():
    # Return phases with agents simplified for frontend
    return {"phases": [p.model_dump() for p in PHASES]}

class CreateProjectReq(BaseModel):
    name: str
    input: ProjectInput

@app.get("/api/projects")
def api_list_projects():
    projs = list_projects()
    return {"projects": [p.model_dump() for p in projs]}

@app.post("/api/projects")
def api_create_project(req: CreateProjectReq):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name required")
    proj = create_project(req.name.strip(), req.input)
    return proj.model_dump()

@app.get("/api/projects/{pid}")
def api_get_project(pid: str):
    proj = get_project(pid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj.model_dump()

@app.put("/api/projects/{pid}/input")
def api_update_input(pid: str, input_data: ProjectInput):
    proj = get_project(pid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    proj.input = input_data
    save_project(proj)
    # unlock first agent if niche exists
    if proj.input.niche:
        st = proj.agent_states.get("market_researcher")
        if st and st.status == AgentStatus.waiting_input:
            st.status = AgentStatus.ready
            st.message = "Готов к запуску"
            save_project(proj)
    return get_project(pid).model_dump()

@app.post("/api/projects/{pid}/agents/{aid}/run")
def api_run_agent(pid: str, aid: str):
    proj = get_project(pid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if aid not in ALL_AGENTS:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        _, ok, msg = run_agent(pid, aid)
        proj = get_project(pid)
        return {"ok": ok, "message": msg, "project": proj.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{pid}/agents/{aid}/approve")
def api_approve_agent(pid: str, aid: str, data: dict = None):
    notes = ""
    if data:
        notes = data.get("notes", "")
    proj = approve_agent(pid, aid, notes)
    return {"ok": True, "project": proj.model_dump()}

@app.post("/api/projects/{pid}/agents/{aid}/reject")
def api_reject_agent(pid: str, aid: str, data: dict = None):
    notes = ""
    if data:
        notes = data.get("notes", "")
    proj = reject_agent(pid, aid, notes)
    return {"ok": True, "project": proj.model_dump()}

@app.get("/api/projects/{pid}/artifacts/{filename}")
def api_get_artifact(pid: str, filename: str):
    # Security: prevent directory traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    content = get_artifact_content(pid, filename)
    path = PROJECTS_DIR / pid / "artifacts" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov"]:
        return FileResponse(path)
    if content is None:
        return FileResponse(path)
    # Return content as json for md preview
    # But also serve file download if requested via ?download
    ext = path.suffix.lower()
    if ext == ".json":
        try:
            return JSONResponse(json.loads(content))
        except:
            return JSONResponse({"raw": content})
    return {"filename": filename, "content": content}

@app.post("/api/projects/{pid}/upload")
def api_upload(pid: str, file: UploadFile = File(...)):
    proj = get_project(pid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    data = file.file.read()
    artifact = save_uploaded_file(pid, data, file.filename)
    return artifact.model_dump()

@app.get("/api/projects/{pid}/artifacts")
def api_list_artifacts(pid: str):
    proj = get_project(pid)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"artifacts": [a.model_dump() for a in proj.artifacts]}

@app.get("/health")
def health():
    return {"status": "ok", "service": "brand-factory", "phases": len(PHASES), "agents": len(ALL_AGENTS)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8002"))
    print(f"\n🚀 Brand Factory running at http://0.0.0.0:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
