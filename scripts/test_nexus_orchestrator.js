'use strict';

const assert = require('assert');
const { buildState, selectNextMission } = require('./nexus_orchestrator');

function queue(missions, currentMissionId = null) {
  return { version: 1, currentMissionId, missions };
}

const activeQueue = queue([
  { id: 'M-001', title: 'Foundation', status: 'completed', priority: 'automation', dependencies: [] },
  { id: 'M-002', title: 'Active', status: 'active', priority: 'maintainability', dependencies: ['M-001'] },
]);
assert.strictEqual(selectNextMission(activeQueue).id, 'M-002');

const priorityQueue = queue([
  { id: 'M-001', title: 'Foundation', status: 'completed', priority: 'automation', dependencies: [] },
  { id: 'M-003', title: 'Maintain', status: 'queued', priority: 'maintainability', dependencies: ['M-001'] },
  { id: 'M-002', title: 'Secure', status: 'queued', priority: 'security', dependencies: ['M-001'] },
]);
assert.strictEqual(selectNextMission(priorityQueue).id, 'M-002');

const blockedByDependency = queue([
  { id: 'M-001', title: 'Foundation', status: 'active', priority: 'automation', dependencies: [] },
  { id: 'M-002', title: 'Dependent', status: 'queued', priority: 'security', dependencies: ['M-001'] },
]);
assert.strictEqual(selectNextMission(blockedByDependency).id, 'M-001');

const state = buildState(priorityQueue);
assert.deepStrictEqual(state.completedMissionIds, ['M-001']);
assert.deepStrictEqual(state.queuedMissionIds, ['M-002', 'M-003']);
assert.strictEqual(state.selectedMissionId, 'M-002');

console.log('NEXUS orchestrator tests passed.');
