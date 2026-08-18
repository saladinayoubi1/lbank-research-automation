'use strict';

const assert = require('assert');
const { validateQueue, V2_PRIORITIES } = require('./validate_nexus_mission_queue');

function mission(id, status, priority, lane = 'general', dependencies = []) {
  return { id, title: id, status, priority, lane, dependencies, reversible: true };
}

const v1 = {
  version: 1,
  currentMissionId: 'M-002',
  selectionPolicy: { zeroIdle: true },
  missions: [
    mission('M-001', 'completed', 'automation'),
    mission('M-002', 'active', 'security', 'general', ['M-001']),
  ],
};
assert.strictEqual(validateQueue(v1), true);

const v2 = {
  version: 2,
  currentMissionId: 'M-010',
  selectionPolicy: {
    zeroIdle: true,
    allowParallelIndependentMissions: true,
    maxParallelMissions: 3,
    minimumProductCapacityFraction: 0.5,
    priorityOrder: [...V2_PRIORITIES],
    requireDependenciesComplete: true,
  },
  missions: [
    mission('M-004', 'completed', 'automation'),
    mission('M-010', 'active', 'product_research', 'product', ['M-004']),
    mission('M-011', 'active', 'product_research', 'product', ['M-004']),
    mission('M-012', 'active', 'phase_blocker', 'blocker', ['M-004']),
    mission('M-013', 'queued', 'backlog', 'backlog', ['M-004']),
  ],
};
assert.strictEqual(validateQueue(v2), true);

const tooMany = JSON.parse(JSON.stringify(v2));
tooMany.selectionPolicy.maxParallelMissions = 2;
assert.throws(() => validateQueue(tooMany), /exceed maxParallelMissions/);

const wrongCurrent = JSON.parse(JSON.stringify(v2));
wrongCurrent.currentMissionId = 'M-013';
assert.throws(() => validateQueue(wrongCurrent), /currentMissionId/);

const widenedPriority = JSON.parse(JSON.stringify(v2));
widenedPriority.selectionPolicy.priorityOrder.push('live_money');
assert.throws(() => validateQueue(widenedPriority), /priorityOrder/);

const badVersion = JSON.parse(JSON.stringify(v2));
badVersion.version = 99;
assert.throws(() => validateQueue(badVersion), /Unsupported mission queue version/);

console.log('NEXUS mission queue validator tests passed.');
