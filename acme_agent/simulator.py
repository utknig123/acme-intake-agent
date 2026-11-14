"""LLM-driven candidate personas: lets a presenter (or the eval harness) stress-test the agent with one click."""
from __future__ import annotations

PERSONAS = {
    "cooperative": ("Cooperative", "You are friendly and answer every question clearly and honestly with realistic, valid details."),
    "evasive": ("Evasive / off-topic", "You are distracted. Often dodge the question: crack a joke, ask about stipend or the company, reply 'hmm' or 'ok', or answer a different question. Only after being gently redirected two or three times do you give a real answer."),
    "confused": ("Confused", "You are unsure what this is about. Ask clarifying questions ('why do you need this?', 'is this a scam?'), give ambiguous answers ('around 8', 'sometime next year', 'CS or IT'), then clarify when asked."),
    "busy": ("Busy - later", "You are busy. Answer the identity question, maybe give one detail, then say you must go and ask to continue tomorrow at a specific time."),
    "refuser": ("Refuses a field", "You cooperate, but firmly refuse to share your CGPA (privacy). Refuse again if asked a second time. Answer everything else."),
    "messy": ("Messy / invalid", "You type fast with typos and Hinglish. Give invalid or odd values first: CGPA as a percentage (84%), graduation year 2025, degree 'BBA', a 4-point CGPA, a repo URL for GitHub. Correct yourself only when the agent explains."),
    "angry": ("Upset", "You are irritated at being messaged, complain about spam, threaten to report them, and demand a human. Stay upset."),
    "wrong": ("Wrong person", "You are not the person named. You got a wrong number. Say so politely."),
}

FACTS = ("Your real profile (use these facts when asked, never invent contradicting ones): final-year student, college "
         "'Veermata Jijabai Technological Institute, Mumbai', degree B.Tech, branch Electronics and Telecommunication, "
         "graduating 2027, CGPA 8.3 out of 10, prefers Bengaluru, can start 2027-01-10, wants a 3 month internship, "
         "email {email}, GitHub github.com/{handle}.")


def candidate_reply(llm, persona, record, transcript):
    name, brief = PERSONAS.get(persona, PERSONAS["cooperative"])
    handle = "".join(c for c in (record.get("full_name") or "student").lower() if c.isalpha()) or "student"
    email = f"{handle}@gmail.com"
    system = (f"You are role-playing a job applicant named {record.get('full_name')} chatting on WhatsApp with a company's "
              f"recruiting assistant. Persona: {brief}\n{FACTS.format(email=email, handle=handle)}\n"
              "Write ONLY the applicant's next message: realistic, short (under 25 words), casual. No quotes, no narration.")
    msgs = [{"role": "system", "content": system}]
    for t in transcript[-14:]:
        msgs.append({"role": "assistant" if t["role"] == "candidate" else "user", "content": t["text"]})
    if len(msgs) == 1 or msgs[-1]["role"] != "user":
        msgs.append({"role": "user", "content": "(say something to start)"})
    rep = llm.chat(msgs, None, temperature=0.9, max_tokens=120)
    text = (rep.content or "").strip().strip('"')
    return text[:300] or "ok"
