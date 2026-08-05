'use strict';

const assert = require('assert');
const policy = require('../config/nexus-ai-council.json');
const { decide, validatePolicy } = require('./nexus_ai_council');

assert.strictEqual(validatePolicy(policy), true);
assert.deepStrictEqual(decide(policy, [
  { role: 'stability', decision: 'approve' },
]), { decision: 'defer', reason: 'quorum_not_met' });
assert.deepStrictEqual(decide(policy, [
  { role: 'stability', decision: 'reject' },
  { role: 'delivery', decision: 'approve' },
]), { decision: 'reject', reason: 'veto:stability' });
assert.deepStrictEqual(decide(policy, [
  { role: 'stability', decision: 'approve' },
  { role: 'security', decision: 'approve' },
  { role: 'delivery', decision: 'reject' },
]), { decision: 'approve', reason: 'majority' });
assert.deepStrictEqual(decide(policy, [
  { role: 'stability', decision: 'approve' },
  { role: 'delivery', decision: 'reject' },
]), { decision: 'approve', reason: 'tie_breaker:stability' });

console.log('NEXUS AI Council tests passed.');
