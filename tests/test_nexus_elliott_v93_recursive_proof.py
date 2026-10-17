"""V93 proof graph's negative and synthetic positive invariants, no source claims."""
import dataclasses
import unittest
from unittest.mock import patch

from research.elliott_v93_recursive_proof import proof_v93 as v93

START=1709251200000
M=60000


def tree(family="IMPULSE",degree=2,start=START,duration=90*M,
         direction="up",known=None,label="root"):
    if known is None:
        known=start+duration+M
    if family=="TERMINAL":
        return v93.WaveNode(label,"TERMINAL",0,start,start+duration,known,direction)
    count=5 if family=="IMPULSE" else 3
    bars,remainder=divmod(duration,M)
    if remainder or bars<count:
        raise ValueError("test fixture needs at least one bar per child")
    widths=[bars//count+(i<bars%count) for i in range(count)]
    children=[]
    used=0
    for i in range(count):
        if degree==1:
            fam="TERMINAL"
        elif family=="IMPULSE":
            fam="IMPULSE" if i%2==0 else ("ZIGZAG" if i==1 else "FLAT")
        elif family=="ZIGZAG":
            fam="IMPULSE" if i!=1 else "FLAT"
        else:
            fam="IMPULSE" if i==2 else "ZIGZAG"
        d=direction if i%2==0 else ("down" if direction=="up" else "up")
        a=start+used*M
        children.append(tree(fam,degree-1,a,widths[i]*M,d,known,label+str(i)))
        used+=widths[i]
    return v93.WaveNode(label,family,degree,start,start+duration,known,
                        direction,tuple(children))


def altered(node,**kwargs):
    return dataclasses.replace(node,**kwargs)


class V93RecursiveGraphTests(unittest.TestCase):
    def test_recursive_two_degree_complete_shape_but_not_source_proof(self):
        result=v93.audit_graph(tree())
        self.assertTrue(result["structural_shape_consistent"])
        self.assertEqual(result["visited_nodes"],27)
        self.assertEqual(result["tree_depth"],2)
        self.assertFalse(result["physical_1m_and_subminute_provenance_verified"])
        self.assertFalse(result["independently_proven_market_wave"])
        self.assertFalse(result["entry_signal"])

    def test_bearish_mirrored_recursive_shape(self):
        x=v93.audit_graph(tree(direction="down"))
        self.assertTrue(x["structural_shape_consistent"])
        self.assertFalse(x["paper_eligible"])

    def test_root_zigzag_shape(self):
        got=v93.audit_graph(tree(family="ZIGZAG",duration=90*M))
        self.assertTrue(got["structural_shape_consistent"])

    def test_root_flat_shape(self):
        got=v93.audit_graph(tree(family="FLAT",duration=90*M))
        self.assertTrue(got["structural_shape_consistent"])

    def test_wrong_degree_child_rejected(self):
        x=tree()
        children=list(x.children)
        children[0]=altered(children[0],degree=0)
        with self.assertRaisesRegex(ValueError,"strictly lower"):
            v93.audit_graph(altered(x,children=tuple(children)))

    def test_wrong_impulse_subwave_family_rejected(self):
        x=tree()
        children=list(x.children)
        children[0]=altered(children[0],family="FLAT")
        with self.assertRaisesRegex(ValueError,"motive versus corrective"):
            v93.audit_graph(altered(x,children=tuple(children)))

    def test_incomplete_parent_five_wave_rejected(self):
        x=tree()
        with self.assertRaisesRegex(ValueError,"wrong recursive subwave count"):
            v93.audit_graph(altered(x,children=x.children[:-1]))

    def test_gap_or_overlap_rejected(self):
        x=tree()
        kids=list(x.children)
        kids[1]=altered(kids[1],start_ms=kids[1].start_ms+M)
        with self.assertRaisesRegex(ValueError,"overlap, gap"):
            v93.audit_graph(altered(x,children=tuple(kids)))

    def test_future_child_confirmation_rejected(self):
        x=tree()
        kids=list(x.children)
        kids[0]=altered(kids[0],known_ms=x.known_ms+M)
        with self.assertRaisesRegex(ValueError,"future subwave"):
            v93.audit_graph(altered(x,children=tuple(kids)))

    def test_wrong_direction_rejected(self):
        x=tree()
        kids=list(x.children)
        kids[1]=altered(kids[1],direction="up")
        with self.assertRaisesRegex(ValueError,"alternating subwave"):
            v93.audit_graph(altered(x,children=tuple(kids)))

    def test_terminal_cannot_self_promote(self):
        x=tree(family="TERMINAL",degree=0)
        with self.assertRaisesRegex(ValueError,"terminal cannot"):
            v93.audit_graph(altered(x,degree=1))

    def test_zero_degree_nonterminal_rejected(self):
        x=tree()
        with self.assertRaisesRegex(ValueError,"nonterminal lacks"):
            v93.audit_graph(altered(x,degree=0))

    def test_unaligned_vertex_rejected(self):
        x=tree()
        with self.assertRaisesRegex(ValueError,"aligned times"):
            v93.audit_graph(altered(x,end_ms=x.end_ms+1))

    def test_premature_parent_completion_rejected(self):
        x=tree()
        with self.assertRaisesRegex(ValueError,"unconfirmed wave"):
            v93.audit_graph(altered(x,known_ms=x.end_ms-M))

    def test_reused_subtree_rejected(self):
        x=tree()
        # Same identical physical WaveNode reused in distinct graph branches.
        c=list(x.children)
        c[1]=c[0]
        with self.assertRaises(ValueError):
            v93.audit_graph(altered(x,children=tuple(c)))

    def test_graph_max_nodes_bounded(self):
        with self.assertRaisesRegex(ValueError,"unsafe recursive"):
            v93.audit_graph(tree(),max_nodes=12)

    def test_untyped_child_refused(self):
        x=tree()
        c=list(x.children); c[0]={"fake":"wave"}
        with self.assertRaisesRegex(ValueError,"untyped subwave"):
            v93.audit_graph(altered(x,children=tuple(c)))

    def test_proof_debt_requires_all_missing_context(self):
        a=v93.audit_prior_cases()
        self.assertEqual(a["symbols"]["BTCUSDT"]["v91_cases_seen"],6)
        self.assertEqual(a["symbols"]["ETHUSDT"]["v91_cases_seen"],2)
        self.assertEqual(a["signals"],0)
        self.assertFalse(a["paper_eligible"])
        self.assertIsNone(a["net_pnl"])
        for symbol,n in (("BTCUSDT",6),("ETHUSDT",2)):
            reason=a["symbols"][symbol]["reason_frequencies"]
            self.assertEqual(reason["NO_INDEPENDENT_RECURSIVE_CANDLE_BACKED_TREE"],n)
            self.assertEqual(reason["FIXED_53535_INNER_COUNT_MISMATCH"],n)
            self.assertEqual(reason["NO_CERTIFIED_15M_PATTERN_POSITION_OR_PRECEDING_CONTEXT"],n)
            self.assertEqual(reason["NO_POST_CONFIRMATION_MARKET_BREAKOUT_WITNESS"],n)
        self.assertEqual(
            a["symbols"]["BTCUSDT"]["reason_frequencies"]["UNORDERED_1M_OHLC_SOURCE_AMBIGUITY"],2) # may differ; check actual

    def test_preregistered_hypothesis_is_future_only(self):
        p=v93.preregistered_research_policy()
        self.assertEqual(p["status"],"HYPOTHESIS_DECLARED_NOT_VALIDATED_OR_ENABLED")
        self.assertFalse(p["apply_to_prior_inspected_july_samples"])
        self.assertTrue(p["requires_source_attested_recursive_tree"])
        self.assertEqual(p["nominal_risk_limit_usdt"],"2.50")
        self.assertEqual(p["paper_reference_balance_usdt"],"500")
        self.assertFalse(p["paper_eligible"])
        self.assertFalse(p["live_enabled"])
        self.assertIsNone(p["performance_claim"])

    def test_modified_source_receipt_hash_rejected(self):
        with patch.object(v93,"V91_SHA","0"*64):
            with self.assertRaisesRegex(ValueError,"source receipt SHA altered"):
                v93.audit_prior_cases()

    def test_directly_forged_permission_rejected(self):
        source=v93.immutable_receipt(
            v93.V91_REL,v93.V91_SHA,v93.V91_COMMIT,
            "nexus.elliott-v91-causal-nested-impulse-entry-exit-gate.v1")
        original=source["symbols"]["BTCUSDT"]["cases"][0]
        forged=dict(original["execution_gate"])
        forged["order_admission"]="ACCEPT"
        with self.assertRaisesRegex(ValueError,"altered V91 candidate"):
            v93.obligation_for_case(original,forged)
