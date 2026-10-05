from pathlib import Path

import agent_manager
import nexus_composite_strategy_research as research
from nexus_mechanism_factory import (
    generate_factory_contracts,
    generate_factory_contracts_v3,
    load_factory_contract,
)
from nexus_research_missions import (
    FOURTEENTH, THIRTEENTH, TWELFTH, FIFTEENTH, SIXTEENTH, SEVENTEENTH,
    PREDECESSOR, TASKS,
)


def _ledger_after_fixed_frontier():
    state = research.empty_ledger()
    core = {k: v for k, v in state.items() if k != "ledger_digest"}
    core["mechanisms_evaluated"] = sorted(research.MECHANISMS)
    core["frontier_screening_version"] = "nexus.frontier-train-screen.v3"
    core["frontier_screened_mechanisms"] = sorted(
        research.FRONTIER_GENERATION1
        + research.FRONTIER_GENERATION2
        + research.FIXED_FACTORY_MECHANISMS
    )
    return {**core, "ledger_digest": research.digest(core)}


def test_generator_builds_unique_reviewed_topologies():
    fixed = load_factory_contract()
    generated = generate_factory_contracts(fixed, limit=24)
    assert len(generated) == 24
    assert set(generated).isdisjoint(fixed)
    fixed_topologies = {x["topology_digest"] for x in fixed.values()}
    generated_topologies = {x["topology_digest"] for x in generated.values()}
    assert len(generated_topologies) == 24
    assert fixed_topologies.isdisjoint(generated_topologies)
    assert all(x["contract_digest"] for x in generated.values())


def test_generator_v3_preserves_v2_history_then_advances_three_new_batches():
    fixed = load_factory_contract()
    legacy = generate_factory_contracts(fixed, limit=24)
    appended = generate_factory_contracts_v3({**fixed, **legacy}, limit=36)
    expanded = {**legacy, **appended}
    assert len(legacy) == 24
    assert len(appended) == 36
    assert len(expanded) == 60
    # Historical #013/#014 contracts must remain byte-semantically identical.
    assert tuple(expanded)[:24] == tuple(legacy)
    for ident, contract in legacy.items():
        assert expanded[ident] == contract

    ledger = _ledger_after_fixed_frontier()
    batches = []
    for batch_index in range(5):
        batch = research._frontier_configs_to_screen(ledger)
        assert len(batch) == research.GENERATED_FRONTIER_BATCH_SIZE == 12
        batches.append([x["mechanism"] for x in batch])
        core = {k: v for k, v in ledger.items() if k != "ledger_digest"}
        core["frontier_screening_version"] = (
            "nexus.frontier-train-screen.v4" if batch_index < 2
            else research.FRONTIER_SCREEN_VERSION
        )
        core["frontier_screened_mechanisms"] = sorted(
            set(core["frontier_screened_mechanisms"]) | set(batches[-1])
        )
        ledger = {**core, "ledger_digest": research.digest(core)}

    assert set(batches[0] + batches[1]) == set(legacy)
    assert all(
        set(batches[i]).isdisjoint(set(batches[j]))
        for i in range(len(batches)) for j in range(i)
    )
    assert len(set(batches[2] + batches[3] + batches[4])) == 36
    assert research._frontier_configs_to_screen(ledger) == []
    assert research.research_mode(ledger) == "exhausted"


def test_task_013_is_strict_successor_of_012():
    assert PREDECESSOR[THIRTEENTH] == TWELFTH
    assert THIRTEENTH in TASKS
    config = agent_manager.load_config(Path("config/nexus-agent-manager.json"))
    task = next(x for x in config["tasks"] if x["id"] == THIRTEENTH)
    assert task["dependencies"] == [TWELFTH]
    assert task["status"] == "PENDING"
    acceptance = " ".join(task["acceptance"]).lower()
    assert "at most twelve" in acceptance
    assert "training-only" in acceptance
    assert "no automatic paper/demo promotion" in acceptance
    assert "no owner-wallet mutation" in acceptance


def test_task_014_consumes_second_generated_batch_after_013():
    assert PREDECESSOR[FOURTEENTH] == THIRTEENTH
    assert FOURTEENTH in TASKS
    config = agent_manager.load_config(Path("config/nexus-agent-manager.json"))
    task = next(x for x in config["tasks"] if x["id"] == FOURTEENTH)
    assert task["dependencies"] == [THIRTEENTH]
    assert task["status"] == "PENDING"
    assert task["priority"] < next(
        x for x in config["tasks"] if x["id"] == THIRTEENTH
    )["priority"]
    acceptance = " ".join(task["acceptance"]).lower()
    assert "second training-only batch" in acceptance
    assert "next unseen generated topologies" in acceptance
    assert "zero-activity" in acceptance
    assert "no automatic paper/demo promotion" in acceptance
    assert "no owner-wallet mutation" in acceptance
