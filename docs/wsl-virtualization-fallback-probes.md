# WSL virtualization fallback probes

This change strengthens the physical Windows preflight without touching the existing Windows runner service or performing a reboot.

When CIM/WMI cannot reliably report firmware virtualization, the diagnostic now also uses native Windows processor feature flags, bounded service state, Hyper-V event evidence, and a disposable tiny WSL2 import probe. The probe is created under ProgramData, unregisters itself on success, and removes its temporary files in all cases.

The decision remains fail-closed. It reports firmware virtualization disabled only when Windows exposes that state explicitly; otherwise it distinguishes kernel, hypervisor, restart, or uncertain states without claiming success.
