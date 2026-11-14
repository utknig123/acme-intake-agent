"""Background reality checks on values the candidate gave.

FAIL-CLOSED: a value is only "verified" if the check positively succeeds. If the check fails OR cannot run
(network down, rate limited) the value is flagged "unverified" and the candidate must explicitly confirm it;
unconfirmed-by-check values are then labelled "unverified" in the record notes for a human.

check() returns (status, reason) with status in {"verified", "bad", "unverified", "n/a"}.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "yopmail.com", "trashmail.com",
              "throwawaymail.com", "sharklasers.com", "getnada.com", "maildrop.cc"}


def _get(url, timeout=4):
    req = urllib.request.Request(url, headers={"User-Agent": "acme-intake-agent/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def check_email(email: str):
    domain = email.rsplit("@", 1)[-1].lower()
    if domain in DISPOSABLE:
        return "bad", f"{domain} is a disposable email provider; ask for a permanent address"
    try:
        d = _get(f"https://dns.google/resolve?name={domain}&type=MX")
        if d.get("Status") == 3:
            return "bad", f"the domain {domain} does not exist, so mail can't be delivered; the address is probably mistyped"
        if d.get("Answer"):
            return "verified", f"{domain} has a working mail server"
        a = _get(f"https://dns.google/resolve?name={domain}&type=A")
        if a.get("Status") == 0 and a.get("Answer"):
            return "verified", f"{domain} resolves"
        return "bad", f"{domain} has no mail server; the address is probably mistyped"
    except Exception:
        return "unverified", "could not verify the email domain right now"


def check_github(url: str):
    m = re.match(r"https://github\.com/([^/]+)$", url or "")
    if not m:
        return "bad", "not a GitHub profile URL"
    try:
        _get(f"https://api.github.com/users/{m.group(1)}")
        return "verified", f"GitHub user {m.group(1)} exists"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "bad", f"GitHub user '{m.group(1)}' was not found; confirm the username"
        return "unverified", "could not verify the GitHub profile right now"
    except Exception:
        return "unverified", "could not verify the GitHub profile right now"


def check(field: str, value):
    if field == "email" and isinstance(value, str):
        return check_email(value)
    if field == "github_url" and isinstance(value, str):
        return check_github(value)
    return "n/a", ""
