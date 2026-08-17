# ADR-019 — Secure Dashboard Gateway and Native Delivery Boundary

Status: Accepted for Phase 4 Gate 14
Parent: #510

## Decision
All dashboard/site reads cross one repository-owned secure gateway. Desktop and Android wrappers are clients of that gateway; they are not independent provider/network execution paths.

The delivery path is:

`generated read-only state -> NEXUS gateway -> versioned bounded API/static UI -> browser/native wrapper`

Direct renderer/WebView access to arbitrary provider URLs is forbidden. Native wrappers accept only an allowlisted NEXUS gateway route and GET semantics.

## Local mode
Local mode is the default and is safe without remote access:

- bind host must be loopback (`127.0.0.1`, `::1`, or localhost semantics);
- non-loopback clients fail closed;
- Host values use an exact allowlist, including the configured port;
- suffix/prefix tricks and DNS-rebinding hostnames are rejected;
- Origin is either absent or an exact local allowlisted origin;
- no bearer token is configured or required;
- the API remains GET/HEAD only and paper/research read-only.

Local plain HTTP is permitted only because the process is loopback-only and host/origin mediated. Android does not use this exception and is HTTPS-only.

## Remote mode
Remote mode is opt-in. Startup fails closed unless all of the following are provided:

- a runtime bearer token of bounded minimum strength;
- TLS certificate and private-key paths supplied at runtime;
- exact remote Host allowlist;
- exact HTTPS Origin allowlist;
- no wildcard hosts or origins.

The bearer token is compared without normal string equality and is never returned in gateway responses or access logs. Remote TLS is TLS 1.2 minimum. Gateway secrets are runtime configuration, not frontend/static assets.

## Query and payload bounds
Only `/api/readiness/series` accepts query parameters. Its schema is exactly `symbol`, `timeframe`, `limit`, and `offset`; unknown, repeated, empty filter, oversized or out-of-range values fail closed. Pagination is explicit and bounded to 200 records per response and a bounded offset.

Request targets, generated reports, static assets, native requests and responses all have size ceilings. Oversized content is rejected rather than truncated into an apparently valid state.

## Rate limiting and methods
The gateway applies a bounded in-memory request rate limit per local client or remote authenticated principal. Exceeding the limit returns `429` with `Retry-After`.

Only GET and HEAD are accepted. POST, PUT, PATCH, DELETE and OPTIONS are denied with `405`. Gate 14 does not introduce a mutation API.

## Security headers and CORS
Every HTTP response receives `no-store`, `nosniff`, frame denial, no-referrer, restrictive Permissions Policy, same-origin resource policy and a CSP that allows only same-origin scripts/styles/connectivity and denies frames, base URI, forms and all unspecified sources.

CORS is not wildcarded. An `Access-Control-Allow-Origin` header is emitted only for an already-authorized exact Origin.

## Static site boundary
Only the exact UI asset paths `/`, `/ui/index.html`, `/ui/app.js`, `/ui/styles.css`, and `/ui/phase4.css` may be served. Resolution is constrained to the configured UI root, symlinks are rejected and asset size is bounded. The frontend receives gateway mode disclosure but no token, credentials or private authorization material.

## Desktop wrapper
Electron remains `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`. Its native bridge:

- accepts one exact `path` field;
- rejects absolute URLs and origin escapes;
- allows only the read-only gateway routes;
- allows query parameters only for the series endpoint;
- performs GET only, rejects redirects and bounds response size/time;
- obtains its gateway origin from runtime environment, allowing HTTP only for loopback and requiring HTTPS otherwise;
- stores only a fixed `gateway` bearer token using Electron secure storage;
- contains no OpenAI-compatible, Anthropic, Gemini, Ollama or other direct provider request path.

## Android wrapper
Android compiles an explicit `NEXUS_GATEWAY_URL` origin, defaulting to an HTTPS loopback placeholder for development. The WebView cannot choose or override that origin. The native bridge accepts only the fixed gateway token identity and exact allowlisted gateway paths. Requests use `HttpsURLConnection`, GET only, no redirects and bounded response sizes/timeouts.

Android manifest and Network Security Configuration deny cleartext traffic. The gateway bearer token is encrypted with AndroidKeyStore AES/GCM and is never compiled into the application.

## Access-mode disclosure
Every versioned JSON response includes `nexus.gateway.v1` disclosure fields for local/remote mode, whether remote access is enabled, whether authentication is required and the read-only boundary. Secret values are never included.

## Safety boundary
Gate 14 introduces no exchange credential loading in the gateway, no live order, withdrawal, production promotion/deployment, billing mutation, signing, merge authority or irreversible financial action. Native direct-provider networking is removed so dashboard/native delivery cannot bypass the repository control plane.
