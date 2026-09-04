# Requalification incident 33824676837

Main run `33824676837` proved historical archive Discovery on `NEXUS-BYBIT-WSL`, but `requalify-physical` did not reach market-data evaluation. The job timed out in `Prepare fresh exact-source requalification process` while executing a workspace-wide `git clean -ffdx` after `git reset --hard`. The job was cancelled at its 55-minute limit. Its `always()` cleanup then failed because `STATE_ROOT` had not yet been exported.

Corrective direction: use a fresh bounded exact-SHA checkout outside the shared runner workspace for requalification, initialize cleanup paths before network operations, and acquire the fresh canonical Bybit REST requalification snapshot on hosted GitHub only after historical Discovery completes. The physical job then consumes a digest-pinned fresh snapshot rather than depending on regional REST access.
