'use strict';

const fs = require('fs');
const path = require('path');

const PRIORITY_ORDER = [
  'stability',
  'security',
  'automation',
  'development_speed',
  'maintainability',
  'user_experience',
  'monetization',
];

function dependenciesComplete(mission, byId) {
  return mission.dependencies.every((id) => byId.get(id)?.status === 'completed');
}

function rankMission(mission) {
  const priority = PRIORITY_ORDER.indexOf(mission.priority);
  return [priority === -1 ? PRIORITY_ORDER.length : priority, mission.id];
}

function compareMissions(left, right) {
  const [leftPriority, leftId] = rankMission(left);
  const [rightPriority, rightId] = rankMission(right);
  return leftPriority - rightPriority || leftId.localeCompare(rightId);
}

function selectNextMission(queue) {
  const byId = new Map(queue.missions.map((mission) => [mission.id, mission]));
  const active = queue.missions.filter((mission) => mission.status === 'active');
  if (active.length === 1 && dependenciesComplete(active[0], byId)) return active[0];

  return queue.missions
    .filter((mission) => mission.status === 'queued')
    .filter((mission) => dependenciesComplete(mission, byId))
    .sort(compareMissions)[0] || null;
}

function buildState(queue) {
  const selected = selectNextMission(queue);
  return {
    version: 1,
    selectedMissionId: selected?.id || null,
    selectedMissionTitle: selected?.title || null,
    completedMissionIds: queue.missions
      .filter((mission) => mission.status === 'completed')
      .map((mission) => mission.id)
      .sort(),
    blockedMissionIds: queue.missions
      .filter((mission) => mission.status === 'blocked')
      .map((mission) => mission.id)
      .sort(),
    queuedMissionIds: queue.missions
      .filter((mission) => mission.status === 'queued')
      .map((mission) => mission.id)
      .sort(),
  };
}

function main() {
  const queuePath = process.argv[2] || path.resolve(__dirname, '..', 'config', 'nexus-mission-queue.json');
  const queue = JSON.parse(fs.readFileSync(queuePath, 'utf8'));
  process.stdout.write(`${JSON.stringify(buildState(queue), null, 2)}\n`);
}

if (require.main === module) main();

module.exports = { PRIORITY_ORDER, buildState, selectNextMission };
