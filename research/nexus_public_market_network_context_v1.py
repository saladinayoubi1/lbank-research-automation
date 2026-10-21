"""Read local public-market network settings; disclose no proxy URLs, IPs or keys."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
from urllib.parse import urlsplit


def run(output):
    if output.exists():
        raise ValueError("refuse context overwrite")
    import requests
    import winreg
    report = {"schema": "nexus.public-market-local-network-context.v1", "worker": platform.node(),
              "observed_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "network_requests": 0, "settings_changed": False, "paper_state_changed": False,
              "proxy_urls_disclosed": False, "ip_addresses_disclosed": False, "exchange_orders": 0}
    variables = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
    report["environment_presence"] = {v: bool(os.environ.get(v) or os.environ.get(v.lower())) for v in variables}
    report["effective_proxies"] = {}
    for host in ("https://api.bybit.com", "https://www.okx.com", "https://openapi.okx.com"):
        proxies = requests.utils.get_environ_proxies(host)
        details = []
        for key, value in proxies.items():
            if key not in ("http", "https", "all"):
                continue
            parsed = urlsplit(value if "://" in value else "http://" + value)
            details.append({"kind": key, "scheme": parsed.scheme,
                            "loopback": parsed.hostname in ("127.0.0.1", "localhost", "::1"),
                            "contains_credentials": parsed.username is not None or parsed.password is not None})
        report["effective_proxies"][host] = {"configured": bool(details), "details": details}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            def value(name):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    return None
            report["windows_user_proxy"] = {"enabled": value("ProxyEnable") == 1,
                                            "proxy_server_present": bool(value("ProxyServer")),
                                            "automatic_config_url_present": bool(value("AutoConfigURL"))}
    except OSError as exc:
        report["windows_user_proxy"] = {"read_error_type": type(exc).__name__}
    hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/drivers/etc/hosts"
    names = ("api.bybit.com", "www.okx.com", "openapi.okx.com")
    try:
        mapped = {v: 0 for v in names}
        for line in hosts.read_text(encoding="utf-8", errors="replace").splitlines():
            fields = line.split("#", 1)[0].split()
            for name in fields[1:]:
                if name.lower() in mapped:
                    mapped[name.lower()] += 1
        report["hosts_override_counts"] = mapped
    except OSError as exc:
        report["hosts_read_error_type"] = type(exc).__name__
    report["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    report["digest"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    with output.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(report, out, sort_keys=True, indent=2)
        out.write("\n")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(**vars(parser.parse_args()))
