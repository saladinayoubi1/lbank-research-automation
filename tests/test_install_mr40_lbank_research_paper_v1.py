import importlib.util
from pathlib import Path
import subprocess
import unittest

spec=importlib.util.spec_from_file_location("paper_task_install_test",Path(__file__).resolve().parents[1]/"scripts/install_mr40_lbank_research_paper_v1.py")
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)


class NativeTaskVerificationTests(unittest.TestCase):
    def fixture(self,level="",enabled="",args=None):
        expected=["paper.py","--source-sha","a"*40]
        text=f'<Task xmlns="{install.NS}"><Principals><Principal>{level}<LogonType>InteractiveToken</LogonType></Principal></Principals><Settings>{enabled}</Settings><Actions><Exec><Arguments>{subprocess.list2cmdline(args or expected)}</Arguments></Exec></Actions></Task>'
        return text,expected

    def test_export_omitting_default_runlevel_and_enabled_is_valid(self):
        install.verify_registered(*self.fixture())
        install.verify_registered(*self.fixture('<RunLevel>LeastPrivilege</RunLevel>','<Enabled>true</Enabled>'))

    def test_elevated_disabled_and_other_source_tasks_are_rejected(self):
        for fixture in (self.fixture('<RunLevel>HighestAvailable</RunLevel>'),
                        self.fixture(enabled='<Enabled>false</Enabled>'),self.fixture(args=["other.py"])):
            with self.assertRaisesRegex(ValueError,"identity_verification_failed"):
                install.verify_registered(*fixture)


if __name__ == "__main__": unittest.main()
