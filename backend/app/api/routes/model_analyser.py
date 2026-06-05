"""Read-only API for the model-analyser dashboard.

Serves the golden conversations (opus-4.8 reference set) and the per-model test
run artifacts produced by `scripts/model_analyser`. Files-on-disk, no DB.
"""
import json
import pathlib

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/model-analyser", tags=["model-analyser"])

BASE = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "model_analyser"
GOLDEN_DIR = BASE / "golden"
RUNS_DIR = BASE / "runs"


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/golden")
def list_golden():
    items = []
    if GOLDEN_DIR.exists():
        for f in sorted(GOLDEN_DIR.glob("conv_*.json")):
            d = _load(f)
            turns = d.get("turns", [])
            items.append({
                "conv_id": d.get("conv_id", f.stem),
                "persona": d.get("persona", {}),
                "turns": len(turns),
                "calls": sum(len(t.get("calls", [])) for t in turns),
                "approved": d.get("approved", False),
            })
    return {"golden": items}


@router.get("/golden/{conv_id}")
def get_golden(conv_id: str):
    f = GOLDEN_DIR / f"conv_{conv_id}.json"
    if not f.exists():
        raise HTTPException(404, f"golden conversation {conv_id!r} not found")
    return _load(f)


@router.get("/runs")
def list_runs():
    items = []
    if RUNS_DIR.exists():
        for f in sorted(RUNS_DIR.glob("*.json")):
            d = _load(f)
            items.append({
                "file": f.stem,
                "label": d.get("label", f.stem),
                "model": d.get("model"),
                "summary": d.get("summary", {}),
            })
    return {"runs": items}


@router.get("/runs/{name}")
def get_run(name: str):
    f = RUNS_DIR / f"{name}.json"
    if not f.exists():
        raise HTTPException(404, f"run {name!r} not found")
    return _load(f)
