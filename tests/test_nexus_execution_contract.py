from __future__ import annotations

from copy import deepcopy
import unittest

from nexus_execution_contract import (
    ExecutionContractError,
    load_contract,
    validate_contract,
    validate_pre_execution_record,
    validate_task_record,
)


def task() -> dict:
    return {
        "task_id": "research-001",
        "lane": "Lane P",
        "deliverable_or_gate": "strategy-candidate",
        "acceptance_criterion": "deterministic OOS evidence is recorded",
        "assigned_resource": "agents",
        "dependencies": [],
        "execution_action": "evaluate bounded hypothesis",
        "verification_method": "independent deterministic replay",
        "durable_evidence_location": "build/evidence/research-001.json",
        "status": "QUEUED",
    }


class NexusExecutionContractTests(unittest.TestCase):
    def test_repository_contract_is_valid(self) -> None:
        load_contract()

    def test_complete_task_is_dispatchable(self) -> None:
        self.assertEqual(validate_task_record(task())["task_id"], "research-001")

    def test_every_required_task_field_is_enforced(self) -> None:
        contract = load_contract()
        for field in contract["requiredPerTask"]:
            with self.subTest(field=field):
                candidate = task()
                del candidate[field]
                with self.assertRaisesRegex(ExecutionContractError, "missing required fields"):
                    validate_task_record(candidate, contract)

    def test_unknown_resource_and_status_fail_closed(self) -> None:
        candidate = task()
        candidate["assigned_resource"] = "unregistered-worker"
        with self.assertRaisesRegex(ExecutionContractError, "not registered"):
            validate_task_record(candidate)
        candidate = task()
        candidate["status"] = "DONE"
        with self.assertRaisesRegex(ExecutionContractError, "unsupported"):
            validate_task_record(candidate)

    def test_every_pre_execution_requirement_must_be_true(self) -> None:
        contract = load_contract()
        record = {key: True for key in contract["requiredBeforeExecution"]}
        self.assertEqual(validate_pre_execution_record(record, contract), record)
        record[contract["requiredBeforeExecution"][0]] = False
        with self.assertRaisesRegex(ExecutionContractError, "not satisfied"):
            validate_pre_execution_record(record, contract)

    def test_disabled_omission_guard_fails_closed(self) -> None:
        contract = deepcopy(load_contract())
        first = next(iter(contract["omissionGuards"]))
        contract["omissionGuards"][first] = False
        with self.assertRaisesRegex(ExecutionContractError, "every omission guard"):
            validate_contract(contract)


if __name__ == "__main__":
    unittest.main()
