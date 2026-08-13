'use strict';

const fs = require('fs');
const path = require('path');

// Product work must win over infrastructure hardening unless a frozen phase gate
// is materially blocking the product. Keep this list backward compatible with
// older queue entries while making Phase/Product work explicit.
const PRIORITY_ORDER = [
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

const LANE_ORDER = {
  product: 0,
  blocker: 1,
  general: 2,
  backlog: 9,
};

function dependenciesComplete(mission, byId) {
  return mission.dependencies.every((id) => byId.get(id)?.status === 'completed');
}

function rankMission(mission) {
  const lane = LANE_ORDER[mission.lane || 'general'] ?? LANE_ORDER.general;
  const priority = PRIORITY_ORDER.indexOf(mission.priority);
  return [lane, priority === -1 ? PRIORITY_ORDER.length : priority, mission.id];
}

function compareMissions(left, right) {
  const leftRank = rankMission(left);
  const rightRank = rankMission(right);
  for (let i = 0; i < leftRank.length; i += 1) {
    if (leftRank[i] < rightRank[i]) return -1;
    if (leftRank[i] > rightRank[i]) return 1;
  }
  return 0;
}

function readyMissions(queue) {
  const byId = new Map(queue.missions.map((mission) => [mission.id, mission]));
  return queue.missions
    .filter((mission) => mission.status === 'active' || mission.status === 'queued')
    .filter((mission) => dependenciesComplete(mission, byId))
    .sort(compareMissions);
}

function selectNextMission(queue) {
  return readyMissions(queue)[0] || null;
}

function selectParallelMissions(queue) {
  const maxParallel = Math.max(1, Number(queue.selectionPolicy?.maxParallelMissions || 3));
  const ready = readyMissions(queue);
  const selected = [];
  const selectedIds = new Set();

  // Product-first capacity rule: when product work is ready, reserve at least
  // half of available slots for it before filling remaining slots.
  const productReady = ready.filter((mission) => (mission.lane || 'general') === 'product');
  const productSlots = productReady.length > 0 ? Math.ceil(maxParallel / 2) : 0;
  for (const mission of productReady.slice(0, productSlots)) {
    selected.push(mission);
    selectedIds.add(mission.id);
  }

  for (const mission of ready) {
    if (selected.length >= maxParallel) break;
    if (selectedIds.has(mission.id)) continue;
    selected.push(mission);
    selectedIds.add(mission.id);
  }
  return selected;
}

function buildState(queue) {
  const selected = selectNextMission(queue);
  const parallel = selectParallelMissions(queue);
  return {
    version: 2,
    selectedMissionId: selected?.id || null,
    selectedMissionTitle: selected?.title || null,
    readyMissionIds: parallel.map((mission) => mission.id),
    readyMissionTitles: parallel.map((mission) => mission.title),
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

module.exports = {
  PRIORITY_ORDER,
  buildState,
  readyMissions,
  selectNextMission,
  selectParallelMissions,
};
