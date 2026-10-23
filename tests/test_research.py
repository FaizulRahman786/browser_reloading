import threading
import unittest
from datetime import datetime, timezone

from app import app
from scenario11_evidence_freshness import (
    decide_recovery,
    hash_payload,
    make_evidence,
    validate_evidence,
)
from scenario12_inflight_race import run_case
from werkzeug.serving import make_server


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config.pop("PRE_COMMIT_HOOK", None)
        with app.test_client() as client:
            response = client.post("/reset")
            self.assertEqual(response.status_code, 200, response.get_json())

    def tearDown(self):
        app.config.pop("PRE_COMMIT_HOOK", None)
        with app.test_client() as client:
            response = client.post("/reset")
            self.assertEqual(response.status_code, 200, response.get_json())

    def test_normal_successful_submission(self):
        with app.test_client() as client:
            response = client.post(
                "/submit?delay=0",
                json={"operation_id": "normal-001"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.get_json()["duplicate"])
            status = client.get("/status")
            self.assertEqual(status.get_json()["total_submissions"], 1)

    def test_blind_retry_can_create_duplicate_records(self):
        with app.test_client() as client:
            for _ in range(2):
                response = client.post(
                    "/submit?delay=0",
                    json={"operation_id": "blind-001"},
                )
                self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get("/status").get_json()["total_submissions"], 2)

    def test_same_key_same_payload_reuses_operation(self):
        with app.test_client() as client:
            headers = {"Idempotency-Key": "same-key"}
            first = client.post(
                "/submit?delay=0",
                json={"operation_id": "same-001"},
                headers=headers,
            )
            second = client.post(
                "/submit?delay=0",
                json={"operation_id": "same-001"},
                headers=headers,
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertTrue(second.get_json()["duplicate"])
            self.assertEqual(client.get("/status").get_json()["total_submissions"], 1)

    def test_same_key_different_payload_returns_conflict(self):
        with app.test_client() as client:
            headers = {"Idempotency-Key": "conflict-key"}
            first = client.post(
                "/submit?delay=0",
                json={"operation_id": "conflict-A"},
                headers=headers,
            )
            second = client.post(
                "/submit?delay=0",
                json={"operation_id": "conflict-B"},
                headers=headers,
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 409)
            self.assertEqual(client.get("/status").get_json()["total_submissions"], 1)

    def test_timeout_does_not_imply_failure_and_operation_commits_later(self):
        entered_precommit = threading.Event()
        allow_commit = threading.Event()
        response_received = threading.Event()
        response_result = []
        thread_errors = []

        def hold_before_commit(_operation_id):
            self.assertEqual(_operation_id, "late-commit")
            entered_precommit.set()
            if not allow_commit.wait(timeout=5):
                raise TimeoutError("Test did not release pre-commit request.")

        app.config["PRE_COMMIT_HOOK"] = hold_before_commit

        def request_in_background():
            try:
                with app.test_client() as client:
                    response = client.post(
                        "/submit?delay=0",
                        json={"operation_id": "late-commit"},
                    )
                    response_result.append(response.status_code)
            except Exception as exc:
                thread_errors.append(exc)
            finally:
                response_received.set()

        request_thread = threading.Thread(target=request_in_background)
        request_thread.start()
        try:
            self.assertTrue(entered_precommit.wait(timeout=2))
            self.assertFalse(response_received.wait(timeout=0.02))
            with app.test_client() as client:
                observed = client.get("/status").get_json()
                self.assertEqual(observed["total_submissions"], 0)
            self.assertFalse(response_received.is_set())
        finally:
            allow_commit.set()
            request_thread.join(timeout=5)

        self.assertFalse(request_thread.is_alive())
        self.assertEqual(thread_errors, [])
        self.assertEqual(response_result, [200])
        with app.test_client() as client:
            self.assertEqual(client.get("/status").get_json()["total_submissions"], 1)

    def test_status_availability_and_missing_status_remain_unresolved(self):
        now = datetime.now(timezone.utc)
        payload_hash = hash_payload({"operation_id": "missing-status"})
        with app.test_client() as client:
            self.assertEqual(client.get("/status").status_code, 200)
            missing = client.get("/test/no-such-status-service")
            self.assertEqual(missing.status_code, 404)

        decision, validations = decide_recovery(
            [], "missing-status", payload_hash, now
        )
        self.assertEqual(decision, "UNKNOWN_DEFER")
        self.assertEqual(validations, [])

    def test_invalid_input_is_rejected(self):
        with app.test_client() as client:
            response = client.post("/submit?delay=0", json={"operation_id": ""})
            invalid_delay = client.post(
                "/submit?delay=not-a-number",
                json={"operation_id": "invalid-delay"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(invalid_delay.status_code, 400)

    def test_reset_is_rejected_while_request_is_in_flight(self):
        entered_precommit = threading.Event()
        allow_commit = threading.Event()
        thread_errors = []

        def hold_before_commit(_operation_id):
            self.assertEqual(_operation_id, "reset-in-flight")
            entered_precommit.set()
            if not allow_commit.wait(timeout=5):
                raise TimeoutError("Test did not release pre-commit request.")

        app.config["PRE_COMMIT_HOOK"] = hold_before_commit

        def request_in_background():
            try:
                with app.test_client() as client:
                    response = client.post(
                        "/submit?delay=0",
                        json={"operation_id": "reset-in-flight"},
                    )
                    self.assertEqual(response.status_code, 200)
            except Exception as exc:
                thread_errors.append(exc)

        request_thread = threading.Thread(target=request_in_background)
        request_thread.start()
        try:
            self.assertTrue(entered_precommit.wait(timeout=2))
            with app.test_client() as client:
                reset = client.post("/reset")
                self.assertEqual(reset.status_code, 409)
        finally:
            allow_commit.set()
            request_thread.join(timeout=5)

        self.assertFalse(request_thread.is_alive())
        self.assertEqual(thread_errors, [])
        with app.test_client() as client:
            self.assertEqual(client.post("/reset").status_code, 200)
            self.assertEqual(client.get("/status").get_json()["total_submissions"], 0)

    def test_unexpected_server_error_is_visible_and_cleans_inflight_state(self):
        app.config["PROPAGATE_EXCEPTIONS"] = False

        def fail_before_commit(_operation_id):
            self.assertEqual(_operation_id, "server-error")
            raise RuntimeError("injected test failure")

        app.config["PRE_COMMIT_HOOK"] = fail_before_commit
        with app.test_client() as client:
            response = client.post(
                "/submit?delay=0",
                json={"operation_id": "server-error"},
            )
            self.assertEqual(response.status_code, 500)
            state = client.get("/test/inflight/server-error").get_json()
            self.assertFalse(state["in_flight"])

    def test_scenario12_synchronized_precommit_race(self):
        blind = run_case("test blind race", False)
        protected = run_case("test idempotent race", True)
        self.assertEqual(blind["records_before_retry"], 0)
        self.assertEqual(blind["final_records"], 2)
        self.assertEqual(protected["records_before_retry"], 0)
        self.assertEqual(protected["final_records"], 1)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.payload_hash = hash_payload({"action": "submit"})
        self.operation_id = "evidence-001"

    def _evidence(self, **kwargs):
        return make_evidence(
            self.operation_id,
            self.payload_hash,
            "COMMITTED",
            "mock-source",
            self.now,
            **kwargs,
        )

    def test_fresh_matching_committed_evidence(self):
        evidence = self._evidence()
        decision, _ = decide_recovery(
            [evidence], self.operation_id, self.payload_hash, self.now
        )
        self.assertEqual(decision, "CONFIRMED_COMMITTED_NO_RETRY")

    def test_fresh_absent_is_an_observation_not_proof_of_finality(self):
        evidence = make_evidence(
            self.operation_id,
            self.payload_hash,
            "ABSENT",
            "mock-source",
            self.now,
        )
        decision, _ = decide_recovery(
            [evidence], self.operation_id, self.payload_hash, self.now
        )
        self.assertEqual(decision, "OBSERVED_ABSENT_RETRY_WITH_SAME_KEY")

    def test_stale_evidence_is_rejected(self):
        result = validate_evidence(
            self._evidence(age_seconds=30),
            self.operation_id,
            self.payload_hash,
            self.now,
        )
        self.assertFalse(result["usable"])
        self.assertIn("evidence_stale", result["reasons"])

    def test_payload_hash_mismatch_is_rejected(self):
        result = validate_evidence(
            make_evidence(
                self.operation_id,
                "wrong",
                "COMMITTED",
                "mock-source",
                self.now,
            ),
            self.operation_id,
            self.payload_hash,
            self.now,
        )
        self.assertFalse(result["usable"])
        self.assertIn("payload_hash_mismatch", result["reasons"])

    def test_untrusted_source_is_rejected(self):
        result = validate_evidence(
            self._evidence(source_trusted=False),
            self.operation_id,
            self.payload_hash,
            self.now,
        )
        self.assertFalse(result["usable"])
        self.assertIn("source_not_trusted", result["reasons"])

    def test_conflicting_usable_evidence_is_deferred(self):
        committed = self._evidence()
        absent = make_evidence(
            self.operation_id,
            self.payload_hash,
            "ABSENT",
            "other-mock-source",
            self.now,
        )
        decision, _ = decide_recovery(
            [committed, absent],
            self.operation_id,
            self.payload_hash,
            self.now,
        )
        self.assertEqual(decision, "UNKNOWN_DEFER")

    def test_future_dated_evidence_is_rejected(self):
        future = self._evidence(age_seconds=-5)
        result = validate_evidence(
            future,
            self.operation_id,
            self.payload_hash,
            self.now,
        )
        self.assertFalse(result["usable"])
        self.assertIn("observation_time_in_future", result["reasons"])

    def test_evidence_from_a_different_operation_is_rejected(self):
        result = validate_evidence(
            self._evidence(),
            "different-operation",
            self.payload_hash,
            self.now,
        )
        self.assertFalse(result["usable"])
        self.assertIn("operation_id_mismatch", result["reasons"])


class ServerLifecycleTests(unittest.TestCase):
    def test_local_server_starts_serves_and_shuts_down(self):
        server = make_server("127.0.0.1", 0, app, threaded=True)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        try:
            import urllib.request

            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/status",
                timeout=2,
            ) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=3)

        self.assertFalse(server_thread.is_alive())


if __name__ == "__main__":
    unittest.main()
