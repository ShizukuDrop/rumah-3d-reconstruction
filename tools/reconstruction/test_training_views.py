"""Appearance selection must preserve rare views and strict split boundaries."""

from copy import deepcopy
import unittest

import numpy as np

try:
    from .training_views import TrainingViewConfig, select_training_views
except ImportError:
    from training_views import TrainingViewConfig, select_training_views


class TrainingViewTests(unittest.TestCase):
    def inputs(self, count=3):
        frames, quality, measurements = [], {}, {}
        pattern = np.tile([35.0, 170.0, 70.0, 210.0], 36)
        for frame_id in range(count):
            frames.append({"id": frame_id, "time_seconds": frame_id * 0.1, "split": "train",
                           "images": {lens: f"{lens}/{frame_id}.jpg" for lens in ("cam0", "cam1")},
                           "selected": False})
            quality[frame_id] = {"views": {lens: {"verdict": "sharp", "confirmed": True,
                                                   "training_eligible": True} for lens in ("cam0", "cam1")}}
            measurements[frame_id] = {lens: {"edge_width_native_px": 10.0,
                                              "signature": {"valid": [1.0] * 144,
                                                            "luma": pattern.tolist(),
                                                            "edge": (pattern / 10).tolist()}}
                                      for lens in ("cam0", "cam1")}
        return {"frames": frames, "source_selection_sha256": "capture"}, quality, measurements

    def view(self, report, frame_id, lens):
        return next(row for row in report["views"] if row["frame_id"] == frame_id and row["lens"] == lens)

    def test_rare_appearance_without_alignment_anchor_is_selected(self):
        capture, quality, measurements = self.inputs()
        measurements[1]["cam1"]["signature"]["luma"] = np.roll(measurements[1]["cam1"]["signature"]["luma"], 1).tolist()
        result = select_training_views(capture, quality, measurements)
        row = self.view(result, 1, "cam1")
        self.assertTrue(row["selected"])
        self.assertEqual(row["status"], "eligible_pending_pose")
        self.assertFalse(row["ready_for_training"])
        self.assertFalse(result["alignment_anchor_membership_used"])

    def test_duplicate_lens_is_dropped_independently(self):
        capture, quality, measurements = self.inputs()
        measurements[1]["cam1"]["signature"]["luma"] = list(reversed(measurements[1]["cam1"]["signature"]["luma"]))
        result = select_training_views(capture, quality, measurements)
        self.assertFalse(self.view(result, 1, "cam0")["selected"])
        self.assertTrue(self.view(result, 1, "cam1")["selected"])

    def test_confirmed_blur_is_excluded_while_opposite_lens_can_contribute(self):
        capture, quality, measurements = self.inputs(1)
        quality[0]["views"]["cam0"].update(verdict="blur", confirmed=True, training_eligible=False)
        result = select_training_views(capture, quality, measurements)
        self.assertEqual(self.view(result, 0, "cam0")["reasons"], ["confirmed_blur"])
        self.assertFalse(self.view(result, 0, "cam0")["selected"])
        self.assertTrue(self.view(result, 0, "cam1")["selected"])

    def test_heldout_timestamp_is_never_selected_or_used_as_coverage(self):
        capture, quality, measurements = self.inputs()
        capture["frames"][0]["split"] = "eval"
        result = select_training_views(capture, quality, measurements)
        self.assertTrue(all(not row["selected"] for row in result["views"] if row["split"] == "eval"))
        self.assertTrue(self.view(result, 1, "cam0")["selected"])
        self.assertEqual(result["heldout_view_count"], 2)

    def test_low_texture_unknown_remains_a_review_candidate(self):
        capture, quality, measurements = self.inputs(1)
        for lens in ("cam0", "cam1"):
            quality[0]["views"][lens].update(verdict="unknown", confirmed=False, training_eligible=False)
            measurements[0][lens]["edge_width_native_px"] = None
            measurements[0][lens]["signature"]["luma"] = [128.0] * 144
            measurements[0][lens]["signature"]["edge"] = [0.0] * 144
        result = select_training_views(capture, quality, measurements)
        self.assertEqual(result["review_view_count"], 2)
        self.assertEqual(result["eligible_view_count"], 0)
        self.assertFalse(result["quality_coverage_passed"])
        self.assertTrue(all(row["status"] == "review_required" for row in result["views"]))

    def test_unreviewed_duplicate_cannot_suppress_subsequent_clear_view(self):
        capture, quality, measurements = self.inputs(2)
        for lens in ("cam0", "cam1"):
            quality[0]["views"][lens].update(verdict="unknown", confirmed=False, training_eligible=False)
        result = select_training_views(capture, quality, measurements)
        self.assertTrue(self.view(result, 1, "cam0")["selected"])
        self.assertEqual(self.view(result, 1, "cam0")["status"], "eligible_pending_pose")

    def test_region_entry_preserves_matching_appearance(self):
        capture, quality, measurements = self.inputs(2)
        regions = [{"name": "main", "source_frame_min": 0, "source_frame_max": 0},
                   {"name": "bathroom", "source_frame_min": 1, "source_frame_max": 1}]
        result = select_training_views(capture, quality, measurements, regions=regions)
        self.assertTrue(self.view(result, 1, "cam0")["selected"])
        self.assertEqual(len(result["coverage"]), 4)
        self.assertTrue(all(row["quality_coverage_passed"] for row in result["coverage"]))

    def test_maximum_gap_retains_temporal_support_without_reinstating_blur(self):
        capture, quality, measurements = self.inputs(2)
        capture["frames"][1]["time_seconds"] = 1.0
        result = select_training_views(capture, quality, measurements)
        self.assertIn("maximum_appearance_gap", self.view(result, 1, "cam0")["reasons"])
        quality[1]["views"]["cam0"].update(verdict="blur", confirmed=True, training_eligible=False)
        result = select_training_views(capture, quality, measurements)
        self.assertFalse(self.view(result, 1, "cam0")["selected"])
        self.assertTrue(any(gap["lens"] == "cam0" for gap in result["unresolved_gaps"]))

    def test_newly_visible_masked_region_adds_a_candidate(self):
        capture, quality, measurements = self.inputs(2)
        measurements[0]["cam0"]["signature"]["valid"][:24] = [0.0] * 24
        result = select_training_views(capture, quality, measurements)
        self.assertTrue(self.view(result, 1, "cam0")["selected"])

    def test_orientation_can_preserve_a_new_direction(self):
        capture, quality, measurements = self.inputs(2)
        capture["frames"][0]["view_directions"] = {"cam0": [0, 0, 1]}
        capture["frames"][1]["view_directions"] = {"cam0": [1, 0, 0]}
        result = select_training_views(capture, quality, measurements)
        self.assertIn("new_viewing_direction_bin", self.view(result, 1, "cam0")["reasons"])
        self.assertFalse(self.view(result, 1, "cam1")["direction_available"])

    def test_exposure_shift_does_not_invent_new_spatial_content(self):
        capture, quality, measurements = self.inputs(2)
        for lens in ("cam0", "cam1"):
            measurements[1][lens]["signature"]["luma"] = (np.asarray(measurements[1][lens]["signature"]["luma"]) + 10).tolist()
        result = select_training_views(capture, quality, measurements)
        self.assertFalse(self.view(result, 1, "cam0")["selected"])

    def test_input_dictionaries_are_not_modified(self):
        args = self.inputs()
        original = deepcopy(args)
        select_training_views(*args)
        self.assertEqual(args, original)


if __name__ == "__main__":
    unittest.main()
