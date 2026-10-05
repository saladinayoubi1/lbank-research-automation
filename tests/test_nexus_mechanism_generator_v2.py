from pathlib import Path

import agent_manager
import nexus_composite_strategy_research as research
from nexus_mechanism_factory import generate_factory_contracts, load_factory_contract
from nexus_research_missions import THIRTEENTH, TWELFTH, PREDECESSOR, TASKS


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


def test_generated_frontier_advances_in_two_batches_then_exhausts():
    first_ledger = _ledger_after_fixed_frontier()
    first = research._frontier_configs_to_screen(first_ledger)
    assert len(first) == research.GENERATED_FRONTIER_BATCH_SIZE == 12
    assert {x["mechanism"] for x in first} <= set(research.GENERATED_FACTORY_MECHANISMS)

    core = {k: v for k, v in first_ledger.items() if k != "ledger_digest"}
    core["frontier_screening_version"] = research.FRONTIER_SCREEN_VERSION
    core["frontier_screened_mechanisms"] = sorted(
        set(core["frontier_screened_mechanisms"]) | {x["mechanism"] for x in first}
    )
    second_ledger = {**core, "ledger_digest": research.digest(core)}
    second = research._frontier_configs_to_screen(second_ledger)
    assert len(second) == 12
    assert {x["mechanism"] for x in first}.isdisjoint({x["mechanism"] for x in second})

    core = {k: v for k, v in second_ledger.items() if k != "ledger_digest"}
    core["frontier_screened_mechanisms"] = sorted(
        set(core["frontier_screened_mechanisms"]) | {x["mechanism"] for x in second}
    )
    final = {**core, "ledger_digest": research.digest(core)}
    assert research._frontier_configs_to_screen(final) == []
    assert research.research_mode(final) == "exhausted"


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
