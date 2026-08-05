'use strict';

const fs = require('fs');
const path = require('path');

function validatePolicy(policy) {
  if (policy.version !== 1) throw new Error('Unsupported AI Council policy version');
  if (!Number.isInteger(policy.quorum) || policy.quorum < 1) throw new Error('quorum must be a positive integer');
  if (!Array.isArray(policy.roles) || policy.roles.length < policy.quorum) throw new Error('roles must satisfy quorum');
  const ids = policy.roles.map((role) => role.id);
  if (new Set(ids).size !== ids.length) throw new Error('role ids must be unique');
  for (const role of policy.roles) {
    if (!role.id || !Number.isInteger(role.priority) || role.priority < 1) throw new Error('invalid role');
    if (typeof role.veto !== 'boolean') throw new Error('role veto must be boolean');
  }
  return true;
}

function decide(policy, votes) {
  validatePolicy(policy);
  const byRole = new Map(policy.roles.map((role) => [role.id, role]));
  const validVotes = votes.filter((vote) => byRole.has(vote.role) && ['approve', 'reject'].includes(vote.decision));
  if (validVotes.length < policy.quorum) return { decision: 'defer', reason: 'quorum_not_met' };

  const veto = validVotes.find((vote) => vote.decision === 'reject' && byRole.get(vote.role).veto);
  if (policy.decisionPolicy.rejectOnVeto && veto) return { decision: 'reject', reason: `veto:${veto.role}` };

  const approvals = validVotes.filter((vote) => vote.decision === 'approve').length;
  const rejections = validVotes.filter((vote) => vote.decision === 'reject').length;
  if (approvals > rejections) return { decision: 'approve', reason: 'majority' };
  if (rejections > approvals) return { decision: 'reject', reason: 'majority' };

  const tieVote = [...validVotes].sort((left, right) => byRole.get(left.role).priority - byRole.get(right.role).priority)[0];
  return { decision: tieVote.decision, reason: `tie_breaker:${tieVote.role}` };
}

function main() {
  const policyPath = process.argv[2] || path.resolve(__dirname, '..', 'config', 'nexus-ai-council.json');
  const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
  validatePolicy(policy);
  process.stdout.write('NEXUS AI Council policy is valid.\n');
}

if (require.main === module) main();

module.exports = { decide, validatePolicy };
