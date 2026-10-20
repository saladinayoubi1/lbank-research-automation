import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"))
import nexus_mr40_momentum30_october_followup_v1 as r

class OctoberBoundaryTests(unittest.TestCase):
    def rows(self):
        return [[1790812800000+i*r.STEP,"1","1","1","1","0"] for i in range(114)]
    def test_appends_without_replacing_old_rows(self):
        old=[[1790812800000-r.STEP,"2","2","2","2","0"]]
        extension={"rows":self.rows()}
        combined=r.append_october(old,extension)
        self.assertEqual(combined[:1],old);self.assertEqual(len(old),1)
        self.assertEqual(len(combined),115)
    def test_missing_day_or_bar_is_rejected(self):
        with self.assertRaises(ValueError):
            r.append_october([[1790812800000-r.STEP]],{"rows":self.rows()[:-1]})
    def test_previous_source_gap_is_rejected(self):
        with self.assertRaises(ValueError):
            r.append_october([[1790812800000-2*r.STEP]],{"rows":self.rows()})
    def test_internal_gap_or_duplicate_is_rejected(self):
        rows=self.rows();rows[10][0]=rows[9][0]
        with self.assertRaises(ValueError):
            r.append_october([[1790812800000-r.STEP]],{"rows":rows})
    def test_canonical_input_substitution_is_rejected(self):
        data={"value":1};data["digest"]=r.digest(data)
        r.check_digest(data,"digest",data["digest"])
        expected=data["digest"];data["value"]=2
        with self.assertRaises(ValueError):r.check_digest(data,"digest",expected)

if __name__=="__main__":unittest.main()
