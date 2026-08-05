'use strict';

const assert = require('assert');
const { buildViewModel, escapeHtml, render } = require('./build_nexus_mission_control');

const queue = {
  version: 1,
  currentMissionId: 'M-002',
  missions: [
    { id: 'M-002', title: '<Active>', status: 'active', priority: 'security', dependencies: ['M-001'] },
    { id: 'M-001', title: 'Foundation', status: 'completed', priority: 'automation', dependencies: [] },
  ],
};

const model = buildViewModel(queue);
assert.strictEqual(model.completed, 1);
assert.strictEqual(model.total, 2);
assert.strictEqual(model.progress, 50);
assert.deepStrictEqual(model.missions.map((mission) => mission.id), ['M-001', 'M-002']);
assert.strictEqual(escapeHtml('<script>'), '&lt;script&gt;');

const html = render(queue);
assert.ok(html.includes('NEXUS Mission Control'));
assert.ok(html.includes('50%'));
assert.ok(html.includes('&lt;Active&gt;'));
assert.ok(!html.includes('<Active>'));
assert.ok(html.includes('status-active'));
assert.ok(html.includes('M-001'));

console.log('NEXUS Mission Control tests passed.');
