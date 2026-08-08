# NEXUS self-hosted runner privacy boundary

This runner is intentionally scoped to repository automation only.

## Privacy rules

- Use a dedicated Windows user for the runner if practical.
- Install the runner in a dedicated folder outside personal Documents/Desktop folders.
- Do not grant administrator rights unless strictly required for runner service installation.
- Do not store exchange API keys, wallet seeds, browser profiles, personal files, or unrelated secrets in the runner workspace.
- Repository workflows use `permissions: contents: read` by default and must explicitly justify any increase.
- The local workflow exposes only a fixed allow-list of tasks; arbitrary command input is prohibited.
- `actions/checkout` uses `persist-credentials: false`.
- Jobs are restricted to the `nexus-local` label.
- No live trading, signing, private credentials, billing, or unrestricted remote shell is authorized.
- Outputs and artifacts must not include environment dumps, home-directory listings, browser data, tokens, or unrelated local paths.
- Any future workflow that needs additional filesystem access must be reviewed separately and remain fail-closed by default.

## Approved task surface

The initial workflow may run only: health checks, repository tests, readiness regeneration, and exhaustive gap repair. Any broader local action requires a separate reviewed change.
