"""V94 portable report-path regression; never changes historic evidence."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.elliott_v92_execution_semantics import execution_v92 as v92
from research.elliott_v93_recursive_proof import proof_v93 as v93


class V94PortableCIRegression(unittest.TestCase):
    def test_v92_report_path_is_on_an_available_drive(self):
        self.assertEqual(v92.ROOT.parent, Path(tempfile.gettempdir()))
        self.assertFalse(v92.LIVE_ENABLED)
        self.assertFalse(v92.PAPER_ELIGIBLE)

    def test_v93_report_path_is_on_an_available_drive(self):
        self.assertEqual(v93.ROOT.parent, Path(tempfile.gettempdir()))
        self.assertFalse(v93.LIVE_ENABLED)
        self.assertFalse(v93.PAPER_ELIGIBLE)

    def test_v92_ci_write_preserves_committed_historical_evidence(self):
        rel=Path("docs/evidence/elliott-v92-synthetic-execution-gate-20261017/V92_EXECUTION_CONTRACT_AUDIT.json")
        source=v92.REPO/rel
        saved=source.read_bytes()
        self.assertEqual(hashlib.sha256(saved).hexdigest(),v93.V92_SHA)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v92,"ROOT",Path(tmp)):
                got=v92.audit_denied_cases()
                written=json.loads((Path(tmp)/"V92_EXECUTION_CONTRACT_AUDIT.json").read_bytes())
                earlier=json.loads(saved)
                for obj in (written,earlier):
                    obj.pop("created_utc",None)
                self.assertEqual(written,earlier)
                self.assertEqual(got["orders"],0)
        self.assertEqual(saved,source.read_bytes())

    def test_v93_ci_write_preserves_committed_historical_evidence(self):
        rel=Path("docs/evidence/elliott-v93-recursive-proof-20261017/V93_PROOF_OBLIGATIONS.json")
        source=v93.REPO/rel
        saved=source.read_bytes()
        self.assertEqual(hashlib.sha256(saved).hexdigest(),"fa55b3dd524fba9de7546fba8ea110db30a1e7b9bb8507ff7c79325ad8a35f58")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v93,"ROOT",Path(tmp)):
                got=v93.audit_prior_cases()
                written=json.loads((Path(tmp)/"V93_PROOF_OBLIGATIONS.json").read_bytes())
                earlier=json.loads(saved)
                for obj in (written,earlier):
                    obj.pop("recorded_utc",None)
                self.assertEqual(written,earlier)
                self.assertEqual(got["signals"],0)
        self.assertEqual(saved,source.read_bytes())
