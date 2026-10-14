# Laptop1 native RDC process discovery preparation

The deployed CJS exit-expression repair and its native proof are now merged: PR2643 source 45d881f, PR2644 evidence head 320bd271 and main ca3458fcbcb9bf2e4f7c449dba3f4b0b423883c5. The single Windows HTTP response failure in PR2644 was retried once on unchanged source; all 11 checks then passed. This is not a claim that the unrelated HTTP transport issue was fixed.

Current task migration is still gated because CIM discovery returned Not found and the prior reader reported psutil absent. The new one-shot reader uses a hash-pinned official Windows psutil wheel, installed only in an isolated QA target. It will observe Node/runner PID, parent, executable, exact native creation FILETIME, Windows owner/session and job membership. Raw command lines and credential-file values are not exported. It has no process termination, task mutation, SDK launch or writer operation.

Prospective precheck and exact code/dependency bytes were frozen at 306645a71f6c7061402d3a7b3239a0ae26b90733 before submission. Probe byte SHA256 is 7cc6893ebb6e7e149e699f4c7e1e4c28278dc6140f08732f668aab811994eb7e. Source receipt arguments must retain that freeze; later evidence commits must not relabel the executed source.

Native command was submitted exactly once as PID 9904 on DESKTOP-1R1081M. The latest terminal session observation reported Blocked=false and runtime 133 seconds. Subsequent output reads returned no output and no terminal exit. The current phase is unknown: neither dependency installation nor process identities are verified. Do not rerun that command while its outcome is unresolved. Resume by reading output for PID 9904 and the QA evidence path recorded in native-checkpoint.json.

The QA path is E:\NEXUS-QA\rdc-l1-native-identity-20261014T0419Z. The command uses pip --isolated, an explicit official index, --target, --no-deps, wheels only and --require-hashes. It leaves global site-packages and the installed RDC/runtime files untouched. No runtime/task/client cutover is performed by this source.

Both device pings succeeded at 04:27:13Z. That demonstrates observed connectivity, not full automatic recovery, hang detection, sustained uptime or market freshness. Before any future retargeting of the SAME existing Recovery task, verify current exact client identities, an independently surviving execution route, positive old-client exits and one-client adoption. Keep legacy guard, task XML backup, Adobe Node, existing runner lanes and Bybit Demo/Paper owner state; Live=false.

Primary dependency provenance: https://pypi.org/project/psutil/7.2.2/
Upstream API documentation: https://psutil.readthedocs.io/stable/
Win32 job read API: https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob
