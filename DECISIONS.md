# Decisions (simple version)

**One idea runs through everything:** the AI does the *talking and deciding*. Plain code does the *checking and saving*. The AI is never trusted to write to the database directly.

## What I chose, and why

| Topic | What I did | Why (plain words) |
|---|---|---|
| Agent, not a script | One AI loop with 3 tools: confirm who it is, save fields, end the chat. | The AI picks what to ask next, so it copes with people answering out of order. |
| Plan before chatting | Code reads the record first and lists: missing, wrong-looking, needs-confirm. If all fine → no chat. | Cheap, predictable, and follows "don't start a conversation if nothing is needed". |
| Stop the AI making things up | A value is saved only if (1) the candidate really said it (we check the quote), (2) it passes strict rules, (3) identity is confirmed. | Stops invented data reaching the database. |
| Claims can't be faked | "Completed" is accepted only after re-reading the database. Replies like "I've saved it" with no save are blocked. | The AI can't just say it's done. |
| No garbled replies | Every reply is scanned; bad ones are regenerated, and if still bad a clean built-in question is sent instead. | A candidate never sees broken text. |
| Spoken numbers | "two thousand four", "twenty twenty seven", "eight point four" are converted to digits. | People type how they talk. |
| Background checks | Email domain is checked to really exist (DNS), disposable emails flagged, GitHub username checked. If the check can't run, we just continue. | Catches typos like `gmial.com` or fake handles without annoying people. |
| Don't overwrite | Only changed fields are sent; valid existing values need the candidate to say "that changed"; notes are appended, never replaced. | Required by the assignment. |
| Safe writes | Version check (`If-Match`), unique `Idempotency-Key`, re-read and merge on conflict, retry with waits on errors. | No lost or double updates. |
| Candidate drifts off-topic | A "stall" counter: gently re-ask, then offer options, then offer to pause, then end politely. | Brings them back without nagging. |
| Outcome rules | completed / in_progress / refused / needs_human / no_answer each have checks. Leaving or silence is closed by code (no AI needed). | Predictable statuses. |
| Follow-ups | If they say "call me tomorrow 6pm", the time is saved in the notes as `follow_up_at`. | Next run can pick up exactly there. |
| 3-model fallback | Groq gpt-oss-120b → Gemini 2.5 Flash → Groq gpt-oss-20b; waits out rate limits. | Free tiers get throttled. (Gemini needs a free key in `.env`.) |
| Hosting | One AWS Lambda serves UI + API. Chat state travels as a signed token (no database needed). Frontend can also go on Vercel. | Simplest thing that works. |

## Project-manager feature: the Work Queue
A recruiter sees **who to contact next and why**: overdue follow-ups first, "almost done" candidates next (quick wins), repeated no-answers pushed down, and escalated cases shown as "Human review". A funnel shows % complete. It uses only data the agent already writes, so no extra setup.

## Known limits (honest)
- A web chat is closed as "abandoned" only if the browser tells us (closing the tab or 5 min idle).
- Groq free tier is ~8,000 tokens/min, so a long chat can pause briefly.
- The public URL has no login; anyone with the link can use it. Add a login before real use.
- Chat token is signed, not encrypted.
- Vercel anonymous deployments expire after 60 min; `scripts/vercel_keepalive.py` redeploys every 45 min, or log in once for a permanent one.

## What I'd build next
1. Real scheduler that auto-starts chats when `follow_up_at` arrives.
2. Database-backed sessions + sweeper for abandoned chats.
3. Login for the UI; secrets in AWS Secrets Manager.
4. WhatsApp integration; more languages.
5. College-name verification against a university list.
