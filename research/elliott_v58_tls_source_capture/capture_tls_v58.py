"""V58 TLS-verified public Bybit Spot daily archive transport (research only).

No credentials, API keys, orders or trading. Exact hostname/path, Python
system trust-store HTTPS peer verification, no redirects or proxies, bounded
HTTP body and gzip decompression, atomic source+receipt publication.
A URL declared by an offline parser is NOT proof of capture; this module
records what the direct verified HTTPS session actually returned.
"""
from __future__ import annotations
from datetime import datetime,timezone
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import ssl
import tempfile
import pandas as pd
from prospective_v52 import ProspectiveGateError, read_frozen_protocol,VALID_SYMBOLS,SOURCE_START,SCORE_END

HOST="public.bybit.com"
MAX_COMPRESSED_BYTES=1024*1024*1024
MAX_EXPANDED_BYTES=12*1024*1024*1024
CHUNK=1024*1024
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
AUTO_DEMO=False

def _utc_now():
    return pd.Timestamp(datetime.now(timezone.utc))

def capture_completed_spot_day_tls(symbol,day_utc,output_directory,*,fixture_mode=False):
    """Only complete UTC days; direct HTTPS verified TLS; no filesystem overwrite.

    Fixture mode is explicitly synthetic, restricted to the OS temp folder.
    It exists for offline mocked-connection regression, not production.
    """
    read_frozen_protocol()
    if symbol not in VALID_SYMBOLS:raise ProspectiveGateError("unsupported Bybit Spot symbol")
    try:day=pd.Timestamp(day_utc)
    except Exception as exc:raise ProspectiveGateError("invalid UTC day") from exc
    if day.tzinfo is None or day.utcoffset() is None:raise ProspectiveGateError("UTC-aware day required")
    day=day.tz_convert("UTC")
    if (day.hour,day.minute,day.second,day.microsecond)!=(0,0,0,0) or not SOURCE_START<=day<SCORE_END:
        raise ProspectiveGateError("out-of-window or off-grid UTC daily source")
    if _utc_now()<day+pd.Timedelta(days=1):
        raise ProspectiveGateError("source UTC day not fully complete")
    name=f"{symbol}_{day.date()}.csv.gz"
    resource=f"/spot/{symbol}/{name}"
    url=f"https://{HOST}{resource}"
    output=Path(output_directory)
    if fixture_mode and not output.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ProspectiveGateError("synthetic capture confined to OS temp")
    if output.exists() or output.is_symlink():
        raise ProspectiveGateError("destination already exists; cannot overwrite evidence")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ProspectiveGateError("physical existing output parent required")
    ssl_context=ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    if not ssl_context.check_hostname or ssl_context.verify_mode!=ssl.CERT_REQUIRED:
        raise ProspectiveGateError("TLS certificate and hostname verification not enabled")
    conn=None
    with tempfile.TemporaryDirectory(prefix=".nexus-tls-capture-",dir=output.parent) as tmp:
        stage=Path(tmp)
        file=stage/name
        try:
            conn=http.client.HTTPSConnection(HOST,port=443,timeout=40,context=ssl_context)
            # Handshake before sending HTTP. With Connection: close, CPython
            # HTTPConnection.getresponse() can close/clear conn.sock first.
            conn.connect()
            sock=conn.sock
            if sock is None or not sock.getpeercert():
                raise ProspectiveGateError("verified peer TLS certificate missing")
            tls=str(sock.version())
            if tls not in ("TLSv1.2","TLSv1.3"):
                raise ProspectiveGateError("unsupported peer TLS version")
            conn.request("GET",resource,headers={
              "Accept":"application/octet-stream","Accept-Encoding":"identity",
              "User-Agent":"NEXUS-research-source-capture-v58/1","Connection":"close"})
            response=conn.getresponse()
            code=int(response.status)
            if code!=200:
                raise ProspectiveGateError(f"official HTTPS archive not available: HTTP {code}; no redirects")
            declared=response.getheader("Content-Length")
            if declared is not None:
                try:claimed=int(declared)
                except ValueError as exc:raise ProspectiveGateError("bad HTTP Content-Length") from exc
                if claimed<=0 or claimed>MAX_COMPRESSED_BYTES:
                    raise ProspectiveGateError("HTTP body length invalid or too large")
            digest=hashlib.sha256();n=0
            with file.open("xb") as out:
                while True:
                    block=response.read(CHUNK)
                    if not block:break
                    n+=len(block)
                    if n>MAX_COMPRESSED_BYTES:
                        raise ProspectiveGateError("compressed archive exceeded bounded limit")
                    digest.update(block)
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            if n<64:
                raise ProspectiveGateError("incomplete/missing gzip archive body")
            if declared is not None and n!=claimed:
                raise ProspectiveGateError("truncated response vs HTTP Content-Length")
            with file.open("rb") as magic_reader:
                if magic_reader.read(2)!=b"\x1f\x8b":
                    raise ProspectiveGateError("not a gzip archive")
            decompressed=0
            with gzip.open(file,"rb") as zipped:
                first=zipped.readline(1000)
                decompressed+=len(first)
                if first.decode("utf-8-sig").strip()!= "id,timestamp,price,volume,side,rpi":
                    raise ProspectiveGateError("Bybit public Spot CSV header unexpected")
                while True:
                    buf=zipped.read(CHUNK)
                    if not buf:break
                    decompressed+=len(buf)
                    if decompressed>MAX_EXPANDED_BYTES:
                        raise ProspectiveGateError("decompressed archive exceeded bounded limit")
            if decompressed<=len(first):
                raise ProspectiveGateError("archive has no trade rows")
            receipt={
                "schema":"nexus.elliott-v58-direct-tls-spot-capture.v1",
                "captured_utc":_utc_now().isoformat(),
                "day_utc":day.date().isoformat(),
                "symbol":symbol,
                "actual_request_scheme":"https","actual_request_host":HOST,
                "actual_request_path":resource,"actual_request_url":url,
                "http_status":200,"redirects_followed":False,
                "tls_system_trust_hostname_verification":True,
                "tls_version":tls,"compressed_bytes":n,
                "expanded_bytes":decompressed,"gzip_crc_verified":True,
                "sha256":digest.hexdigest(),
                "archive_path":str(output/name),
                "fixture_mode":bool(fixture_mode),
                "remote_origin_tls_verified":not fixture_mode,
                "research_only":True,"entry_signal":False,"paper_eligible":False,
                "live_enabled":False,"pnl":None,
                "status":"SYNTHETIC_TRANSPORT_TEST_ONLY" if fixture_mode else "PASS_TLS_VERIFIED_SOURCE_CAPTURE_ONLY",
            }
            (stage/"SOURCE_TLS_RECEIPT.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf8")
            if output.exists() or output.is_symlink():
                raise ProspectiveGateError("destination created concurrently; refusing overwrite")
            stage.rename(output)
            return receipt
        except ProspectiveGateError:raise
        except (OSError,ssl.SSLError,ValueError,UnicodeError,gzip.BadGzipFile,http.client.HTTPException) as exc:
            raise ProspectiveGateError("secure source transfer or archive verification failed") from exc
        finally:
            if conn is not None:conn.close()
