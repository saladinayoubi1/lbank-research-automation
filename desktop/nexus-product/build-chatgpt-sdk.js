'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const vendor = path.join(__dirname, 'vendor', 'siwc-local');
const pin = JSON.parse(fs.readFileSync(path.join(vendor, 'UPSTREAM.json'), 'utf8'));
if (pin.commit !== 'f723814abdccec135b519c451fb6e1992ee5e933' || pin.source_unmodified !== true) throw new Error('Unverified SIWC source');
for (const [file, digest] of Object.entries(pin.files)) {
  const actual = createHash('sha256').update(fs.readFileSync(path.join(vendor, file))).digest('hex');
  if (actual !== digest) throw new Error('SIWC source digest mismatch: ' + file);
}
require('esbuild').buildSync({ entryPoints: [path.join(vendor, 'src', 'index.ts')],
  outfile: path.join(__dirname, 'chatgpt-sdk.cjs'), bundle: true, platform: 'node',
  target: 'node22', format: 'cjs', legalComments: 'external',
  banner: { js: '// Official Sign in with ChatGPT DevKit, pinned in vendor/siwc-local/UPSTREAM.json.\n// Noncommercial license and third-party notices are included in vendor/siwc-local.' } });
const legal = path.join(__dirname, 'chatgpt-sdk.cjs.LEGAL.txt');
if (!fs.existsSync(legal)) fs.writeFileSync(legal, 'See vendor/siwc-local/LICENSE and THIRD_PARTY_NOTICES.md.\n');
console.log('Pinned ChatGPT SDK bundle verified and built.');
