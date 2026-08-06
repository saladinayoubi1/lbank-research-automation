from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import shutil
import statistics
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "data" / "system_capacity_report.json"


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def gib(value: int) -> float:
    return round(value / (1024 ** 3), 2)


def memory_info() -> dict[str, float]:
    if os.name == "nt":
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return {
                "total_gib": gib(status.ullTotalPhys),
                "available_gib": gib(status.ullAvailPhys),
                "used_percent": float(status.dwMemoryLoad),
            }
    return {"total_gib": 0.0, "available_gib": 0.0, "used_percent": 0.0}


def cpu_benchmark(seconds: float = 3.0) -> dict[str, float]:
    payload = b"lbank-capacity-test" * 4096
    count = 0
    start = time.perf_counter()
    deadline = start + seconds
    while time.perf_counter() < deadline:
        hashlib.sha256(payload).digest()
        count += 1
    elapsed = time.perf_counter() - start
    return {
        "duration_seconds": round(elapsed, 3),
        "sha256_ops_per_second": round(count / elapsed, 1),
    }


def disk_benchmark(size_mib: int = 64) -> dict[str, float]:
    block = os.urandom(1024 * 1024)
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="lbank_capacity_", suffix=".bin", delete=False, dir=ROOT) as handle:
            path = Path(handle.name)
            start = time.perf_counter()
            for _ in range(size_mib):
                handle.write(block)
            handle.flush()
            os.fsync(handle.fileno())
            write_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        total = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
        read_elapsed = time.perf_counter() - start
        return {
            "test_size_mib": size_mib,
            "write_mib_per_second": round(size_mib / write_elapsed, 1),
            "read_mib_per_second": round((total / 1024 / 1024) / read_elapsed, 1),
        }
    finally:
        if path and path.exists():
            path.unlink(missing_ok=True)


def dashboard_latency(samples: int = 10) -> dict[str, object]:
    url = "http://127.0.0.1:8000/health"
    timings: list[float] = []
    failures = 0
    for _ in range(samples):
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                response.read()
                if response.status != 200:
                    failures += 1
                    continue
            timings.append((time.perf_counter() - start) * 1000)
        except Exception:
            failures += 1
    return {
        "url": url,
        "samples": samples,
        "successful": len(timings),
        "failures": failures,
        "average_ms": round(statistics.mean(timings), 2) if timings else None,
        "p95_ms": round(sorted(timings)[max(0, int(len(timings) * 0.95) - 1)], 2) if timings else None,
    }


def recommendation(cpu_count: int, memory: dict[str, float], disk_free_gib: float) -> dict[str, object]:
    available = memory.get("available_gib", 0.0)
    if available and available < 1.0:
        tier = "low"
        workers = 1
        parallel_jobs = 1
        note = "Only light dashboard and one background job at a time."
    elif available and available < 2.0:
        tier = "limited"
        workers = 1
        parallel_jobs = 1
        note = "Safe for dashboard plus one moderate data job; avoid concurrent backfills."
    elif cpu_count <= 2:
        tier = "limited"
        workers = 1
        parallel_jobs = 1
        note = "CPU is the main limit; run heavy data jobs sequentially."
    else:
        tier = "moderate"
        workers = min(2, max(1, cpu_count // 2))
        parallel_jobs = 2
        note = "Safe for dashboard and up to two moderate jobs, while monitoring memory."
    if disk_free_gib < 10:
        note += " Disk space is low; clean or move historical datasets."
    return {
        "capacity_tier": tier,
        "recommended_server_workers": workers,
        "recommended_parallel_data_jobs": parallel_jobs,
        "note": note,
    }


def main() -> int:
    memory = memory_info()
    disk = shutil.disk_usage(ROOT)
    cpu_count = os.cpu_count() or 1
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_logical_cores": cpu_count,
            "memory": memory,
            "disk_total_gib": gib(disk.total),
            "disk_free_gib": gib(disk.free),
        },
        "benchmarks": {
            "cpu": cpu_benchmark(),
            "disk": disk_benchmark(),
            "dashboard": dashboard_latency(),
        },
    }
    report["recommendation"] = recommendation(cpu_count, memory, report["system"]["disk_free_gib"])
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSaved report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
