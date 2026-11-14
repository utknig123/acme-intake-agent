import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acme_agent import validators as V  # noqa: E402
from acme_agent.agent import Conversation  # noqa: E402
from harness.fakes import FakeDB, ScriptedLLM  # noqa: E402

TODAY = dt.date(2026, 11, 14)
CLOCK = lambda: dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.timezone.utc)  # noqa: E731


def conv(cid, script, db=None, identity=False):
    db = db or FakeDB()
    c, _ = Conversation.start(cid, db, ScriptedLLM(script), CLOCK)
    c.s["identity"] = True if identity else None
    return c, db


def save(*items):
    return ("save_fields", {"fields": [{"field": f, "value": v, "evidence": e} for f, v, e in items]})


class Validators(unittest.TestCase):
    def test_enums_and_numbers(self):
        self.assertEqual(V.validate("degree", "btech").value, "B.Tech")
        self.assertEqual(V.validate("preferred_location", "Bangalore").value, "Bengaluru")
        self.assertFalse(V.validate("degree", "BBA").ok)
        self.assertFalse(V.validate("cgpa", 85).ok)
        self.assertFalse(V.validate("cgpa", "84%").ok)
        self.assertEqual(V.validate("cgpa", "8.456").value, 8.46)
        self.assertTrue(V.validate("cgpa", 3.5).confirm)
        self.assertFalse(V.validate("graduation_year", 2025).ok)
        self.assertFalse(V.validate("internship_duration_months", 4).ok)
        self.assertEqual(V.validate("internship_duration_months", "three months").value, 3)
        self.assertFalse(V.validate("available_from", "2028-01-01", TODAY).ok)
        self.assertFalse(V.validate("available_from", "2027-02-30", TODAY).ok)
        self.assertFalse(V.validate("email", "bad@@x").ok)
        self.assertTrue(V.validate("email", "a@gmial.com").confirm)
        self.assertFalse(V.validate("github_url", "github.com/u/repo").ok)
        self.assertEqual(V.validate("linkedin_url", "linkedin.com/in/aa/").value, "https://linkedin.com/in/aa")

    def test_audit(self):
        db = FakeDB()
        a = V.audit_record(db.rows["c003"], today=TODAY)
        self.assertEqual({i["field"] for i in a.invalid}, {"cgpa", "degree"})
        self.assertTrue(V.audit_record(db.rows["c002"], today=TODAY).complete)
        self.assertIn("college", V.audit_record(db.rows["c007"], today=TODAY).missing)
        self.assertEqual(V.audit_record(db.rows["c005"], today=TODAY).autofix, {"degree": "B.Tech", "cgpa": 8.5})


class AgentGuards(unittest.TestCase):
    def test_complete_record_starts_no_chat(self):
        c, db = conv("c002", [])
        self.assertTrue(c.s["ended"])
        self.assertEqual(c.s["outcome"], "no_action")
        self.assertEqual(db.rows["c002"]["collection_status"], "completed")
        self.assertEqual(db.rows["c002"]["attempt_count"], 0)

    def test_cannot_save_before_identity(self):
        c, db = conv("c001", [save(("branch", "CS", "CS")), "hi"])
        c.turn("CS")
        self.assertEqual(db.writes, [])

    def test_hallucinated_value_rejected(self):
        c, db = conv("c001", [save(("cgpa", 9.1, "my cgpa is 8.4")), "ok"], identity=True)
        c.turn("my cgpa is 8.4")
        self.assertIsNone(db.rows["c001"]["cgpa"])

    def test_fabricated_evidence_rejected(self):
        c, db = conv("c001", [save(("email", "z@z.com", "z@z.com")), "ok"], identity=True)
        c.turn("I would rather not say")
        self.assertEqual(db.writes, [])

    def test_good_save_and_no_overwrite(self):
        c, db = conv("c001", [save(("branch", "computer science", "I study computer science"),
                                   ("college", "IIT Delhi", "IIT Delhi")), "done"], identity=True)
        c.turn("I study computer science at IIT Delhi")
        r = db.rows["c001"]
        self.assertEqual(r["branch"], "Computer Science")
        self.assertEqual(r["college"], "VJTI Mumbai")
        self.assertEqual(r["collection_status"], "in_progress")
        self.assertEqual(len(db.writes), 1)

    def test_claim_without_save_is_blocked(self):
        c, db = conv("c001", ["I've saved your details!", "Which college do you attend?"], identity=True)
        self.assertIn("college", c.turn("my cgpa is 8.4"))

    def test_leak_before_identity_blocked(self):
        c, db = conv("c001", ["Is aarav@example.com still correct?", "Am I speaking with Aarav Sharma?"])
        self.assertIn("Aarav", c.turn("hello"))

    def test_completed_rejected_if_incomplete(self):
        c, db = conv("c001", [("end_conversation", {"outcome": "completed", "summary": "all done", "final_message": "bye"}),
                              "still need a few things"], identity=True)
        c.turn("that is all")
        self.assertFalse(c.s["ended"])
        self.assertEqual(db.rows["c001"]["collection_status"], "pending")

    def test_full_flow_completed(self):
        script = [save(("branch", "Electronics", "Electronics"), ("graduation_year", 2027, "2027"),
                       ("cgpa", 8.2, "8.2"), ("preferred_location", "Remote", "remote"),
                       ("available_from", "2027-01-15", "15 jan 2027"), ("internship_duration_months", 6, "6 months")),
                  ("end_conversation", {"outcome": "completed", "summary": "All collected", "final_message": "Thanks!"})]
        c, db = conv("c001", script, identity=True)
        out = c.turn("Electronics, 2027, 8.2, remote, 15 jan 2027, 6 months")
        r = db.rows["c001"]
        self.assertTrue(c.s["ended"])
        self.assertEqual((r["collection_status"], r["attempt_count"]), ("completed", 1))
        self.assertTrue(r["last_contacted_at"].endswith("+05:30"))
        self.assertEqual(out, "Thanks!")

    def test_abandon_paths(self):
        c, db = conv("c001", [])
        c.abandon("no reply")
        r = db.rows["c001"]
        self.assertEqual((r["collection_status"], r["attempt_count"]), ("no_answer", 1))
        c, db = conv("c001", [save(("branch", "IT", "IT")), "ok"], identity=True)
        c.turn("IT")
        c.abandon("left")
        self.assertEqual(db.rows["c001"]["collection_status"], "in_progress")
        self.assertIn("Still needed", db.rows["c001"]["notes"])

    def test_conflict_and_outage(self):
        db = FakeDB(conflict_next=1)
        c, _ = conv("c004", [save(("branch", "IT", "IT")), "ok"], db, identity=True)
        c.turn("IT")
        self.assertEqual(db.rows["c004"]["branch"], "IT")
        db = FakeDB(fail_next=10)
        c, _ = conv("c004", [save(("branch", "IT", "IT")), "ok"], db, identity=True)
        c.turn("IT")
        self.assertEqual(c.s["unsaved"], {"branch": "IT"})

    def test_attempt_cap(self):
        c, db = conv("c008", [])
        c.abandon("x")
        self.assertEqual(db.rows["c008"]["attempt_count"], 50)

    def test_autofix_piggybacks(self):
        c, db = conv("c005", [])
        self.assertTrue(c.s["ended"])
        r = db.rows["c005"]
        self.assertEqual((r["degree"], r["cgpa"], r["collection_status"]), ("B.Tech", 8.5, "completed"))


if __name__ == "__main__":
    unittest.main()


class Robustness(unittest.TestCase):
    def test_garbled_detector(self):
        from acme_agent.agent import garbled
        self.assertTrue(garbled("Where ? \n\n\n\nWe \u2026 \u2026 \u2026 \u2026"))
        self.assertTrue(garbled("ok ok ok ok ok ok"))
        self.assertTrue(garbled('{"name": "commentary", "arguments": {}}'))
        self.assertFalse(garbled("Thanks Aarav! Could you share your CGPA out of 10?"))
        self.assertFalse(garbled("Great, noted. Kab se start kar sakte ho?"))

    def test_garbage_never_reaches_candidate(self):
        bad = "Where ? \n\n\n\n\u2026 \u2026 \u2026 \u2026 \u2026"
        c, db = conv("c001", [bad, bad, bad, bad], identity=True)
        out = c.turn("hello")
        self.assertIn("Could you share", out)           # deterministic fallback question
        self.assertFalse(any("\u2026 \u2026" in t["text"] for t in c.s["transcript"]))

    def test_stall_counter_and_followup(self):
        c, db = conv("c001", ["Sure! Which branch are you in?", "Okay, which branch?",
                              ("end_conversation", {"outcome": "in_progress", "summary": "busy, wants a call tomorrow",
                                                    "follow_up_time": "2026-11-15T18:00:00+05:30", "final_message": "Talk soon!"})],
                      identity=True)
        c.turn("lol")
        self.assertEqual(c.s["stalls"], 1)
        c.turn("hmm")
        self.assertEqual(c.s["stalls"], 2)
        c.turn("tomorrow 6pm please")
        self.assertIn("follow_up_at=2026-11-15T18:00", db.rows["c001"]["notes"])
        self.assertEqual(db.rows["c001"]["collection_status"], "in_progress")

    def test_suspicious_existing_value_can_be_replaced(self):
        c, db = conv("c004", [save(("email", "sneha.iyer@gmail.com", "sneha.iyer@gmail.com")), "ok"], identity=True)
        c.turn("sneha.iyer@gmail.com")
        self.assertEqual(db.rows["c004"]["email"], "sneha.iyer@gmail.com")

    def test_enum_grounding(self):
        c, db = conv("c001", [save(("preferred_location", "Mumbai", "my cgpa is 8")), "ok"], identity=True)
        c.turn("my cgpa is 8")
        self.assertIsNone(db.rows["c001"]["preferred_location"])


class SpokenNumbers(unittest.TestCase):
    def test_numberize(self):
        from acme_agent.numwords import numberize as n
        self.assertEqual(n("two thousand four"), "2004")
        self.assertEqual(n("I graduate in twenty twenty seven"), "I graduate in 2027")
        self.assertEqual(n("cgpa is eight point four"), "cgpa is 8.4")
        self.assertEqual(n("six months please"), "6 months please")

    def test_spoken_values_validate_and_ground(self):
        self.assertEqual(V.validate("graduation_year", "two thousand twenty seven").value, 2027)
        self.assertEqual(V.validate("cgpa", "eight point four").value, 8.4)
        c, db = conv("c001", [save(("graduation_year", 2027, "twenty twenty seven"), ("cgpa", 8.4, "eight point four")), "ok"], identity=True)
        c.turn("twenty twenty seven and eight point four")
        self.assertEqual((db.rows["c001"]["graduation_year"], db.rows["c001"]["cgpa"]), (2027, 8.4))

    def test_queue_ranking(self):
        from acme_agent import queue as Q
        rows = list(FakeDB().rows.values())
        q = Q.build(rows)
        self.assertEqual(q["funnel"]["pending"], 7)
        self.assertTrue(all(i["id"] != "c002" for i in q["queue"]))       # complete records are not queued


class FailClosedVerification(unittest.TestCase):
    def _save_email(self, status, confirmed=False):
        from unittest import mock
        item = {"field": "email", "value": "sneha@gmail.com", "evidence": "sneha@gmail.com"}
        if confirmed:
            item["confirmed"] = True
        c, db = conv("c004", [("save_fields", {"fields": [item]}), "ok"], identity=True)
        with mock.patch("acme_agent.verify.check", return_value=(status, "reason")):
            c.turn("sneha@gmail.com")
        return c, db

    def test_unverifiable_is_flagged_not_saved(self):
        c, db = self._save_email("unverified")
        self.assertEqual(db.rows["c004"]["email"], "sneha@gmial.com")      # unchanged: needs confirmation

    def test_bad_is_flagged_not_saved(self):
        c, db = self._save_email("bad")
        self.assertEqual(db.rows["c004"]["email"], "sneha@gmial.com")

    def test_verified_is_saved_and_scored(self):
        c, db = self._save_email("verified")
        self.assertEqual(db.rows["c004"]["email"], "sneha@gmail.com")
        self.assertEqual(c.s["verifications"]["email"]["status"], "verified")

    def test_candidate_confirmed_unverified_is_labelled(self):
        c, db = self._save_email("unverified", confirmed=True)
        self.assertEqual(db.rows["c004"]["email"], "sneha@gmail.com")
        c.s["identity"] = True
        c.abandon("left")
        self.assertIn("UNVERIFIED", db.rows["c004"]["notes"])
        self.assertIn("Quality", db.rows["c004"]["notes"])
