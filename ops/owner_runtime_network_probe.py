"""Read-only owner runtime checks; no configuration or account writes."""
import concurrent.futures
import json
import pathlib
import socket
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

sys.path.insert(0, r"E:\NEXUS\demo-terminal-qa-deps")
import psutil


def check_host(host):
    started = time.monotonic()
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        with socket.create_connection((host, 443), timeout=5):
            connected = True
        return {"host": host, "addresses": addresses, "tcp_443": connected,
                "seconds": round(time.monotonic()-started, 2)}
    except Exception as e:
        return {"host": host, "error": type(e).__name__, "seconds": round(time.monotonic()-started, 2)}


def check_https(url):
    started = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "NEXUS-owner-readonly-probe/1"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=8) as response:
            body = response.read(96000)
            result = {"url": url, "http_status": response.status}
            if "bybit.com" in url or "bytick.com" in url:
                payload = json.loads(body)
                result.update(ret_code=payload.get("retCode"), server_time_ms=payload.get("time"),
                              candle_rows=len(payload.get("result", {}).get("list", [])))
            return dict(result, seconds=round(time.monotonic()-started, 2))
    except urllib.error.HTTPError as e:
        return {"url": url, "http_status": e.code, "seconds": round(time.monotonic()-started, 2)}
    except Exception as e:
        return {"url": url, "error": type(e).__name__, "seconds": round(time.monotonic()-started, 2)}


def main():
    root = pathlib.Path(r"C:\Users\afaq\AppData\Local\NEXUS\actions-runner")
    config = json.loads((root / ".runner").read_text(encoding="utf-8-sig"))
    hosts = ["api.github.com", urllib.parse.urlparse(config["serverUrl"]).hostname,
             urllib.parse.urlparse(config["serverUrlV2"]).hostname, "api.bybit.com", "api.bytick.com"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        print(json.dumps({"network": list(pool.map(check_host, hosts))}), flush=True)
    urls = [config["serverUrl"].rstrip("/")+"/_apis/connectionData?connectOptions=1",
            config["serverUrlV2"],
            "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=240&limit=3",
            "https://api.bytick.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=240&limit=3"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        print(json.dumps({"https_probes": list(pool.map(check_https, urls))}), flush=True)
    runners = []
    for proc in psutil.process_iter(["pid", "name", "ppid", "exe", "cwd"], ad_value=None):
        if (proc.info["name"] or "").lower() in ("runner.listener.exe", "runner.worker.exe"):
            runners.append(proc.info)
    print(json.dumps({"windows_runner_processes": runners}), flush=True)
    diag = sorted((root / "_diag").glob("Runner_*.log"), key=lambda p: p.stat().st_mtime)[-1]
    lines = diag.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    # Output final connection diagnostics; never credential file contents.
    selected = [line for line in lines if any(k in line for k in
                ("ERR ", "WARN ", "Listening for Jobs", "Connected to GitHub", "Connecting to the Runner server"))]
    print(json.dumps({"latest_log": diag.name, "diagnostics": selected[-12:]}), flush=True)


if __name__ == "__main__":
    main()
