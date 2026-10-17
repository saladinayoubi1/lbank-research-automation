"""V58 TLS-pinned direct archive transport regression discovery."""
import sys
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]/"research"
for _part in ("elliott_v52_prospective","elliott_v58_tls_source_capture"):
    sys.path.insert(0,str(_ROOT/_part))
from test_tls_v58 import V58VerifiedTransportTests  # noqa: F401,E402
