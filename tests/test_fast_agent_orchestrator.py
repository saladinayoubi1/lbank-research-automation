from fast_agent_orchestrator import classify, newest_by_name


def test_classify_states():
    assert classify({"status": "in_progress", "conclusion": None}) == "RUNNING"
    assert classify({"status": "completed", "conclusion": "success"}) == "DONE"
    assert classify({"status": "completed", "conclusion": "failure"}) == "FAILED"
    assert classify({"status": "completed", "conclusion": "cancelled"}) == "BLOCKED"


def test_newest_by_name_keeps_first_seen():
    runs = [
        {"name": "CI", "databaseId": 2},
        {"name": "CI", "databaseId": 1},
        {"name": "Data", "databaseId": 3},
    ]
    latest = newest_by_name(runs)
    assert latest["CI"]["databaseId"] == 2
    assert latest["Data"]["databaseId"] == 3
