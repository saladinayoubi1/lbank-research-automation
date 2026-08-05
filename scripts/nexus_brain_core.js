'use strict';

const fs = require('fs');
const path = require('path');
const { selectNextMission } = require('./nexus_orchestrator');
const { decide, validatePolicy: validateCouncilPolicy } = require('./nexus_ai_council');

const VALID_RISK = new Set(['low', 'high']);

function validateBrainPolicy(policy) {
  if (policy.version !== 1) throw new Error('Unsupported brain policy version');
  if (policy.defaultDecision !== 'defer') throw new Error('Brain policy must fail closed');
  if (!Array.isArray(policy.allowedActions) || policy.allowedActions.length === 0) throw new Error('allowedActions required');
  if (!Array.isArray(policy.humanApprovalRequired)) throw new Error('humanApprovalRequired required');
  if (policy.sideEffects?.default !== 'deny') throw new Error('side effects must default deny');
  if (!Array.isArray(policy.sideEffects.allowedRepositories) || policy.sideEffects.allowedRepositories.length === 0) {
    throw new Error('allowedRepositories required');
  }
  if (!Number.isInteger(policy.limits?.maxPlanSteps) || policy.limits.maxPlanSteps < 1) throw new Error('invalid maxPlanSteps');
  if (!Number.isInteger(policy.limits?.maxFilesPerChange) || policy.limits.maxFilesPerChange < 1) throw new Error('invalid maxFilesPerChange');
  return true;
}

function normalizeRequest(request) {
  const normalized = {
    repository: request.repository,
    action: request.action,
    risk: request.risk,
    planSteps: request.planSteps || [],
    filesChanged: request.filesChanged || 0,
    approvalType: request.approvalType || null,
    humanApproved: request.humanApproved === true,
  };
  if (!normalized.repository || !normalized.action || !VALID_RISK.has(normalized.risk)) throw new Error('invalid request');
  if (!Array.isArray(normalized.planSteps) || !Number.isInteger(normalized.filesChanged) || normalized.filesChanged < 0) {
    throw new Error('invalid request limits');
  }
  return normalized;
}

function evaluate(policy, councilPolicy, queue, votes, request) {
  validateBrainPolicy(policy);
  validateCouncilPolicy(councilPolicy);
  const input = normalizeRequest(request);
  const mission = selectNextMission(queue);
  if (!mission) return { decision: 'defer', reason: 'no_eligible_mission', missionId: null };
  if (!policy.allowedActions.includes(input.action)) return { decision: 'reject', reason: 'action_not_allowed', missionId: mission.id };
  if (!policy.sideEffects.allowedRepositories.includes(input.repository)) {
    return { decision: 'reject', reason: 'repository_not_allowed', missionId: mission.id };
  }
  if (input.planSteps.length > policy.limits.maxPlanSteps) return { decision: 'reject', reason: 'plan_limit_exceeded', missionId: mission.id };
  if (input.filesChanged > policy.limits.maxFilesPerChange) return { decision: 'reject', reason: 'file_limit_exceeded', missionId: mission.id };

  const council = decide(councilPolicy, votes);
  if (council.decision !== 'approve') return { decision: council.decision, reason: `council:${council.reason}`, missionId: mission.id };

  const approvalRequired = input.risk === 'high' || Boolean(input.approvalType);
  if (input.approvalType && !policy.humanApprovalRequired.includes(input.approvalType)) {
    return { decision: 'reject', reason: 'unknown_approval_type', missionId: mission.id };
  }
  if (approvalRequired && !input.humanApproved) {
    return { decision: 'defer', reason: 'human_approval_required', missionId: mission.id };
  }

  return {
    decision: 'approve',
    reason: 'policy_and_council_approved',
    missionId: mission.id,
    execution: 'proposal_only',
  };
}

function main() {
  const root = path.resolve(__dirname, '..');
  const policy = JSON.parse(fs.readFileSync(path.join(root, 'config', 'nexus-brain-policy.json'), 'utf8'));
  const councilPolicy = JSON.parse(fs.readFileSync(path.join(root, 'config', 'nexus-ai-council.json'), 'utf8'));
  const queue = JSON.parse(fs.readFileSync(path.join(root, 'config', 'nexus-mission-queue.json'), 'utf8'));
  validateBrainPolicy(policy);
  validateCouncilPolicy(councilPolicy);
  if (!selectNextMission(queue)) throw new Error('No eligible NEXUS mission');
  process.stdout.write('NEXUS Brain Core policy is valid.\n');
}

if (require.main === module) main();

module.exports = { evaluate, normalizeRequest, validateBrainPolicy };
