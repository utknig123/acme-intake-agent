"""Application Quality Score (0-100): how much a recruiter can trust this record. Deterministic and explainable.

  completeness 50  - mandatory fields present and valid
  verification 20  - email domain / GitHub profile positively verified (fail-closed)
  consistency  20  - cross-field sanity checks (dates, names, CGPA) pass
  provenance   10  - every value collected this chat is backed by the candidate's own quote
Returns the score, a per-component breakdown and human-readable risk flags.
"""
from __future__ import annotations

import datetime as dt
import re

from . import validators as V


def consistency_flags(rec):
    flags = []
    name = re.findall(r"[a-z]{3,}", str(rec.get("full_name") or "").lower())
    email = str(rec.get("email") or "").lower().split("@")[0]
    if name and email and not any(t in email for t in name) and not any(email.startswith(t[:3]) for t in name):
        flags.append("Email does not resemble the candidate's name (could be shared or typo'd)")
    try:
        start = dt.date.fromisoformat(str(rec.get("available_from")))
        gy = int(rec.get("graduation_year"))
        if start.year > gy + 1:
            flags.append(f"Start date {start} is more than a year after graduation ({gy})")
        if start.year < 2026:
            flags.append("Start date is in the past")
    except (TypeError, ValueError):
        pass
    try:
        cg = float(rec.get("cgpa"))
        if cg < 5:
            flags.append(f"Low CGPA ({cg}); may be on a different scale")
        if cg == 10:
            flags.append("Perfect 10.0 CGPA; worth a quick check")
    except (TypeError, ValueError):
        pass
    if rec.get("degree") == "Other":
        flags.append("Degree recorded as 'Other'; check notes for the real degree")
    return flags


def score(rec, verifications=None, saved=None):
    verifications = verifications or {}
    a = V.audit_record(rec)
    mand = [f for f in V.MANDATORY]
    good = sum(1 for f in mand if f in a.ok)
    completeness = round(50 * good / len(mand))
    checked = [f for f in ("email", "github_url") if not V.is_blank(rec.get(f))]
    if checked:
        ver_pts = round(20 * sum(1 for f in checked if verifications.get(f, {}).get("status") == "verified") / len(checked))
    else:
        ver_pts = 0
    flags = consistency_flags(rec)
    consistency = max(0, 20 - 7 * len(flags))
    saved = saved or {}
    prov = 10 if not saved else round(10 * sum(1 for v in saved.values() if v.get("evidence")) / len(saved))
    risk = list(flags)
    for f in checked:
        st = verifications.get(f, {}).get("status")
        if st == "unverified":
            risk.append(f"{f} could not be verified automatically")
        elif st is None:
            risk.append(f"{f} was not verified this session")
        elif st == "bad":
            risk.append(f"{f} failed verification and was confirmed by the candidate")
    total = completeness + ver_pts + consistency + prov
    grade = "A" if total >= 90 else "B" if total >= 75 else "C" if total >= 55 else "D"
    return {"score": total, "grade": grade, "risk": risk,
            "parts": {"completeness": completeness, "verification": ver_pts, "consistency": consistency, "provenance": prov}}
