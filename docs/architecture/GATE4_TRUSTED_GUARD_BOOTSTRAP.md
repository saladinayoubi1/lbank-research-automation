# Gate 4 trusted guard bootstrap

This branch introduces a trusted `pull_request_target` control-plane guard that executes from the PR base/default branch with read-only permissions and rejects candidate changes to the frozen Phase 3 control-plane tuple. After bootstrap merge, the repository ruleset must require the `control-plane trusted guard` status check before adversarial bypass retesting.
