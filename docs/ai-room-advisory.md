# Product AI Room advisory connection

The product AI Room can request optional DeepSeek advice while its original
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
