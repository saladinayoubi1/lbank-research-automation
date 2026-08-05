'use strict';
const fs = require('fs');
const path = require('path');
const queue = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'config', 'nexus-mission-queue.json'), 'utf8'));
function assertValue(condition, message) { if (!condition) throw new Error(message); }
const statuses = ['queued', 'active', 'blocked', 'completed'];
const priorities = ['stability', 'security', 'automation', 'development_speed', 'maintainability', 'user_experience', 'monetization'];
assertValue(queue.version === 1, 'Unsupported mission queue version');
assertValue(Array.isArray(queue.missions) && queue.missions.length > 0, 'missions must be non-empty');
assertValue(queue.selectionPolicy && queue.selectionPolicy.zeroIdle === true, 'zeroIdle must be enabled');
const ids = queue.missions.map((mission) => mission.id);
assertValue(new Set(ids).size === ids.length, 'Mission ids must be unique');
for (const mission of queue.missions) {
  assertValue(/^M-[0-9]{3}$/.test(mission.id), 'Invalid mission id');
  assertValue(statuses.includes(mission.status), 'Invalid mission status');
  assertValue(priorities.includes(mission.priority), 'Invalid mission priority');
  assertValue(Array.isArray(mission.dependencies), 'dependencies must be an array');
  assertValue(mission.reversible === true, 'Missions must be reversible');
  for (const dependency of mission.dependencies) assertValue(ids.includes(dependency), 'Unknown dependency');
}
const active = queue.missions.filter((mission) => mission.status === 'active');
assertValue(active.length <= 1, 'Only one primary mission may be active');
if (queue.currentMissionId) assertValue(active.length === 1 && active[0].id === queue.currentMissionId, 'currentMissionId mismatch');
console.log('NEXUS mission queue is valid.');
