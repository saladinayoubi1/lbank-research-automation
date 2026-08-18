'use strict';
const fs = require('fs');
const path = require('path');

function assertValue(condition, message) { if (!condition) throw new Error(message); }

const STATUSES = ['queued', 'active', 'blocked', 'completed'];
const V1_PRIORITIES = ['stability', 'security', 'automation', 'development_speed', 'maintainability', 'user_experience', 'monetization'];
const V2_PRIORITIES = [
  'product_research',
  'phase_blocker',
  'stability',
  'automation',
  'development_speed',
  'security',
  'maintainability',
  'user_experience',
  'monetization',
  'backlog',
];
const V2_LANES = ['product', 'blocker', 'general', 'backlog'];

function validateCommon(queue, priorities) {
  assertValue(Array.isArray(queue.missions) && queue.missions.length > 0, 'missions must be non-empty');
  assertValue(queue.selectionPolicy && queue.selectionPolicy.zeroIdle === true, 'zeroIdle must be enabled');
  const ids = queue.missions.map((mission) => mission.id);
  assertValue(new Set(ids).size === ids.length, 'Mission ids must be unique');
  for (const mission of queue.missions) {
    assertValue(/^M-[0-9]{3}$/.test(mission.id), 'Invalid mission id');
    assertValue(typeof mission.title === 'string' && mission.title.length > 0, 'Invalid mission title');
    assertValue(STATUSES.includes(mission.status), 'Invalid mission status');
    assertValue(priorities.includes(mission.priority), 'Invalid mission priority');
    assertValue(Array.isArray(mission.dependencies), 'dependencies must be an array');
    assertValue(new Set(mission.dependencies).size === mission.dependencies.length, 'Duplicate dependency');
    assertValue(!mission.dependencies.includes(mission.id), 'Self dependency');
    assertValue(mission.reversible === true, 'Missions must be reversible');
    for (const dependency of mission.dependencies) assertValue(ids.includes(dependency), 'Unknown dependency');
  }
  return ids;
}

function validateV1(queue) {
  validateCommon(queue, V1_PRIORITIES);
  const active = queue.missions.filter((mission) => mission.status === 'active');
  assertValue(active.length <= 1, 'Only one primary mission may be active');
  if (queue.currentMissionId) {
    assertValue(active.length === 1 && active[0].id === queue.currentMissionId, 'currentMissionId mismatch');
  }
}

function validateV2(queue) {
  validateCommon(queue, V2_PRIORITIES);
  const policy = queue.selectionPolicy;
  assertValue(policy.allowParallelIndependentMissions === true, 'parallel independent missions must be enabled');
  assertValue(Number.isInteger(policy.maxParallelMissions) && policy.maxParallelMissions >= 1 && policy.maxParallelMissions <= 6, 'maxParallelMissions must be bounded');
  assertValue(typeof policy.minimumProductCapacityFraction === 'number' && policy.minimumProductCapacityFraction >= 0 && policy.minimumProductCapacityFraction <= 1, 'minimumProductCapacityFraction must be bounded');
  assertValue(Array.isArray(policy.priorityOrder), 'priorityOrder must be an array');
  assertValue(JSON.stringify(policy.priorityOrder) === JSON.stringify(V2_PRIORITIES), 'priorityOrder must match the v2 scheduling contract');
  assertValue(policy.requireDependenciesComplete === true, 'requireDependenciesComplete must be enabled');

  for (const mission of queue.missions) {
    assertValue(V2_LANES.includes(mission.lane), 'Invalid mission lane');
  }
  const active = queue.missions.filter((mission) => mission.status === 'active');
  assertValue(active.length <= policy.maxParallelMissions, 'Active missions exceed maxParallelMissions');
  if (queue.currentMissionId) {
    const current = queue.missions.find((mission) => mission.id === queue.currentMissionId);
    assertValue(current && current.status === 'active', 'currentMissionId must reference an active mission');
  }
}

function validateQueue(queue) {
  assertValue(queue && typeof queue === 'object' && !Array.isArray(queue), 'mission queue root must be an object');
  if (queue.version === 1) validateV1(queue);
  else if (queue.version === 2) validateV2(queue);
  else throw new Error('Unsupported mission queue version');
  return true;
}

function main() {
  const queue = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'config', 'nexus-mission-queue.json'), 'utf8'));
  validateQueue(queue);
  console.log('NEXUS mission queue is valid.');
}

if (require.main === module) main();

module.exports = { validateQueue, V1_PRIORITIES, V2_PRIORITIES, V2_LANES };
