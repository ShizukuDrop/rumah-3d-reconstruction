"""Regression cases for noise, masked content and asymmetric paired blur."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

try:
    from .quality import QualityConfig, compare_views, evaluate_pair, measure_view
except ImportError:
    from quality import QualityConfig, compare_views, evaluate_pair, measure_view


class QualityTests(unittest.TestCase):
    def setUp(self):
        cv2.setNumThreads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = QualityConfig(max_edge=512, calibration_verified=True,
                                    max_sharp_edge_width_native_px=3.5)
        y, x = np.indices((512, 512))
        self.clear = np.where(((x // 64) + (y // 64)) % 2, 210, 35).astype(np.uint8)
        self.mask = np.full_like(self.clear, 255)

    def tearDown(self):
        self.temp.cleanup()

    def measure(self, image, name, lens="cam0", mask=None, time=0.0):
        directory = self.root / lens
        directory.mkdir(exist_ok=True)
        path, mask_path = directory / f"{name}.png", directory / f"{name}.mask.png"
        cv2.imwrite(str(path), image)
        cv2.imwrite(str(mask_path), self.mask if mask is None else mask)
        result = measure_view(path, mask_path, self.config)
        result["time_seconds"] = time
        return result

    def refs(self, lens):
        return [self.measure(self.clear, "ref1", lens, time=-0.1),
                self.measure(self.clear, "ref2", lens, time=0.1)]

    def test_blur_in_one_lens_rejects_pair_and_clear_lens_remains_eligible(self):
        blurred = cv2.GaussianBlur(self.clear, (0, 0), 3)
        pair = {"cam0": self.measure(self.clear, "candidate", "cam0"),
                "cam1": self.measure(blurred, "candidate", "cam1")}
        result = evaluate_pair(pair, {lens: self.refs(lens) for lens in pair}, self.config)
        self.assertEqual(result["action"], "reject", result)
        self.assertEqual(result["reason"], "one_lens_blurry")
        self.assertTrue(result["training_eligible"]["cam0"])
        self.assertFalse(result["training_eligible"]["cam1"])
        self.assertTrue(all(check["supported"] for check in result["views"]["cam1"]["tracked_edge_checks"]))
        # Repetition never silently restores a third blurry pair.
        self.assertEqual(evaluate_pair(pair, {lens: self.refs(lens) for lens in pair}, self.config)["action"], "reject")

    def test_blurred_edges_are_wider_with_strong_spatial_support(self):
        clear = self.measure(self.clear, "clear")
        blurred = self.measure(cv2.GaussianBlur(self.clear, (0, 0), 3), "blur")
        self.assertTrue(clear["measurement_reliable"], clear)
        self.assertTrue(blurred["measurement_reliable"], blurred)
        self.assertGreater(blurred["edge_width_native_px"], 2 * clear["edge_width_native_px"])

    def test_noise_and_textureless_images_remain_unknown(self):
        rng = np.random.default_rng(20)
        noise = np.clip(rng.normal(128, 35, self.clear.shape), 0, 255).astype(np.uint8)
        for name, image in (("noise", noise), ("blank", np.full_like(self.clear, 128))):
            pair = {lens: self.measure(image, name, lens) for lens in ("cam0", "cam1")}
            result = evaluate_pair(pair, {lens: self.refs(lens) for lens in pair}, self.config)
            self.assertEqual(result["action"], "review", result)
            self.assertTrue(all(view["verdict"] == "unknown" for view in result["views"].values()))

    def test_masked_detail_cannot_create_texture_support(self):
        mask = np.full_like(self.clear, 255)
        mask[:, :256] = 0
        mixed = np.full_like(self.clear, 128)
        mixed[:, :256] = self.clear[:, :256]
        result = self.measure(mixed, "masked", mask=mask)
        self.assertFalse(result["measurement_reliable"])
        self.assertEqual(result["edge_profiles"], 0)
        self.assertAlmostEqual(result["valid_fraction"], 0.5)

    def test_opposite_lens_and_unrelated_spatial_content_are_not_references(self):
        view = self.measure(self.clear, "candidate")
        wrong_lens = self.measure(self.clear, "other", "cam1")
        self.assertFalse(compare_views(view, wrong_lens, self.config)["comparable"])
        shifted = self.measure(np.roll(self.clear, 32, axis=1), "shifted", time=0.1)
        self.assertFalse(compare_views(view, shifted, self.config)["comparable"])

    def test_uncalibrated_thresholds_cannot_reject_or_approve_training(self):
        config = replace(self.config, calibration_verified=False)
        blurred = cv2.GaussianBlur(self.clear, (0, 0), 3)
        pair = {lens: self.measure(blurred, "blur", lens) for lens in ("cam0", "cam1")}
        result = evaluate_pair(pair, {lens: self.refs(lens) for lens in pair}, config)
        self.assertEqual(result["action"], "review")
        self.assertFalse(any(result["training_eligible"].values()))

    def test_duplicate_reference_does_not_meet_support_requirement(self):
        pair = {lens: self.measure(self.clear, "candidate", lens) for lens in ("cam0", "cam1")}
        references = {lens: [self.refs(lens)[0]] * 4 for lens in pair}
        self.assertEqual(evaluate_pair(pair, references, self.config)["action"], "review")

    def test_blurred_neighborhood_is_not_its_own_sharp_baseline(self):
        blurred = cv2.GaussianBlur(self.clear, (0, 0), 3)
        pair = {lens: self.measure(blurred, "candidate", lens) for lens in ("cam0", "cam1")}
        references = {lens: [self.measure(blurred, "ref1", lens, time=-0.1),
                             self.measure(blurred, "ref2", lens, time=0.1)] for lens in pair}
        result = evaluate_pair(pair, references, self.config)
        self.assertEqual(result["action"], "review")
        self.assertTrue(all("no_validated_sharp_reference" in d["reasons"] for d in result["views"].values()))

    def test_uninformative_other_lens_cannot_hide_confirmed_blur(self):
        pair = {"cam0": self.measure(np.full_like(self.clear, 128), "blank", "cam0"),
                "cam1": self.measure(cv2.GaussianBlur(self.clear, (0, 0), 3), "blur", "cam1")}
        result = evaluate_pair(pair, {lens: self.refs(lens) for lens in pair}, self.config)
        self.assertEqual(result["action"], "reject")
        self.assertEqual(result["views"]["cam0"]["verdict"], "unknown")

    def test_verified_configuration_requires_a_sharp_reference_ceiling(self):
        with self.assertRaisesRegex(ValueError, "ceiling"):
            QualityConfig(calibration_verified=True)

    def test_masks_must_match_source_dimensions(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.measure(self.clear, "wrongmask", mask=np.full((16, 16), 255, np.uint8))

    def test_pair_requires_both_lenses_and_equal_time(self):
        view = self.measure(self.clear, "candidate")
        with self.assertRaises(ValueError):
            evaluate_pair({"cam0": view}, {}, self.config)
        other = self.measure(self.clear, "candidate", "cam1", time=0.1)
        with self.assertRaises(ValueError):
            evaluate_pair({"cam0": view, "cam1": other}, {}, self.config)


if __name__ == "__main__":
    unittest.main()
