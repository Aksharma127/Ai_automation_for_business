"""Employee task assignment: requirement extraction, skill match and workload checks."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel

from .. import llm as llm_api
from .base import ToolContext, tool
from .data import Table, load_json, load_table


class _Skills(BaseModel):
    skills: list[str]


@tool("understand_task", provides=("employee/task database",), uses_llm=True)
def understand_task(ctx: ToolContext, employees_path: str, task_file: str | None = None,
                    description: str | None = None, priority: str | None = None, deadline: str | None = None,
                    role: str | None = None, estimated_hours: float | None = None,
                    deadline_days: dict[str, int] | None = None, today: str | None = None) -> dict[str, Any]:
    """Work out the task's required skills, priority, deadline and effort."""
    task: dict[str, Any] = load_json(ctx, task_file) if task_file else {}
    if description:
        task.update({"title": description[:60], "description": description})
    task["priority"] = (priority or task.get("priority") or "normal").lower()
    task["role"] = role or task.get("role")
    hours = float(estimated_hours or task.get("estimated_hours") or 8)
    task["estimated_hours"] = int(hours) if hours.is_integer() else hours
    base = date.fromisoformat(today) if today else date.today()
    days = (deadline_days or {}).get(task["priority"], 7)
    task["deadline"] = deadline or task.get("deadline") or (base + timedelta(days=days)).isoformat()

    vocab = sorted({s.strip().lower() for e in load_table(ctx, employees_path) for s in str(e.get("skills", "")).split(";")})
    text = f"{task.get('title', '')} {task.get('description', '')}".lower()
    skills = [s for s in vocab if re.search(rf"\b{re.escape(s)}\b", text)]
    method = "skill vocabulary match"
    if ctx.llm is not None:
        try:
            res = llm_api.ask_structured(ctx.llm, _Skills, "Pick the skills from the vocabulary that the task needs.",
                                         f"Vocabulary: {vocab}\nTask:\n{llm_api.data(text, 'task')}")
            picked = [s.lower() for s in res.skills if s.lower() in vocab]
            if picked:
                skills, method = picked, "llm"
        except Exception as exc:
            ctx.note(f"LLM skill extraction unavailable ({type(exc).__name__}); used vocabulary match")
    task["required_skills"] = skills
    task["skills_method"] = method
    return task


@tool("score_skill_match", provides=("ranking logic",))
def score_skill_match(ctx: ToolContext, employees_path: str, required_skills: list[str], role: str | None = None) -> Table:
    """Load employees (optionally of a role) and compute the share of required skills each has."""
    rows = load_table(ctx, employees_path)
    if role:
        rows = [r for r in rows if role.lower().rstrip("s") in str(r.get("role", "")).lower()]
    req = {s.lower() for s in required_skills}
    out = []
    for r in rows:
        have = {s.strip().lower() for s in str(r.get("skills", "")).split(";")}
        matched = sorted(req & have)
        out.append({**r, "matched_skills": ", ".join(matched) or "-",
                    "skill_match": round(len(matched) / len(req), 2) if req else 0.0})
    return out


@tool("check_workload", provides=("employee/task database",))
def check_workload(ctx: ToolContext, employees: Table, estimated_hours: float) -> Table:
    """Compute spare capacity and whether each person can take the task now."""
    out = []
    for r in employees:
        spare = (r.get("weekly_capacity_hours") or 0) - (r.get("current_load_hours") or 0)
        available = str(r.get("available", "yes")).lower() in {"yes", "true", "1"}
        out.append({**r, "spare_hours": spare, "is_available": available,
                    "has_capacity": available and spare >= estimated_hours})
    return out
