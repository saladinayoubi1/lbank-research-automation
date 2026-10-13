"""Exercise the actual workflow guards without executing research or Paper jobs."""
from __future__ import annotations

import ast
import copy
import re
import unittest
from pathlib import Path
from typing import Any

from scripts.check_workflow_permissions import load_yaml


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY = "nexus_multitimeframe_strategy_discovery.yml"
ROTATION = "nexus_strategy_discovery_rotation.yml"
REQUALIFICATION = "nexus_strategy_proposal_runtime_requalification.yml"
MULTIPAIR = "nexus_multipair_strategy_discovery_v2.yml"


def _condition(expression: str, github: dict[str, Any], needs: dict[str, Any] | None = None) -> bool:
    """Evaluate only the boolean/string subset used by these GitHub guards.

    No eval or arbitrary calls are allowed; only always() is supported as a
    GitHub status primitive. Missing event
    properties resolve to an empty string, as in GitHub Actions expressions.
    """
    expression = expression.strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    # GitHub job identifiers permit hyphens in dotted needs references.
    expression = re.sub(r"\bneeds\.([A-Za-z0-9_-]+)", lambda match: "needs." + match[1].replace("-", "_"), expression)
    contexts = {"github": github, "needs": {key.replace("-", "_"): value for key, value in (needs or {}).items()}}
    tree = ast.parse("(" + expression.replace("&&", " and ").replace("||", " or ") + ")", mode="eval")

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name) and node.id in contexts:
            return contexts[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "always" and not node.args and not node.keywords:
            return True
        if isinstance(node, ast.Attribute):
            parent = visit(node.value)
            return parent.get(node.attr, "") if isinstance(parent, dict) else ""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(visit(value)) for value in node.values)
            if isinstance(node.op, ast.Or):
                return any(bool(visit(value)) for value in node.values)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = visit(node.left), visit(node.comparators[0])
            if isinstance(left, str) and isinstance(right, str):
                left, right = left.casefold(), right.casefold()
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise ValueError(f"unsupported guard syntax: {type(node).__name__}")

    return bool(visit(tree))


def _context(event: str, ref: str = "refs/heads/main") -> dict[str, Any]:
    return {
        "event_name": event,
        "ref": ref,
        "sha": "a" * 40,
        "repository": "owner/research",
        "event": {
            "workflow_run": {
                "name": "NEXUS multi-timeframe strategy discovery",
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": "a" * 40,
                "head_repository": {"full_name": "owner/research"},
                "conclusion": "success",
            }
        } if event == "workflow_run" else {},
    }


class ResearchWorkflowExecutionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflows = {
            name: load_yaml(ROOT / ".github" / "workflows" / name)
            for name in (DISCOVERY, ROTATION, REQUALIFICATION, MULTIPAIR)
        }

    def allowed(self, workflow: str, job: str, context: dict[str, Any]) -> bool:
        jobs = self.workflows[workflow]["jobs"]
        expression = jobs[job].get("if")
        if expression and not _condition(expression, context):
            return False
        # These consumers require the successful contract job. A source-stale
        # workflow_run must not execute after its contract job was skipped.
        dependency = jobs[job].get("needs")
        if dependency:
            self.assertEqual(dependency, "contract-test")
            prerequisite = jobs[dependency].get("if")
            if prerequisite and not _condition(prerequisite, context):
                return False
        return True

    def test_discovery_event_matrix(self) -> None:
        for event in ("push", "pull_request", "workflow_dispatch", "schedule", "repository_dispatch"):
            for ref in ("refs/heads/main", "refs/heads/feature"):
                with self.subTest(event=event, ref=ref):
                    self.assertEqual(
                        self.allowed(DISCOVERY, "discover", _context(event, ref)),
                        event == "workflow_dispatch" and ref == "refs/heads/main",
                    )

    def test_rotation_event_matrix(self) -> None:
        for event in ("push", "pull_request", "workflow_dispatch", "schedule", "repository_dispatch"):
            for ref in ("refs/heads/main", "refs/heads/feature"):
                with self.subTest(event=event, ref=ref):
                    self.assertEqual(
                        self.allowed(ROTATION, "dispatch-one-stage", _context(event, ref)),
                        event in {"workflow_dispatch", "schedule"} and ref == "refs/heads/main",
                    )

    def test_multipair_entire_pipeline_requires_main_dispatch(self) -> None:
        # Deliberately provide successful parents and nonempty old outputs:
        # even that context cannot turn a code-only push into fresh evidence.
        needs = {
            "runtime-snapshot": {"result": "success", "outputs": {"runtime_snapshot_archive_chunk_count": "1"}},
            "requalify-physical": {"result": "success", "outputs": {"proof_b64": "synthetic-proof"}},
        }
        for job, definition in self.workflows[MULTIPAIR]["jobs"].items():
            if job == "contract-test":
                continue
            for event in ("push", "pull_request", "workflow_dispatch", "schedule", "repository_dispatch", "workflow_run"):
                for ref in ("refs/heads/main", "refs/heads/feature"):
                    with self.subTest(job=job, event=event, ref=ref):
                        self.assertEqual(
                            _condition(definition["if"], _context(event, ref), needs),
                            event == "workflow_dispatch" and ref == "refs/heads/main",
                        )

    def test_multipair_publishers_keep_parent_result_and_no_work_gates(self) -> None:
        cases = (
            ("persist-runtime-snapshot", "runtime-snapshot", "runtime_snapshot_archive_chunk_count", "1", "0"),
            ("persist-proof", "requalify-physical", "proof_b64", "synthetic-proof", ""),
        )
        for job, parent, field, good_value, no_work in cases:
            definition = self.workflows[MULTIPAIR]["jobs"][job]
            self.assertEqual(definition["needs"], parent)
            for status in ("failure", "cancelled", "skipped"):
                needs = {parent: {"result": status, "outputs": {field: good_value}}}
                with self.subTest(job=job, parent_status=status):
                    self.assertFalse(_condition(definition["if"], _context("workflow_dispatch"), needs))
            needs = {parent: {"result": "success", "outputs": {field: no_work}}}
            with self.subTest(job=job, empty_evidence=True):
                self.assertFalse(_condition(definition["if"], _context("workflow_dispatch"), needs))

    def test_contract_only_discovery_results_cannot_activate_consumers(self) -> None:
        for source_event in ("push", "pull_request", "schedule", "repository_dispatch"):
            context = _context("workflow_run")
            context["event"]["workflow_run"]["event"] = source_event
            for workflow, job in (
                (ROTATION, "dispatch-one-stage"),
                (REQUALIFICATION, "runtime-requalification"),
            ):
                with self.subTest(source_event=source_event, workflow=workflow):
                    self.assertFalse(self.allowed(workflow, job, context))

    def test_actual_dispatched_research_keeps_trusted_consumers(self) -> None:
        for workflow, job in (
            (ROTATION, "dispatch-one-stage"),
            (REQUALIFICATION, "runtime-requalification"),
        ):
            with self.subTest(workflow=workflow):
                self.assertTrue(self.allowed(workflow, job, _context("workflow_run")))
                for key, bad_value in (
                    ("conclusion", "failure"),
                    ("head_branch", "feature"),
                    ("head_repository", {"full_name": "fork/research"}),
                ):
                    context = _context("workflow_run")
                    context["event"]["workflow_run"][key] = bad_value
                    with self.subTest(rejected=key):
                        self.assertFalse(self.allowed(workflow, job, context))

    def test_paper_demo_health_and_source_stale_guards_are_preserved(self) -> None:
        for name in ("NEXUS persistent Paper trading loop", "NEXUS Demo regime lifecycle bridge"):
            for source_event in ("schedule", "workflow_dispatch"):
                context = _context("workflow_run")
                context["event"]["workflow_run"].update(name=name, event=source_event)
                with self.subTest(name=name, event=source_event):
                    self.assertTrue(self.allowed(ROTATION, "dispatch-one-stage", context))
                    stale = copy.deepcopy(context)
                    stale["event"]["workflow_run"]["head_sha"] = "b" * 40
                    self.assertFalse(self.allowed(ROTATION, "dispatch-one-stage", stale))

    def test_push_and_pr_contracts_remain_enabled(self) -> None:
        for workflow in self.workflows:
            for event in ("push", "pull_request"):
                with self.subTest(workflow=workflow, event=event):
                    self.assertTrue(self.allowed(workflow, "contract-test", _context(event)))
                    triggers = self.workflows[workflow].get("on", self.workflows[workflow].get(True))
                    self.assertIn(event, triggers)
                    test_path = "tests/test_nexus_research_workflow_execution_policy.py"
                    self.assertIn(test_path, triggers[event]["paths"])
                    commands = " ".join(
                        step.get("run", "")
                        for step in self.workflows[workflow]["jobs"]["contract-test"]["steps"]
                    )
                    self.assertIn(test_path, commands)

    def test_missing_workflow_run_metadata_fails_closed(self) -> None:
        for workflow, job in (
            (ROTATION, "dispatch-one-stage"),
            (REQUALIFICATION, "runtime-requalification"),
        ):
            context = _context("workflow_run")
            context["event"] = {}
            self.assertFalse(self.allowed(workflow, job, context))


if __name__ == "__main__":
    unittest.main()
