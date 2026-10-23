import threading
from pathlib import Path

import app as app_module

app = app_module.app


OPERATION_ID = "race-test-001"
PAYLOAD = {"operation_id": OPERATION_ID}


def _count_records(client):
    response = client.get("/status")
    assert response.status_code == 200
    return sum(
        item["operation_id"] == OPERATION_ID
        for item in response.get_json()["submissions"]
    )


def run_case(label, use_idempotency):
    with app.test_client() as client:
        reset = client.post("/reset")
        assert reset.status_code == 200, reset.get_json()

    entered_precommit = threading.Event()
    allow_commit = threading.Event()
    original_result = []
    original_error = []

    def pre_commit_hook(_operation_id):
        assert _operation_id == OPERATION_ID
        if not entered_precommit.is_set():
            entered_precommit.set()
            allow_commit.wait(timeout=5)

    app.config["PRE_COMMIT_HOOK"] = pre_commit_hook

    def original_request():
        try:
            with app.test_client() as client:
                response = client.post(
                    "/submit?delay=0&commit_delay=0",
                    json=PAYLOAD,
                    headers=(
                        {"Idempotency-Key": "race-key-001"}
                        if use_idempotency else {}
                    ),
                )
                original_result.append(
                    (response.status_code, response.get_json())
                )
        except Exception as exc:
            original_error.append(exc)

    original = threading.Thread(
        target=original_request,
        name=f"scenario12-{label}",
        daemon=False,
    )
    original.start()
    try:
        assert entered_precommit.wait(timeout=2), (
            "Original request did not enter the pre-commit hook."
        )

        with app.test_client() as client:
            probe = client.get(f"/test/inflight/{OPERATION_ID}")
            assert probe.status_code == 200
            assert probe.get_json() == {
                "operation_id": OPERATION_ID,
                "in_flight": True,
                "recorded": False,
            }
            before_retry = _count_records(client)
            assert before_retry == 0

            retry = client.post(
                "/submit?delay=0&commit_delay=0",
                json=PAYLOAD,
                headers=(
                    {"Idempotency-Key": "race-key-001"}
                    if use_idempotency else {}
                ),
            )
            assert retry.status_code == 200, retry.get_json()
            retry_result = retry.get_json()
    finally:
        allow_commit.set()
        original.join(timeout=5)
        app.config.pop("PRE_COMMIT_HOOK", None)

    assert not original.is_alive(), "Original request thread did not finish."
    assert not original_error, f"Original request failed: {original_error}"
    assert original_result and original_result[0][0] == 200

    with app.test_client() as client:
        final_count = _count_records(client)

    expected_count = 1 if use_idempotency else 2
    assert final_count == expected_count, (
        f"{label}: expected {expected_count} records, got {final_count}"
    )
    if use_idempotency:
        assert retry_result["duplicate"] is True
        assert retry_result["in_progress"] is True

    result = {
        "label": label,
        "records_before_retry": before_retry,
        "retry": retry_result,
        "original": original_result[0][1],
        "final_records": final_count,
    }
    print(f"\nCASE: {label}")
    print(f"Records before retry (original is in pre-commit hook): {before_retry}")
    print(f"Retry response: {retry_result}")
    print(f"Original response: {original_result[0][1]}")
    print(f"Final records after both requests completed: {final_count}")
    return result


def main():
    app.config["TESTING"] = True
    print("Scenario 12: synchronized in-process pre-commit race")
    print(f"Resolved app: {Path(app_module.__file__).resolve()}")
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule}")
    run_case("Blind retry without idempotency", False)
    run_case("Retry with same idempotency key", True)


if __name__ == "__main__":
    main()
