"""Synthetic mathematical/causality checks; no market data or vendor execution."""
import importlib.util
import unittest
from unittest import mock

missing = [name for name in ("scipy", "sklearn")
           if importlib.util.find_spec(name) is None]
if missing:
    raise unittest.SkipTest(
        "CTREND scientific extras absent: " + ", ".join(missing)
        + "; Research Evidence Refresh installs the separate locked environment"
    )

import numpy as np
from scipy.stats import rankdata
from sklearn.linear_model import ElasticNet as RealElasticNet

from research import nexus_ctrend_causal_model_v1 as model


def fixture(rows=55, assets=40):
    rng = np.random.default_rng(20102026)
    features = rng.normal(size=(rows, assets, 28))
    caps = rng.uniform(1_000_000, 5_000_000, (rows, assets))
    ranks = np.array([(rankdata(row[:, 0]) - 1) / (assets - 1) - .5 for row in features])
    returns = .04 * ranks + rng.normal(scale=.0001, size=(rows, assets))
    current = rng.normal(size=(assets, 28))
    current_caps = rng.uniform(1_000_000, 5_000_000, assets)
    step = 7 * 24 * 60 * 60 * 1000
    feature_times = 1_500_000_000_000 + np.arange(rows, dtype=np.int64) * step
    label_times = feature_times + step
    return dict(history_features=features, history_returns=returns, history_caps=caps,
                current_features=current, current_caps=current_caps,
                feature_times=feature_times, label_times=label_times,
                current_feature_time=int(label_times[-1]), decision_time=int(label_times[-1]))


class CausalModelTests(unittest.TestCase):
    def test_learns_the_prior_window_and_forms_a_known_quintile(self):
        args = fixture()
        forecast = model.fit_predict(**args)
        self.assertIn(0, forecast.selected_features)
        expected_rank = rankdata(args["current_features"][:, 0])
        self.assertGreater(np.corrcoef(forecast.scores, expected_rank)[0, 1], .99)
        self.assertEqual(len(forecast.members), 8)
        self.assertEqual(tuple(sorted(forecast.members)), forecast.members)
        self.assertEqual(forecast.diagnostics["history_rows_used"], 52)
        self.assertEqual(len(forecast.diagnostics["selection"]["path"]), 200)
        self.assertTrue(forecast.diagnostics["solver"]["all_path_points_converged"])

    def test_only_last_52_rows_can_change_learning(self):
        args = fixture()
        original = model.fit_predict(**args)
        args["history_features"][:3] *= -100
        args["history_returns"][:3] += 20
        args["history_caps"][:3] *= 20
        changed = model.fit_predict(**args)
        np.testing.assert_array_equal(original.scores, changed.scores)
        self.assertEqual(original.selected_features, changed.selected_features)
        args["history_returns"][3:] *= -1
        reversed_signal = model.fit_predict(**args)
        self.assertLess(np.corrcoef(original.scores, reversed_signal.scores)[0, 1], -.99)

    def test_unknown_future_and_nonchronological_clocks_are_rejected(self):
        cases = []
        args = fixture(); args["label_times"][-1] += 1; cases.append(args)
        args = fixture(); args["current_feature_time"] += 1; cases.append(args)
        args = fixture(); args["feature_times"][2] = args["label_times"][2]; cases.append(args)
        args = fixture(); args["feature_times"][2] = args["feature_times"][1]; cases.append(args)
        args = fixture(); args["label_times"] = args["label_times"].astype(float); cases.append(args)
        args = fixture(); args["decision_time"] = True; cases.append(args)
        for args in cases:
            with self.subTest(args={k: args[k] for k in ("decision_time", "current_feature_time")}):
                with self.assertRaises(ValueError):
                    model.fit_predict(**args)

    def test_future_labels_have_no_inference_interface(self):
        args = fixture()
        forecast = model.fit_predict(**args)
        future_labels = np.arange(40, dtype=float)
        future_labels[:] = -1_000_000
        again = model.fit_predict(**args)
        np.testing.assert_array_equal(forecast.scores, again.scores)
        with self.assertRaises(TypeError):
            model.fit_predict(**args, current_returns=future_labels)

    def test_current_snapshot_cannot_precede_known_training_label_end(self):
        args = fixture()
        for timestamp in (0, int(args["label_times"][-1]) - 1,
                          int(args["feature_times"][-1])):
            with self.subTest(current_feature_time=timestamp):
                args["current_feature_time"] = timestamp
                with self.assertRaisesRegex(ValueError, "current feature snapshot"):
                    model.fit_predict(**args)

    def test_missing_past_label_cannot_rerank_snapshots(self):
        args = fixture()
        full = model.fit_predict(**args)
        args["history_returns"][:, 3] = np.nan
        missing = model.fit_predict(**args)
        self.assertEqual(full.diagnostics["training_rank_digest"],
                         missing.diagnostics["training_rank_digest"])
        self.assertEqual(full.diagnostics["current_rank_digest"],
                         missing.diagnostics["current_rank_digest"])
        self.assertEqual(missing.diagnostics["historical_fit_counts"], [39] * 52)
        self.assertIn(3, missing.diagnostics["current_eligible_indices"])

    def test_input_snapshots_are_not_mutated(self):
        args = fixture()
        args["history_eligible"] = np.ones((55, 40), dtype=bool)
        args["current_eligible"] = np.ones(40, dtype=bool)
        copies = {key: value.copy() for key, value in args.items() if isinstance(value, np.ndarray)}
        forecast = model.fit_predict(**args)
        for key, previous in copies.items():
            np.testing.assert_array_equal(args[key], previous)
        with self.assertRaises(ValueError):
            forecast.scores[0] = 1

    def test_current_membership_uses_only_known_mask_caps_and_features(self):
        args = fixture()
        args["current_caps"][0] = 999_999
        args["current_features"][1, 5] = np.nan
        args["current_eligible"] = np.ones(40, dtype=bool)
        args["current_eligible"][2] = False
        forecast = model.fit_predict(**args)
        self.assertTrue(np.isnan(forecast.scores[:3]).all())
        self.assertTrue(all(i not in forecast.members for i in (0, 1, 2)))
        self.assertEqual(len(forecast.diagnostics["current_eligible_indices"]), 37)

    def test_insufficient_cohort_history_and_tied_portfolios_fail_closed(self):
        args = fixture(assets=24)
        with self.assertRaises(model.ForecastUnavailable): model.fit_predict(**args)
        args = fixture(rows=51)
        with self.assertRaises(model.ForecastUnavailable): model.fit_predict(**args)
        args = fixture(); args["history_returns"][-1, :31] = np.nan
        with self.assertRaises(model.ForecastUnavailable): model.fit_predict(**args)
        args = fixture(); args["current_features"][:] = 0
        with self.assertRaises(model.ForecastUnavailable): model.fit_predict(**args)

    def test_no_positive_learned_signal_fails_closed(self):
        args = fixture(); args["history_returns"][:] = 0
        with self.assertRaises(model.ForecastUnavailable): model.fit_predict(**args)
        args = fixture(); args["history_features"][:] = 1
        with self.assertRaises(model.ForecastUnavailable): model.fit_predict(**args)

    def test_nonconvergent_real_solver_is_rejected(self):
        def limited_solver(**kwargs):
            kwargs.update(max_iter=1, tol=1e-30)
            return RealElasticNet(**kwargs)
        with mock.patch.object(model, "ElasticNet", side_effect=limited_solver):
            with self.assertRaisesRegex(model.ForecastUnavailable, "converge"):
                model.fit_predict(**fixture())

    def test_hazen_cutpoints_and_constant_rank_guard(self):
        scores = np.arange(26, dtype=float)
        groups, cuts = model._quintiles(scores, np.ones(26, dtype=bool))
        np.testing.assert_allclose(cuts, [4.7, 9.9, 15.1, 20.3])
        self.assertEqual([len(group) for group in groups], [5, 5, 6, 5, 5])
        ranked, eligible = model._rank_snapshot(np.ones((30, 28)),
                                                np.full(30, 1_000_000.),
                                                np.ones(30, dtype=bool))
        self.assertTrue(eligible.all())
        np.testing.assert_array_equal(ranked, np.zeros((30, 28)))

    def test_malformed_snapshots_are_rejected(self):
        cases = []
        args = fixture(); args["history_features"] = args["history_features"][:, :, :27]; cases.append(args)
        args = fixture(); args["current_caps"] = np.ones((40, 1)); cases.append(args)
        args = fixture(); args["history_caps"][3, 2] = np.inf; cases.append(args)
        args = fixture(); args["current_eligible"] = np.ones(40); cases.append(args)
        args = fixture(); args["history_returns"] = args["history_returns"].astype(str); cases.append(args)
        for args in cases:
            with self.subTest(shape=np.shape(args["history_features"])):
                with self.assertRaises(ValueError): model.fit_predict(**args)


if __name__ == "__main__":
    unittest.main()
