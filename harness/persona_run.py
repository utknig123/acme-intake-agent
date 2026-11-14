"""Run LLM-simulated candidate personas against the agent (real LLM, real or fake DB).

    python -m harness.persona_run c004 evasive [--real]
Prints transcript + guardrail events; saves JSON into runs/.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from acme_agent.agent import Conversation  # noqa: E402
from acme_agent.cli import save_run  # noqa: E402
from acme_agent.config import ROOT, load_env, make_clients  # noqa: E402
from acme_agent.simulator import candidate_reply  # noqa: E402


def run(cid, persona, real=True, max_turns=14, out=True):
    load_env()
    db, llm = make_clients()
    if not real:
        from harness.fakes import FakeDB
        db = FakeDB()
    conv, _ = Conversation.start(cid, db, llm)
    if conv.s["ended"]:
        return conv, db
    conv.open()
    for _ in range(max_turns):
        if conv.s["ended"]:
            break
        conv.turn(candidate_reply(llm, persona, conv.s["record"], conv.s["transcript"]))
    if not conv.s["ended"]:
        conv.abandon("persona script ended")
    if out:
        for t in conv.s["transcript"]:
            print(("AGENT: " if t["role"] == "agent" else "  CAND: ") + t["text"])
        ev = [t["t"] for t in conv.s["trace"] if t["t"] in ("guardrail_reply_blocked", "fallback_reply_used", "tool_format_error", "llm_error")]
        print(f"-- outcome={conv.s['outcome']} guardrail_events={ev} models={llm.stats}")
        save_run(conv, ROOT / "runs")
    return conv, db


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], real="--real" in sys.argv)
