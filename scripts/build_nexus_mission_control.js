'use strict';

const fs = require('fs');
const path = require('path');

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function buildViewModel(queue) {
  const missions = [...queue.missions].sort((a, b) => a.id.localeCompare(b.id));
  const completed = missions.filter((mission) => mission.status === 'completed').length;
  return {
    version: queue.version,
    currentMissionId: queue.currentMissionId,
    completed,
    total: missions.length,
    progress: missions.length ? Math.round((completed / missions.length) * 100) : 0,
    missions,
  };
}

function render(queue) {
  const model = buildViewModel(queue);
  const rows = model.missions.map((mission) => `
      <tr>
        <td>${escapeHtml(mission.id)}</td>
        <td>${escapeHtml(mission.title)}</td>
        <td><span class="status status-${escapeHtml(mission.status)}">${escapeHtml(mission.status)}</span></td>
        <td>${escapeHtml(mission.priority)}</td>
        <td>${escapeHtml(mission.dependencies.join(', ') || 'none')}</td>
      </tr>`).join('');

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NEXUS Mission Control</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
    body { margin: 0; background: #08111f; color: #e7eef9; }
    main { max-width: 1100px; margin: 0 auto; padding: 32px 20px; }
    .panel { background: #101c2e; border: 1px solid #24354f; border-radius: 16px; padding: 20px; margin-bottom: 18px; }
    .summary { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 12px; }
    .metric { background: #0b1626; border-radius: 12px; padding: 16px; }
    .metric strong { display: block; font-size: 1.6rem; margin-top: 6px; }
    .bar { height: 12px; background: #26364d; border-radius: 999px; overflow: hidden; }
    .bar > span { display: block; height: 100%; width: ${model.progress}%; background: #60a5fa; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 12px; border-bottom: 1px solid #24354f; }
    .status { padding: 4px 9px; border-radius: 999px; font-size: .85rem; }
    .status-completed { background: #153f31; }
    .status-active { background: #183d66; }
    .status-blocked { background: #5b2430; }
    .status-queued { background: #3b344f; }
    @media (max-width: 700px) { table { display: block; overflow-x: auto; } }
  </style>
</head>
<body>
<main>
  <h1>NEXUS Mission Control</h1>
  <section class="panel summary">
    <div class="metric">Current mission<strong>${escapeHtml(model.currentMissionId || 'none')}</strong></div>
    <div class="metric">Completed<strong>${model.completed}/${model.total}</strong></div>
    <div class="metric">Progress<strong>${model.progress}%</strong></div>
    <div class="metric">Queue version<strong>v${escapeHtml(model.version)}</strong></div>
  </section>
  <section class="panel">
    <div class="bar" aria-label="mission completion"><span></span></div>
  </section>
  <section class="panel">
    <table>
      <thead><tr><th>ID</th><th>Mission</th><th>Status</th><th>Priority</th><th>Dependencies</th></tr></thead>
      <tbody>${rows}
      </tbody>
    </table>
  </section>
</main>
</body>
</html>\n`;
}

function main() {
  const queuePath = process.argv[2] || path.resolve(__dirname, '..', 'config', 'nexus-mission-queue.json');
  const outputPath = process.argv[3] || path.resolve(__dirname, '..', 'build', 'nexus-mission-control', 'index.html');
  const queue = JSON.parse(fs.readFileSync(queuePath, 'utf8'));
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, render(queue), 'utf8');
  console.log(`Built ${outputPath}`);
}

if (require.main === module) main();
module.exports = { buildViewModel, escapeHtml, render };
