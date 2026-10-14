# Laptop1 native process identity preparation — 2026-10-14

Change: Prepare a one-shot read-only native process inspector using a hash-pinned psutil wheel in an isolated QA folder, to unblock exact RDC identity/ancestry discovery after unavailable CIM and absent psutil.
System Map node(s): OBS-80, REL-90, SYS-00.
Existing component being changed: Diagnostic access to the existing Laptop1 RDC/recovery lane. No runtime CJS, Startup, task or client is modified.
Why existing component cannot already satisfy the need: CIM process query returned Not found; the original standalone reader reported psutil absent. Current remote identities/ancestry must be observed before any safe task cutover.
Primary runner / execution lane: Laptop1 read-only maintenance, same Windows owner/session. Laptop2 Research primary and Laptop1 Paper owner remain.
Data source and provenance: Merged main db52c90e3e68ff33e905fbd3b6a35101aa5e87ad; current patched CJS digest d762b259a74aa0b31188dcc02e259bbf9f2c7cd61952bc858297554c2412e35d. Official PyPI psutil 7.2.2 Windows amd64 abi3 wheel digest eb7e81434c8d223ec4a219b5fc1c47d0417b12be7ea866e24fb5ad6e84b3d988 (https://pypi.org/project/psutil/7.2.2/). psutil upstream docs: https://psutil.readthedocs.io/stable/.
Upstream dependencies: Existing Python 3.12 amd64, official PyPI HTTPS/wheel hash, isolated target directory, published immutable probe bytes. No new global Python package.
Downstream consumers: Later existing-task migration preflight only. These observations are not termination or writer authority.
Authority level: Read-only process metadata and isolated QA-package/files only. No process stop/start of the real SDK, task registration/action mutation, failover or trading authority.
Paper/Live boundary: Bybit Demo/Paper 500 USDT, Live=false; profile/journal/checkpoint/research and installed application preserved.
Duplicate-work check: No persistent task/service/watchdog/runner/client. Observe Node and Runner PID/parent/exe/creation/owner/session/job membership. Adobe Node is unrelated and excluded from SDK classification. No HTTP-test assertion weakening.
Failure mode: Wrong host/Python width/source or wheel hash fails closed. Missing/access-denied process recorded explicitly. Never infer positive process exit or independently surviving controller from these fingerprints. Raw command lines and credential file values are not exported.
Rollback: Isolated QA dependency folder can be removed separately; native runtime/task/Startup/guard are untouched.
Tests: Native version/module-path/hash/creation/session/job metadata and actual reader exit; no destructive test or auth SDK invocation. Source uses typed Win32 read-only APIs with upstream package metadata.
Independent QA required: Native read-only evidence and hosted exact-head checks before promoting source or using it in a future mutating controller. Existing PR2644 Windows HTTP failure is separately retried once at unchanged source; no claim that it is fixed until actual result.
Deployment/cutover impact: Diagnostic preparation only. Real current RDC and legacy migration guard stay.
Evidence required to declare DONE: Frozen source/wheel digests, successful isolated installation and native process metadata, preserved runtime/task/Startup/guard and fresh RDC ping. Full task recovery requires separate independent execution and positive exact old-client exit.

Win32 job API reference: https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob
