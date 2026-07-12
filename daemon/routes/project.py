from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import yaml
from daemon.protocol.writer import atomic_write_yaml

router = APIRouter()

REPO = Path("/Users/user/Obsidian-Claude-Vibe-Squad")
PROJECTS = REPO / "projects"

class CreateProjectRequest(BaseModel):
    slug: str
    category: str
    brief: str = ""
    tags: list[str] = []

@router.post("/projects")
def create_project(req: CreateProjectRequest):
    from datetime import date
    today = date.today().isoformat()
    project_dir = PROJECTS / req.category / f"{req.slug}-{today}"
    if project_dir.exists():
        raise HTTPException(400, "project already exists")
    for sub in ["research", "drafts", "deliverables", "handoffs"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    (project_dir / "brief.md").write_text(f"# {req.slug}\n\n{req.brief}\n")
    atomic_write_yaml(project_dir / "state.yaml", {
        "project": req.slug,
        "category": req.category,
        "started": today,
        "last_touched": today,
        "status": "active",
        "tags": req.tags,
        "participants": ["chrono"],
        "deliverables": [],
    })
    (project_dir / "review.md").write_text("# Retrospective\n\n_(fill when project closes)_\n")
    return {"path": str(project_dir), "slug": req.slug, "category": req.category}

@router.get("/projects")
def list_projects():
    if not PROJECTS.exists():
        return {"projects": []}
    projects = []
    for cat_dir in PROJECTS.iterdir():
        if cat_dir.is_dir():
            for proj_dir in cat_dir.iterdir():
                if proj_dir.is_dir() and (proj_dir / "state.yaml").exists():
                    state = yaml.safe_load((proj_dir / "state.yaml").read_text())
                    projects.append(state)
    return {"projects": projects}

@router.get("/projects/{slug}")
def get_project(slug: str):
    for cat_dir in PROJECTS.iterdir() if PROJECTS.exists() else []:
        for proj_dir in cat_dir.iterdir():
            if proj_dir.name.startswith(f"{slug}-") and (proj_dir / "state.yaml").exists():
                return yaml.safe_load((proj_dir / "state.yaml").read_text())
    raise HTTPException(404, "project not found")
