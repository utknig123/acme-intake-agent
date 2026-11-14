# How it works + presentation script

## In one sentence
You give it a candidate ID. It reads the record, works out what's missing or wrong, chats with the candidate like a recruiter, validates every answer, saves only safe data, and records how the chat ended.

## What it does (feature list)
- Reads the record and **audits** it: missing fields, wrong-looking existing data (CGPA 85, `kabir@gmail`, year 2031), placeholders ("N/A"), fixable format issues.
- **No chat if nothing is needed** (record is just marked completed).
- Greets, **confirms identity by name** (never asks for an ID), then collects fields in natural groups.
- Understands messy answers: "bangalore", "btech", "1st June", "two thousand twenty seven", "eight point four".
- Handles exceptions: busy/later, refusal, invalid answers, off-topic/dodging, upset, wrong person, silence.
- Verifies in the background: email domain exists, not disposable, GitHub username exists.
- Saves safely (version check, idempotency, conflict merge, retries) and **never overwrites** valid data.
- Writes outcome: `completed`, `in_progress` (with follow-up time), `refused` (which fields), `needs_human`, `no_answer`; attempts, last-contact time, notes.
- **Work Queue** for recruiters: who next and why, plus a completion funnel.
- Frontend shows the chat plus an **Agent view**: tool calls, DB writes, before/after record with the candidate's own quote as proof.

## Architecture (say this in 3 minutes)
```
Browser / terminal
   │  message
   ▼
Conversation (acme_agent/agent.py)
   │ 1. audit record  ───────────────►  Candidate DB API (GET)
   │ 2. build prompt: rules + live state (missing / wrong / notes / stalls)
   │ 3. LLM decides → calls a tool
   │        confirm_identity · save_fields · end_conversation
   │ 4. GUARDRAILS run in code before anything is saved:
   │        quote really said by candidate? · valid format/range? · identity confirmed?
   │        existing value protected? · email/GitHub real? · "completed" true after re-read?
   │ 5. write ───────────────────────►  Candidate DB API (PATCH + If-Match + Idempotency-Key)
   │ 6. reply scanned (no garbage / no false "saved" / no leaks) → shown to candidate
   ▼
LLM chain: Groq 120b → Gemini → Groq 20b (auto fallback, waits out rate limits)
```
State lives in the chat (a signed token on the web, memory in the terminal). The database is always the source of truth.

## Live demo flow (about 8 minutes)
1. **Work Queue** (left): "this is what a recruiter sees: next best action per candidate". Point at the funnel.
2. **c002** (3 fields missing): show the **Plan** tab first (the agent decided what to ask). Chat: confirm identity, then answer **"twenty twenty seven"** and **"two thousand and... six months"** → show numbers saved correctly in **Record** with your quote as proof.
3. **c005** (bad email `kabir.shah@gmail`): agent notices the existing data is wrong and asks to fix it. Give an email with a fake domain → show the background check pushing back.
4. **Exceptions** on any candidate: reply "lol" twice (agent re-anchors), then "busy, message me tomorrow 6pm" → outcome `in_progress`, follow-up time shown in the **Hand-off** tab and the notes.
5. **c008** (graduation year 2031): say "2025" → agent explains the 2026-2028 rule and escalates to `needs_human` if impossible.
6. **c003 or c006** (already complete): "no chat started, nobody bothered".
7. Show **Activity** tab: every tool call and PATCH; mention rejected hallucination if one appears.
8. Close with limits + next steps (from DECISIONS.md).

## Likely questions → short answers
- *How do you stop hallucinations?* Quote must come from the candidate; strict validators; completion verified by re-reading the DB; replies scanned.
- *Is it a script?* No. The LLM chooses questions and tools; code only enforces rules.
- *Rate limits?* 3-model fallback and waiting; deterministic fallback question if all fail.
- *Abandoned chats?* `/quit`, idle timeout, closing the tab → `no_answer` or `in_progress`, attempts +1, note of what's left.
- *Two writers at once?* `If-Match` version; on 409 re-read and merge, never overwrite someone else's value.
- *What's unique?* Work Queue with follow-up scheduling, background verification, spoken-number understanding, proof quotes per field.

## How to run
```bash
python agent.py --candidate-id c002      # terminal
python -m acme_agent.local               # web UI http://127.0.0.1:8080
python -m unittest discover -s tests     # 23 offline tests
python scripts/aws_tool.py deploy        # AWS
```
Live: https://kcjwxwjdaefxakn7l6nrtntqnu0ronmo.lambda-url.ap-south-1.on.aws/
