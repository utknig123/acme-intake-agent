"""Recruiter work-queue: who should be contacted next, why, and how the pipeline looks.

Pure function over the candidate list (no extra API calls). It reads what earlier agent runs left behind
(status, attempts, `follow_up_at` in notes) and turns it into a ranked to-do list plus a funnel.
"""
from __future__ import annotations

import datetime as dt
import re

from . import validators as V

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _follow_up(notes):
    m = re.findall(r"follow_up_at=([0-9T:+\-]+)", str(notes or ""))
    if not m:
        return None
    try:
        t = dt.datetime.fromisoformat(m[-1])
        return t if t.tzinfo else t.replace(tzinfo=IST)
    except ValueError:
        return None


def build(candidates, now=None):
    now = now or dt.datetime.now(IST)
    items, funnel = [], {"completed": 0, "in_progress": 0, "pending": 0, "no_answer": 0, "refused": 0, "needs_human": 0}
    for c in candidates:
        status = c.get("collection_status") or "pending"
        funnel[status] = funnel.get(status, 0) + 1
        todo = V.audit_record(c).todo_fields()
        fu = _follow_up(c.get("notes"))
        attempts = int(c.get("attempt_count") or 0)
        if status == "needs_human":
            items.append({"id": c["id"], "name": c.get("full_name"), "lane": "human", "score": 100, "todo": todo,
                          "action": "Human review", "reason": "Agent escalated this record; see the last note."})
            continue
        if not todo:
            continue
        score, reason, action = 10 + 4 * len(todo), f"{len(todo)} field(s) missing", "Start chat"
        if fu:
            if fu <= now:
                score += 60
                reason, action = f"Follow-up was due {fu.astimezone(IST):%d %b %H:%M}", "Resume now (overdue)"
            else:
                score -= 25
                reason, action = f"Candidate asked for {fu.astimezone(IST):%d %b %H:%M}", "Wait until then"
        if status == "in_progress":
            score += 15
        if status == "refused":
            score -= 20
            action, reason = "Human decision", "Declined some fields; a person should decide if they are optional in practice"
        if status == "no_answer":
            score -= 12 * attempts
            action = "Retry later" if attempts < 3 else "Give up / call"
            reason = f"No reply, {attempts} attempt(s)"
        if len(todo) <= 2 and status in ("in_progress", "pending"):
            score += 12
            reason += " - almost done, quick win"
        items.append({"id": c["id"], "name": c.get("full_name"), "lane": "agent", "score": score, "todo": todo,
                      "action": action, "reason": reason, "follow_up_at": fu.isoformat() if fu else None})
    items.sort(key=lambda i: -i["score"])
    total = max(1, len(candidates))
    return {"queue": items, "funnel": funnel, "completion_rate": round(100 * funnel.get("completed", 0) / total)}
