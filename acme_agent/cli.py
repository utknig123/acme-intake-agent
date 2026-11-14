"""Terminal chat:  python agent.py --candidate-id c001"""
import argparse
import json
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path

from .agent import Conversation
from .config import ROOT, make_clients
from .db import DBError


def _read(prompt, timeout):
    q = queue.Queue()
    threading.Thread(target=lambda: q.put(sys.stdin.readline()), daemon=True).start()
    print(prompt, end="", flush=True)
    try:
        line = q.get(timeout=timeout)
    except queue.Empty:
        return None
    return None if line == "" else line.rstrip("\n")


def save_run(conv, runs_dir):
    d = Path(runs_dir)
    d.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = d / f"{conv.s['cid']}_{stamp}"
    state = conv.public_state()
    base.with_suffix(".json").write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    lines = [f"{'AGENT' if t['role'] == 'agent' else 'CANDIDATE'}: {t['text']}" for t in state["transcript"]]
    base.with_suffix(".txt").write_text("\n".join(lines) + f"\n\nOUTCOME: {state['outcome']}\n", encoding="utf-8")
    return base


def main(argv=None):
    ap = argparse.ArgumentParser(description="ACME candidate intake agent")
    ap.add_argument("--candidate-id")
    ap.add_argument("--idle-timeout", type=int, default=300, help="seconds of silence before the chat counts as abandoned")
    ap.add_argument("--runs-dir", default=str(ROOT / "runs"))
    ap.add_argument("--list", action="store_true", help="list candidates and exit")
    ap.add_argument("--reset", action="store_true", help="reset the workspace and exit")
    a = ap.parse_args(argv)
    db, llm = make_clients()
    try:
        if a.list:
            for c in db.list():
                print(c["id"], c.get("full_name"), c.get("collection_status"))
            return 0
        if a.reset:
            db.reset()
            print("workspace reset")
            return 0
        if not a.candidate_id:
            ap.error("--candidate-id is required")
        if not llm.configured:
            print("LLM_API_KEY is not set (see .env.example)", file=sys.stderr)
            return 2
        conv, audit = Conversation.start(a.candidate_id, db, llm)
    except DBError as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 2
    print(f"[agent] {a.candidate_id}: missing={audit.missing} invalid={[i['field'] for i in audit.invalid]} confirm={[i['field'] for i in audit.confirm]}")
    if conv.s["ended"]:
        print("[agent] Nothing to collect - no conversation started.")
        return 0
    print("[agent] Chat started. Type as the candidate. /quit to leave.\n")
    print(f"Agent: {conv.open()}\n")
    try:
        while not conv.s["ended"]:
            line = _read("You: ", a.idle_timeout)
            if line is None:
                print("\n[agent] no reply - closing as abandoned")
                conv.abandon("no reply / idle timeout")
                break
            if line.strip().lower() in ("/quit", "/exit"):
                conv.abandon("candidate left the chat (/quit)")
                break
            if not line.strip():
                continue
            print(f"\nAgent: {conv.turn(line)}\n")
    except KeyboardInterrupt:
        conv.abandon("interrupted")
    except Exception as e:
        print(f"[agent] fatal: {e}", file=sys.stderr)
        conv.abandon(f"agent error: {type(e).__name__}")
    if not conv.s.get("final_write_ok", True):
        print("[agent] WARNING: final DB write failed:", conv.s.get("final_write_error"), file=sys.stderr)
    p = save_run(conv, a.runs_dir)
    print(f"\n[agent] outcome={conv.s['outcome']}  run saved to {p}.json")
    return 0
