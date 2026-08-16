# NEXUS Global Agent Manager Policy

Status: permanent project-wide operating policy.
Scope: all current and future NEXUS phases, not Phase 4 only.

## Purpose
NEXUS must continue useful bounded work without waiting for the owner or chat assistant to manually dispatch every task.

## Permanent manager layer
A persistent Agent Manager / Supervisor is part of the core project architecture in every phase.
It owns task decomposition, assignment, routing, dependency tracking, progress monitoring, bounded retry/reassignment, conflict handling, verification handoff, evidence capture, and release of the next eligible task.

Default execution path:
Mission Queue -> Agent Manager -> Capability/Load Router -> Agent/DeepSeek/Cloud/Laptop -> Result Validator -> Conflict Resolver -> Retry/Reassign -> Evidence -> Next Eligible Task

## Required workers/resources
The manager should use all available bounded resources by default where appropriate:
- specialist agents;
- DeepSeek/auxiliary AI providers within their authority and budget;
- GitHub Actions/cloud runners;
- Windows self-hosted laptop runner when runtime semantics or local capabilities matter;
- cloud fallback when local resources are unavailable.

Idle capable workers while eligible independent work exists are considered an orchestration defect unless blocked by policy, dependency, budget, or resource limits.

## Five-minute operating rule
At least every five minutes, the coordinator must inspect active work for FAILED, BLOCKED, WAITING, STALLED, or unexpectedly idle states.
For each actionable problem it must promptly:
1. classify the failure;
2. capture the exact task/run/revision identity;
3. determine whether retry, reassignment, fallback, repair, or escalation is allowed;
4. apply bounded remediation on the existing work path where possible;
5. re-verify on the exact resulting revision/state;
6. record evidence and release newly eligible downstream work.

Do not create new PRs for evidence-only reruns or bookkeeping. A new PR/change is justified only by a demonstrated code/schema/policy defect.

## Agent autonomy
Agents do not wait for a new owner/chat instruction when a task is already authorized, dependencies are satisfied, and required inputs are available.
The manager may split tasks, assign/reassign them, resolve routine conflicts through validators, request bounded second opinions, and continue to the next eligible task.

## Conflict resolution
When agents disagree, the manager must not choose arbitrarily. It must route the disagreement to deterministic validators, tests, evidence comparison, or an independent bounded verifier. Unresolved ambiguity fails closed.

## Authority boundary
The manager and agents cannot self-promote authority.
Owner-required/high-impact actions remain blocked when they involve credentials, billing changes, production/signing authority, withdrawals, live financial execution, irreversible external actions, or explicit policy changes requiring owner approval.

## Persistence across phases
Every phase contract must inherit this policy by default. A phase may tighten these controls but may not silently remove or weaken the manager layer, five-minute rule, fail-closed behavior, audit trail, or authority boundaries.

## Recovery
On restart or chat migration, the manager resumes from durable queue/state/evidence rather than relying on conversation history. Stale, conflicting, or corrupt state must be quarantined and previous-valid state preserved.

## Success condition
The manager is functioning only when authorized work can continue autonomously across eligible agents/resources, failures are triaged within the five-minute cadence, dependencies are respected, and no safety/authority boundary is bypassed.
