from __future__ import annotations

import phase5_paper_pipeline as pipeline


def test_pipeline_stops_before_execution_when_qualification_is_killed(monkeypatch):
    killed = {"status": "killed", "paper_only": True, "live_execution_allowed": False}
    monkeypatch.setattr(pipeline, "qualify", lambda *_: killed)
    result = pipeline.run_paper_validation_pipeline({}, {}, {}, [], initial_equity=1000)
    assert result["pipeline_status"] == "qualification_rejected"
    assert result["paper_report"] is None
    assert result["live_execution_allowed"] is False


def test_pipeline_connects_candidate_to_paper_evaluator(monkeypatch):
    candidate = {"status": "paper_candidate", "paper_only": True, "live_execution_allowed": False}
    report = {"status": "observing", "paper_only": True, "live_execution_allowed": False}
    monkeypatch.setattr(pipeline, "qualify", lambda *_: candidate)
    monkeypatch.setattr(pipeline, "evaluate_paper_candidate", lambda *args, **kwargs: report)
    result = pipeline.run_paper_validation_pipeline({}, {}, {}, [], initial_equity=1000)
    assert result["pipeline_status"] == "observing"
    assert result["qualification"] is candidate
    assert result["paper_report"] is report
    assert result["live_execution_allowed"] is False
