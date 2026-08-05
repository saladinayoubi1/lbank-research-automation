'use strict';

const assert = require('assert');
const brainPolicy = require('../config/nexus-brain-policy.json');
const councilPolicy = require('../config/nexus-ai-council.json');
const queue = require('../config/nexus-mission-queue.json');
const { evaluate, validateBrainPolicy } = require('./nexus_brain_core');

const approveVotes = [
  { role: 'stability', decision: 'approve' },
  { role: 'security', decision: 'approve' },
];

function request(overrides = {}) {
  return {
    repository: 'saladinayoubi1/lbank-research-automation',
    action: 'propose_change',
    risk: 'low',
    planSteps: ['inspect', 'test'],
    filesChanged: 2,
    ...overrides,
  };
}

assert.strictEqual(validateBrainPolicy(brainPolicy), true);
assert.deepStrictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request()), {
  decision: 'approve',
  reason: 'policy_and_council_approved',
  missionId: queue.currentMissionId,
  execution: 'proposal_only',
});
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request({ action: 'deploy_production' })).reason, 'action_not_allowed');
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request({ repository: 'other/repo' })).reason, 'repository_not_allowed');
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request({ risk: 'high' })).reason, 'human_approval_required');
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request({ approvalType: 'billing' })).reason, 'human_approval_required');
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request({ approvalType: 'unbounded_override', humanApproved: true })).reason, 'unknown_approval_type');
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, [{ role: 'security', decision: 'reject' }, { role: 'delivery', decision: 'approve' }], request()).reason, 'council:veto:security');
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request({ filesChanged: 21 })).reason, 'file_limit_exceeded');
assert.strictEqual(evaluate(brainPolicy, councilPolicy, queue, approveVotes, request({ planSteps: Array(13).fill('step') })).reason, 'plan_limit_exceeded');

const permissive = JSON.parse(JSON.stringify(brainPolicy));
permissive.sideEffects.default = 'allow';
assert.throws(() => validateBrainPolicy(permissive), /default deny/);

console.log('NEXUS Brain Core tests passed.');
