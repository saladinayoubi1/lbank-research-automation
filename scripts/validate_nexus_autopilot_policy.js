'use strict';

const fs = require('fs');
const path = require('path');

const policyPath = path.resolve(__dirname, '..', 'config', 'nexus-autopilot-policy.json');
const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'));

const requiredAllowed = [
  'create_branch',
  'edit_code',
  'add_tests',
  'commit_changes',
  'open_pull_request',
  'run_ci',
  'merge_after_required_checks'
];

const requiredApproval = [
  'change_billing',
  'create_or_rotate_secrets',
  'use_signing_certificate',
  'deploy_to_production',
  'delete_user_data'
];

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

assert(policy.version === 1, 'Unsupported autopilot policy version');
assert(policy.mode === 'autopilot', 'Autopilot mode must be enabled');
assert(policy.defaults?.preferReversibleChanges === true, 'Reversible changes must be preferred');
assert(policy.defaults?.requirePassingChecksBeforeMerge === true, 'Passing checks must be required before merge');
assert(Number.isInteger(policy.defaults?.maxAutomaticRetriesPerJob), 'Retry limit must be an integer');
assert(policy.defaults.maxAutomaticRetriesPerJob >= 0 && policy.defaults.maxAutomaticRetriesPerJob <= 5,
  'Retry limit must be between 0 and 5');
assert(Array.isArray(policy.allowed), 'allowed must be an array');
assert(Array.isArray(policy.approvalRequired), 'approvalRequired must be an array');

for (const action of requiredAllowed) {
  assert(policy.allowed.includes(action), `Missing allowed action: ${action}`);
}
for (const action of requiredApproval) {
  assert(policy.approvalRequired.includes(action), `Missing approval-required action: ${action}`);
}
for (const action of policy.allowed) {
  assert(!policy.approvalRequired.includes(action), `Action cannot be both allowed and approval-required: ${action}`);
}

console.log('NEXUS autopilot policy is valid.');
