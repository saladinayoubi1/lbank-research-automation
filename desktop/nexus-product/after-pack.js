'use strict';

const fs = require('fs');
const path = require('path');

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== 'win32') return;
  const resources = path.join(context.appOutDir, 'resources');
  const required = [
    path.join(resources, 'scripts', 'bootstrap_nexus_runner_from_gui.ps1'),
    path.join(resources, 'scripts', 'install_nexus_owner_autostart_from_gui.ps1'),
    path.join(resources, 'nexus-source-seed.git', 'HEAD'),
    path.join(resources, 'nexus-source-seed.git', 'shallow'),
    path.join(resources, 'nexus-source-seed.git', 'objects'),
  ];
  for (const target of required) {
    if (!fs.existsSync(target)) throw new Error(`packaged owner bootstrap resource missing: ${target}`);
  }
  const shallow = fs.readFileSync(path.join(resources, 'nexus-source-seed.git', 'shallow'), 'utf8').trim();
  if (!/^[0-9a-f]{40}(?:\r?\n[0-9a-f]{40})*$/.test(shallow)) {
    throw new Error('packaged owner bootstrap shallow boundary is invalid');
  }
};
