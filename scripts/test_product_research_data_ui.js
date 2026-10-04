'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function main() {
  const nodes = new Map();
  class Element {
    constructor() { this.listeners = {}; this.attributes = {}; this.currentCells = []; this.disabled = false; }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    set innerHTML(value) {
      this.html = value;
      for (const match of value.matchAll(/\bid="([^"]+)"/g)) {
        const node = new Element(); node.id = match[1];
      }
      this.currentCells = [...value.matchAll(/<td data-current="true">([^<]*)<\/td>/g)].map(match => ({textContent: match[1]}));
    }
    get innerHTML() { return this.html || ''; }
    appendChild(node) { nodes.set(node.id, node); }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(event, listener) { this.listeners[event] = listener; }
    querySelectorAll(selector) { assert.equal(selector, '[data-current]'); return this.currentCells; }
  }
  for (const id of ['view-data', 'view-research']) { const node = new Element(); node.id = id; }
  const snapshots = {};
  for (const provider of ['lbank', 'bitget']) {
    snapshots[provider] = {
      provider, polling_enabled: false, state: {feed_healthy: true, successful_cycles: 3, cells: []},
      datasets: [{provider, symbol: 'ETHUSDT', timeframe: '15m', row_count: 120,
        end_exclusive_ms: 1791140400000, historical_only: false, fresh: true}]
    };
  }
  const calls = [], failures = new Set();
  const window = {};
  const context = {
    document: {readyState: 'complete', hidden: false, getElementById: id => nodes.get(id), createElement: () => new Element()},
    window, AbortSignal, setInterval: () => 1,
    fetch: async (url, options) => {
      calls.push({url, options});
      if (failures.has(url)) throw new Error('gateway unavailable');
      if (url === '/api/product/research/reports') return {ok: true, json: async () => ({reports: [], errors: []})};
      const provider = url.includes('lbank-market') ? 'lbank' : 'bitget';
      if (options.method === 'POST') {
        if (url.endsWith('/polling')) snapshots[provider].polling_enabled = JSON.parse(options.body).enabled;
        return {ok: true, json: async () => ({status: 'started'})};
      }
      return {ok: true, json: async () => structuredClone(snapshots[provider])};
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../product_ui/product-research-data.js'), 'utf8'), context);
  await window.NexusResearchData.refresh();
  assert.match(nodes.get('lbankMarketTable').innerHTML, /LBank · Spot/);
  assert.match(nodes.get('alternativeMarketTable').innerHTML, /Bitget · Spot/);
  assert.equal(nodes.get('lbankMarketPanel').attributes['data-provider'], 'lbank');
  assert.equal(nodes.get('lbankStart').disabled, false);
  await nodes.get('lbankStart').listeners.click();
  const post = calls.find(c => c.options.method === 'POST');
  assert.equal(post.url, '/api/product/lbank-market/polling');
  assert.deepEqual(JSON.parse(post.options.body), {enabled: true});
  assert.equal(nodes.get('lbankStart').disabled, true);
  assert.equal(nodes.get('lbankStop').disabled, false);
  assert.equal(snapshots.bitget.polling_enabled, false);
  await nodes.get('alternativeRefresh').listeners.click();
  assert(calls.some(c => c.url === '/api/product/alternative-market/refresh' && c.options.method === 'POST'));
  snapshots.lbank.provider = 'bitget';
  await window.NexusResearchData.refresh();
  assert.equal(nodes.get('lbankMarketBadge').textContent, 'خطای خواندن وضعیت');
  assert.equal(nodes.get('lbankMarketTable').currentCells[0].textContent, 'تازگی تأیید نشده');
  assert.equal(nodes.get('alternativeMarketBadge').textContent, 'دادهٔ تازه و معتبر');
  failures.add('/api/product/alternative-market');
  await window.NexusResearchData.refresh();
  assert.equal(nodes.get('alternativeMarketBadge').textContent, 'خطای خواندن وضعیت');
  assert.equal(nodes.get('alternativeMarketTable').currentCells[0].textContent, 'تازگی تأیید نشده');
  const count = calls.length;
  const first = window.NexusResearchData.refresh();
  assert.equal(window.NexusResearchData.refresh(), first);
  await first;
  assert.equal(calls.length - count, 3);
  assert(calls.every(c => c.options.credentials === 'same-origin'));
  console.log('Research data UI: independent provider controls, identity rejection, stale/error display and bounded reads pass.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
