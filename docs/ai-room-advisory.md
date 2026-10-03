# Product AI Room advisory connection

The product AI Room can request optional DeepSeek or ChatGPT advice while its original
deterministic control plane remains authoritative. The response source selector
defaults to the internal NEXUS route. An external response is visibly labelled
with the provider and returned model; it is never dispatched as a tool or order.

## API and authority

- `GET /api/product/ai/provider` reports local configuration and budget readiness.
  It performs no network request and writes no files. `ready_unverified` does not
  prove connectivity. `connected` requires a validated provider response in this
  process within the last ten minutes and is cleared on a provider failure.
- `POST /api/product/ai/advisory` accepts exactly the existing AI Room request:
  `session_id`, `conversation_id`, `turn_id`, and `message`. Authentication,
  origin, body size and query restrictions use the existing product gateway.
- The original turn is evaluated server-side through `/api/ai-room/message`.
  A denied authority decision cannot contact the provider. Caller-supplied
  decisions, context, model choices or execution instructions are not accepted.
- The frozen AI Room, two-route tool registry, Gate 20 and Live/L4 policy are
  unchanged. Advice cannot mutate a mission, promote a strategy, or write a
  Paper journal. Local control and external advice have separate response paths.

## Provider input and privacy

The adapter maps the message locally to a fixed topic and the original classified
intent. It forwards only that classification and allowlisted component health
enums for Mission, Research, Strategy, Risk, Paper and Recovery. Unrecognised
runtime status strings become `unknown`. Project Memory remains local to the
original control plane.

Raw chat, transcripts, memory contents, account balances, PnL, position counts,
credentials, paths and arbitrary report strings are not provider input. The
existing DeepSeek egress policy validates the repository-owned prompt and filters
the model response before display. The adapter does not persist chat transcripts.

## Readiness, cost and retries

The existing owner-managed `DEEPSEEK_API_KEY` configuration and
`NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED=1` are both required. The UI never collects a
private key. Configuration presence is not proof of a valid key or a successful
API call. Tests use isolated fixtures and mocked transport, not private keys.

Requests use the existing routine model and canonical usage ledger, its USD 5
monthly ceiling, atomic reservations and ambiguous-charge quarantine. There is
one provider attempt per accepted turn, no automatic retry and no silent fallback.
Malformed output, unresolved spend and budget errors fail the advisory operation
without blocking independent local Research or internal AI Room requests.

Turn deduplication is process-local and bounded to 128 accepted turns. Completed
and ambiguous turns are retained; when full, new advisory turns are rejected
instead of evicting a paid replay. Duplicate payloads return the original result;
changed payloads conflict. A restart creates a new session scope, so clients must
not replay old paid turns across a server restart. The existing spend ledger
remains durable; transcript-based cross-restart deduplication is not claimed.

The desktop offline wrapper inherits the same authenticated product routes.
Release installation still requires the repository's exact-head CI/build checks;
this feature does not overwrite an existing installation or alter owner Paper
state. Rollback is a normal code revert; provider and ledger policy stay intact.

## ChatGPT in the local desktop

The local Electron main process uses the official **Sign in with ChatGPT** flow.
Eligible owners can explicitly consent to use their ChatGPT plan; this route
requires no API key and has no paid API fallback or separate API billing ledger.
It does not consume or override the canonical DeepSeek USD 5 budget. Plan usage
limits fail the operation and the UI offers the official usage settings page.
ChatGPT conversation history is not imported into NEXUS.

The `Continue with ChatGPT` button opens only the official authorization URL in
the system browser. The pinned official local SDK handles loopback OAuth, PKCE,
state/nonce, token verification, issued client registration and token rotation.
Credentials are encrypted through Electron `safeStorage`, including refusal of
Linux's `basic_text` backend. They live under the app's separate local `chatgpt`
directory, never Product Paper data, Research workflows, source control or logs.
The renderer receives no tokens, email, profile identity or generic network API.
Credential IPC accepts only the registered product main frame at the exact local
origin; arbitrary arguments, foreign frames and arbitrary destinations fail.

Model selection comes from the account's discovered model catalogue. Login,
sharing consent, catalogue readiness and completed inference are separate states.
`connection_verified` requires a complete, filtered response in this process within
ten minutes; merely signing in or listing models does not establish that proof.
Proof is cleared on inference failure, account change or unavailable secure storage.

The main process sends the **original** request to the authenticated local
`POST /api/product/ai/chatgpt/context` route. The unchanged frozen gate must allow
it before the server prepares the same fixed-enum topic/component context used by
DeepSeek. Raw chat and Project Memory contents remain local. Only that prepared
context reaches the Responses API; the SDK sets `store:false` and `stream:true`,
with no model tools or automatic retry. Deltas are never displayed as a completed
answer. Failed, incomplete or interrupted responses fail the turn, including
usage failures that arrive after partial text. Before display, the authenticated
local `/api/product/ai/chatgpt/sanitize` route applies the existing secret/PII
filter; it has no execution authority and accepts only a bounded `reply`.

ChatGPT turns have a separate process-local, account-bound, 128-entry deduplication
cache. A completed duplicate returns its previous advice only for the same signed-in
account. Ambiguous consumed turns cannot be retried under the same turn ID; no cache
eviction or silent provider fallback is permitted. A fresh renderer creates a new
session; cross-restart replay is not supported. Nothing persists a chat transcript.

The SDK sources are unmodified and pinned to upstream commit
`f723814abdccec135b519c451fb6e1992ee5e933` in
`desktop/nexus-product/vendor/siwc-local/UPSTREAM.json`. The bundle build verifies
all source digests, retains the upstream noncommercial license and third-party
notices, and is used for this personal Research/Paper application. Electron is
pinned to 44.5.1 for the SDK's Node >=22 runtime requirement. The dependency lock,
headless bridge tests and actual SDK stream-parser tests are part of Windows
packaging. A new build still requires isolated device verification before replacing
the healthy owner installation.

## Accepted room / Council / execution roadmap

`GET /api/product/ai/roadmap` reads `config/nexus-ai-council.json`. It projects the
actual three-role policy (stability and security with veto; delivery; quorum two)
as **configured**, with no fabricated votes or decision. Missing or incompatible
policy is **unavailable**. The policy is included in the packaged Python sidecar.
A response from ChatGPT or DeepSeek is neither a Council vote nor independent QA.
This feature does not create autonomous model Council sessions.

The accepted chain remains:

1. Owner and local Project Memory provide context to AI Room / Council.
2. A proposal passes the existing bounded policy route into a Mission.
3. Supervisor / Router and Agent Manager assign and track Worker leases.
4. Worker Evidence requires an Independent Verifier; a worker cannot self-approve.
5. Qualified strategy evidence passes Decision and deterministic Risk before Paper.
6. Performance / Drift feeds new Research and Memory through the existing gates.

For software work, the worker produces a scoped patch and tests on a branch;
independent review and exact-head CI precede a guarded merge. GitHub and canonical
evidence remain the source of truth. The room does not interpret provider prose
as queue entries, shell commands, orders, promotion approvals or completed missions.
Showing a configured component does not prove a running process or successful
research. In particular, workflow success does not prove #010 producer success.

Official sources:
- https://learn.chatgpt.com/cookbook/articles/sign-in-with-chatgpt
- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://github.com/openai/sign-in-with-chatgpt-devkit
