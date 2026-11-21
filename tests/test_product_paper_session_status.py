from pathlib import Path
import shutil
import subprocess
from unittest import SkipTest


ROOT = Path(__file__).resolve().parents[1]


def test_paper_overview_renders_session_state_without_claiming_worker_liveness():
    node = shutil.which("node")
    if not node:
        raise SkipTest("Node is unavailable")
    source = (ROOT / "product_ui" / "product.js").read_text(encoding="utf-8")
    html = (ROOT / "product_ui" / "index.html").read_text(encoding="utf-8")
    assert '<span>PAPER SESSION</span><b id="paperState">' in html
    assert "<small>Account session status</small>" in html
    start = source.index("function paperSessionLabel(paper){")
    end = source.index("\nfunction activePaperTerminalSnapshot", start)
    program = source[start:end] + r"""
const assert = require('node:assert/strict');
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {textContent: '', innerHTML: '', className: ''});
  return elements.get(id);
};
const metric = () => '';
const statusClass = () => 'neutral';
const esc = value => String(value);
const state = {overview: null};
const account = {active: true, paper_only: true, live_trading_authority: false,
  account: {session_open: true, positions: [], cash: '500'}, event_count: 2};
function check(paper, expected) {
  state.overview = {paper};
  renderOverview();
  assert.equal($('#paperState').textContent, expected);
  assert.notEqual($('#paperState').textContent, 'ACTIVE');
}
// A newly opened empty account describes its session without inventing a worker.
check(account, 'SESSION OPEN');
check({...account, account: {...account.account, session_open: false}}, 'SESSION CLOSED');
// An old financial event is neither a fresh worker heartbeat nor proof of failure.
check({...account, last_execution_utc: '2026-10-05T15:29:59.999Z'}, 'SESSION OPEN');
check({...account, active: false}, 'UNAVAILABLE');
check({...account, account: {}}, 'UNAVAILABLE');
check({...account, paper_only: false}, 'UNAVAILABLE');
check({...account, live_trading_authority: true}, 'UNAVAILABLE');
check(undefined, 'UNAVAILABLE');
console.log('PAPER_SESSION_STATUS=PASS');
"""
    result = subprocess.run(
        [node, "-e", program], cwd=ROOT, text=True, capture_output=True,
        check=False, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PAPER_SESSION_STATUS=PASS" in result.stdout
