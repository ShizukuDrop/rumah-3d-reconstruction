"""CPU quality measurements and conservative decisions for synchronized lenses.

Thresholds are starting values, not a calibrated camera model. A caller must
visually validate them and set calibration_verified before blur can reject an
alignment pair. Source images and masks are only read.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class QualityConfig:
    max_edge: int = 960
    profile_radius: int = 12
    max_profiles: int = 1600
    min_valid_fraction: float = 0.20
    min_edge_profiles: int = 24
    min_texture_cells: int = 6
    max_noise: float = 12.0
    min_comparable_references: int = 2
    max_reference_gap_seconds: float = 0.75
    min_spatial_correlation: float = 0.75
    min_edge_similarity: float = 0.65
    max_local_difference: float = 22.0
    blur_ratio: float = 1.65
    blur_extra_native_pixels: float = 3.0
    sharp_ratio: float = 1.25
    min_shared_edge_cells: int = 4
    min_blurred_cell_fraction: float = 0.60
    max_sharp_edge_width_native_px: float | None = None
    calibration_verified: bool = False
    require_tracked_edge_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.max_edge < 128 or self.profile_radius < 4 or self.max_profiles < 24:
            raise ValueError("Analysis resolution or edge sampling budget is too small")
        if self.blur_ratio <= self.sharp_ratio or self.sharp_ratio < 1:
            raise ValueError("Require blur_ratio > sharp_ratio >= 1")
        if self.min_comparable_references < 2:
            raise ValueError("At least two comparable references are required")
        if self.calibration_verified and self.max_sharp_edge_width_native_px is None:
            raise ValueError("Verified calibration requires a measured sharp-edge width ceiling")


def _grid(values: np.ndarray, mask: np.ndarray, size: int = 12) -> list[float]:
    weights = cv2.resize(mask.astype(np.float32), (size, size), interpolation=cv2.INTER_AREA)
    weighted = cv2.resize(values * mask, (size, size), interpolation=cv2.INTER_AREA)
    return np.divide(weighted, weights, out=np.zeros_like(weighted), where=weights > 0).ravel().tolist()


def _edge_widths(gray: np.ndarray, valid: np.ndarray, config: QualityConfig,
                 noise: float, scale_x: float, scale_y: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, list]:
    smooth = cv2.GaussianBlur(gray, (0, 0), 0.8)
    gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3, scale=0.125)
    gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3, scale=0.125)
    magnitude = cv2.magnitude(gx, gy)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), 1.5)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), 1.5)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), 1.5)
    coherence = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
    normal_x = gx / np.maximum(magnitude, 1e-6)
    normal_y = gy / np.maximum(magnitude, 1e-6)
    yy, xx = np.indices(gray.shape, dtype=np.float32)
    before = cv2.remap(magnitude, xx - normal_x, yy - normal_y, cv2.INTER_LINEAR)
    after = cv2.remap(magnitude, xx + normal_x, yy + normal_y, cv2.INTER_LINEAR)
    radius = config.profile_radius
    interior = cv2.erode(valid.astype(np.uint8), np.ones((2 * radius + 3,) * 2, np.uint8)) > 0
    interior[:radius + 1] = False
    interior[-radius - 1:] = False
    interior[:, :radius + 1] = False
    interior[:, -radius - 1:] = False
    threshold = max(3.5, 2.0 * noise)
    candidates = interior & (coherence > 0.65) & (magnitude > threshold)
    candidates &= (magnitude >= before) & (magnitude > after)
    rows, cols = np.nonzero(candidates)
    if len(rows) == 0:
        return np.empty(0), np.empty(0, dtype=int), magnitude, []
    # Uniform image-order sampling prevents one high-contrast object from
    # consuming the entire measurement budget.
    chosen = np.linspace(0, len(rows) - 1, min(len(rows), config.max_profiles), dtype=int)
    rows, cols = rows[chosen], cols[chosen]
    dx, dy = normal_x[rows, cols], normal_y[rows, cols]
    offsets = np.linspace(-radius, radius, 4 * radius + 1, dtype=np.float32)
    map_x = cols[:, None].astype(np.float32) + dx[:, None] * offsets
    map_y = rows[:, None].astype(np.float32) + dy[:, None] * offsets
    profiles = cv2.remap(smooth, map_x, map_y, cv2.INTER_LINEAR)
    low = np.mean(profiles[:, :3], axis=1)
    high = np.mean(profiles[:, -3:], axis=1)
    contrast = high - low
    differences = np.diff(profiles, axis=1)
    monotonicity = contrast / np.maximum(np.sum(np.abs(differences), axis=1), 1e-6)
    endpoint_slope = np.maximum(np.max(np.abs(differences[:, :4]), axis=1),
                                np.max(np.abs(differences[:, -4:]), axis=1))
    peak_slope = np.max(np.abs(differences), axis=1)
    good = (contrast >= max(20.0, 8.0 * noise)) & (monotonicity > 0.80)
    good &= endpoint_slope < 0.30 * np.maximum(peak_slope, 1e-6)
    normalized = (profiles[good] - low[good, None]) / contrast[good, None]
    monotone = np.maximum.accumulate(normalized, axis=1)
    widths = np.array([np.interp(0.9, p, offsets) - np.interp(0.1, p, offsets)
                       for p in monotone])
    native_scale = np.sqrt((dx[good] * scale_x) ** 2 + (dy[good] * scale_y) ** 2)
    cells = np.minimum(rows[good] * 8 // gray.shape[0], 7) * 8
    cells += np.minimum(cols[good] * 8 // gray.shape[1], 7)
    widths *= native_scale
    samples = np.column_stack((cols[good], rows[good], widths, dx[good], dy[good]))
    keep = np.linspace(0, len(samples) - 1, min(len(samples), 400), dtype=int)
    return widths, cells, magnitude, np.round(samples[keep], 4).tolist()


def measure_view(image_path: str | Path, mask_path: str | Path,
                 config: QualityConfig = QualityConfig()) -> dict[str, Any]:
    """Measure one lens using a 255-keep, 0-exclude mask in source pixels."""
    image_path, mask_path = Path(image_path), Path(mask_path)
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if image is None or mask is None:
        raise ValueError(f"Unreadable image or mask: {image_path}, {mask_path}")
    if image.shape != mask.shape:
        raise ValueError("Mask dimensions must match the source image exactly")
    height, width = image.shape
    scale = min(1.0, config.max_edge / max(height, width))
    analysis_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    gray = cv2.resize(image.astype(np.float32), analysis_size, interpolation=cv2.INTER_AREA)
    # Requiring a fully valid resize footprint avoids artificial edges at masks.
    valid = cv2.resize((mask > 127).astype(np.float32), analysis_size,
                       interpolation=cv2.INTER_AREA) > 0.999
    noise_mask = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    residual = cv2.filter2D(gray, cv2.CV_32F,
                           np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32))
    noise = float(np.median(np.abs(residual[noise_mask])) / (0.67449 * 6)) if noise_mask.any() else 0.0
    widths, cells, gradient, samples = _edge_widths(gray, valid, config, noise,
                                                   width / analysis_size[0], height / analysis_size[1])
    cell_counts = np.bincount(cells, minlength=64)
    supported_cells = int(np.count_nonzero(cell_counts >= 2))
    valid_fraction = float(np.mean(valid))
    reasons = []
    if valid_fraction < config.min_valid_fraction:
        reasons.append("insufficient_unmasked_area")
    if len(widths) < config.min_edge_profiles or supported_cells < config.min_texture_cells:
        reasons.append("insufficient_spatial_edge_support")
    if noise > config.max_noise:
        reasons.append("high_noise")
    confidence = min(1.0, len(widths) / max(config.min_edge_profiles * 3, 1),
                     supported_cells / max(config.min_texture_cells * 2, 1),
                     valid_fraction / max(config.min_valid_fraction * 2, 1))
    if reasons:
        confidence = min(confidence, 0.49)
    percentiles = np.percentile(widths, [25, 50, 75]).tolist() if len(widths) else [None] * 3
    cell_widths = [float(np.percentile(widths[cells == cell], 25)) if cell_counts[cell] >= 2 else None
                   for cell in range(64)]
    return {
        "image": str(image_path.resolve()), "mask": str(mask_path.resolve()),
        "camera_id": image_path.parent.name, "native_size": [width, height],
        "analysis_size": list(analysis_size), "valid_fraction": valid_fraction,
        "noise_sigma_analysis_pixels": noise, "edge_profiles": int(len(widths)),
        "texture_cells": supported_cells, "edge_width_native_px": percentiles[0],
        "edge_width_percentiles_native_px": dict(zip(("p25", "p50", "p75"), percentiles)),
        "edge_width_cells_native_px": cell_widths,
        "edge_samples": samples,
        "confidence": float(confidence), "measurement_reliable": not reasons,
        "measurement_reasons": reasons, "calibration_verified": config.calibration_verified,
        "signature": {"luma": _grid(gray, valid), "edge": _grid(gradient, valid),
                      "valid": cv2.resize(valid.astype(np.float32), (12, 12),
                                          interpolation=cv2.INTER_AREA).ravel().tolist()},
    }


@lru_cache(maxsize=8)
def _tracking_image(image_path: str, mask_path: str, size: tuple[int, int],
                    image_mtime: int, mask_mtime: int) -> tuple[np.ndarray, np.ndarray]:
    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if image is None or mask is None:
        raise ValueError("Image or mask is unavailable for blur confirmation")
    gray = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    valid = cv2.resize((mask > 127).astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0.999
    return gray, valid.astype(np.uint8)


def _tracked_edge_check(view: dict, reference: dict, config: QualityConfig) -> dict:
    """Corroborate suspected blur using nearby edges after verified local motion."""
    def load(item):
        return _tracking_image(item["image"], item["mask"], tuple(item["analysis_size"]),
                               Path(item["image"]).stat().st_mtime_ns, Path(item["mask"]).stat().st_mtime_ns)
    a, ma = load(view)
    b, mb = load(reference)
    if a.shape != b.shape:
        return {"supported": False, "reason": "different_analysis_size"}
    points = cv2.goodFeaturesToTrack(a, 400, 0.01, 10, mask=ma, blockSize=7)
    if points is None or len(points) < 12:
        return {"supported": False, "reason": "insufficient_trackable_corners"}
    opts = dict(winSize=(31, 31), maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    forward, status, _ = cv2.calcOpticalFlowPyrLK(a, b, points, None, **opts)
    backward, back_status, _ = cv2.calcOpticalFlowPyrLK(b, a, forward, None, **opts)
    keep = status.ravel().astype(bool) & back_status.ravel().astype(bool)
    keep &= np.linalg.norm(points[:, 0] - backward[:, 0], axis=1) <= 1.0
    xy = np.rint(forward[:, 0]).astype(int)
    inside = (xy[:, 0] >= 0) & (xy[:, 0] < b.shape[1]) & (xy[:, 1] >= 0) & (xy[:, 1] < b.shape[0])
    valid_destination = np.zeros(len(xy), dtype=bool)
    valid_destination[inside] = mb[xy[inside, 1], xy[inside, 0]] > 0
    keep &= valid_destination
    if np.count_nonzero(keep) < 12:
        return {"supported": False, "reason": "insufficient_consistent_corner_tracks"}
    source, destination = points[keep], forward[keep]
    transform, inliers = cv2.findHomography(source, destination, cv2.RANSAC, 2.0)
    if transform is None or inliers is None or np.count_nonzero(inliers) < 12:
        return {"supported": False, "reason": "local_motion_fit_failed"}
    source_xy = source[inliers.ravel() > 0, 0]
    regions = (source_xy[:, 1].astype(int) * 4 // a.shape[0]) * 4
    regions += source_xy[:, 0].astype(int) * 4 // a.shape[1]
    if len(np.unique(regions)) < 4:
        return {"supported": False, "reason": "corner_tracks_not_spatially_distributed"}
    sa, sb = np.asarray(view["edge_samples"]), np.asarray(reference["edge_samples"])
    if len(sa) < 16 or len(sb) < 16:
        return {"supported": False, "reason": "insufficient_edge_samples"}
    predicted = cv2.perspectiveTransform(sa[:, :2].astype(np.float32)[None], transform)[0]
    distances = np.sum((predicted[:, None] - sb[None, :, :2]) ** 2, axis=2)
    closest = np.argmin(distances, axis=1)
    distance = np.sqrt(distances[np.arange(len(sa)), closest])
    aligned = (distance <= 3.0) & (np.abs(np.sum(sa[:, 3:5] * sb[closest, 3:5], axis=1)) >= 0.85)
    candidates = np.flatnonzero(aligned)
    # Count each reference edge only once, using its nearest candidate.
    ordered = candidates[np.argsort(distance[candidates])]
    _, unique = np.unique(closest[ordered], return_index=True)
    selected = ordered[unique]
    cells = (sa[selected, 1].astype(int) * 8 // a.shape[0]) * 8
    cells += sa[selected, 0].astype(int) * 8 // a.shape[1]
    if len(selected) < 16 or len(np.unique(cells)) < 4:
        return {"supported": False, "reason": "insufficient_corresponding_edges", "matched_edges": len(selected)}
    ratios = sa[selected, 2] / np.maximum(sb[closest[selected], 2], 1e-6)
    wider = (ratios >= config.blur_ratio) & (sa[selected, 2] - sb[closest[selected], 2] >= config.blur_extra_native_pixels)
    fraction = float(np.mean(wider))
    return {"supported": fraction >= config.min_blurred_cell_fraction,
            "reason": "tracked_edges_widen" if fraction >= config.min_blurred_cell_fraction else "tracked_edges_do_not_confirm_blur",
            "matched_edges": len(selected), "matched_regions": len(np.unique(cells)),
            "median_width_ratio": float(np.median(ratios)), "blurred_fraction": fraction,
            "corner_inliers": int(np.count_nonzero(inliers))}


def compare_views(view: dict, reference: dict, config: QualityConfig = QualityConfig()) -> dict:
    """Check same-lens spatial content before using a local blur reference.

    This is conservative image evidence, not a geometric overlap certificate.
    Callers should supply neighboring views verified by their motion/pose stage.
    """
    if view.get("camera_id") != reference.get("camera_id"):
        return {"comparable": False, "reason": "different_lens"}
    if view.get("image") == reference.get("image"):
        return {"comparable": False, "reason": "same_image"}
    if "time_seconds" not in view or "time_seconds" not in reference:
        return {"comparable": False, "reason": "missing_timestamp"}
    if abs(view["time_seconds"] - reference["time_seconds"]) > config.max_reference_gap_seconds:
        return {"comparable": False, "reason": "reference_too_distant"}
    if not reference.get("measurement_reliable", False):
        return {"comparable": False, "reason": "unreliable_reference"}
    a, b = view["signature"], reference["signature"]
    common = (np.asarray(a["valid"]) > 0.8) & (np.asarray(b["valid"]) > 0.8)
    if np.count_nonzero(common) < 24:
        return {"comparable": False, "reason": "insufficient_common_mask_support"}
    av, bv = np.asarray(a["luma"])[common], np.asarray(b["luma"])[common]
    ac, bc = av - np.mean(av), bv - np.mean(bv)
    correlation = float(np.dot(ac, bc) / max(np.linalg.norm(ac) * np.linalg.norm(bc), 1e-6))
    ae, be = np.asarray(a["edge"])[common], np.asarray(b["edge"])[common]
    edge_similarity = float(np.dot(ae, be) / max(np.linalg.norm(ae) * np.linalg.norm(be), 1e-6))
    local_difference = float(np.median(np.abs(av - bv - np.median(av - bv))))
    comparable = (correlation >= config.min_spatial_correlation
                  and edge_similarity >= config.min_edge_similarity
                  and local_difference <= config.max_local_difference)
    return {"comparable": comparable, "reason": "supported" if comparable else "different_spatial_content",
            "common_cells": int(np.count_nonzero(common)), "luma_correlation": correlation,
            "edge_similarity": edge_similarity, "local_difference": local_difference}


def evaluate_view(view: dict, references: list[dict],
                  config: QualityConfig = QualityConfig()) -> dict:
    result = {"verdict": "unknown", "confirmed": False, "training_eligible": False,
              "calibration_verified": config.calibration_verified,
              "confidence": view["confidence"], "reasons": list(view["measurement_reasons"])}
    comparisons = [compare_views(view, reference, config) for reference in references]
    result["reference_checks"] = comparisons
    usable = [reference for reference, check in zip(references, comparisons) if check["comparable"]]
    # Duplicate references cannot manufacture independent support.
    usable = list({reference["image"]: reference for reference in usable}.values())
    if not view["measurement_reliable"]:
        return result
    if len(usable) < config.min_comparable_references:
        result["reasons"].append("insufficient_comparable_references")
        return result
    baseline = float(np.percentile([item["edge_width_native_px"] for item in usable], 25))
    width = view["edge_width_native_px"]
    ratio = width / max(baseline, 1e-6)
    result.update(reference_count=len(usable), baseline_native_px=baseline, width_ratio=ratio)
    if (config.max_sharp_edge_width_native_px is not None
            and baseline > config.max_sharp_edge_width_native_px):
        result["reasons"].append("no_validated_sharp_reference")
        return result
    # Compare like spatial regions. A changing mix of a sharp door edge and
    # broad wall shadows must not turn the global percentile into a blur alarm.
    cell_ratios, cell_differences = [], []
    for cell, candidate_width in enumerate(view["edge_width_cells_native_px"]):
        reference_widths = [item["edge_width_cells_native_px"][cell] for item in usable
                            if item["edge_width_cells_native_px"][cell] is not None]
        if candidate_width is None or len(reference_widths) < config.min_comparable_references:
            continue
        cell_baseline = float(np.percentile(reference_widths, 25))
        cell_ratios.append(candidate_width / max(cell_baseline, 1e-6))
        cell_differences.append(candidate_width - cell_baseline)
    result["shared_edge_cells"] = len(cell_ratios)
    if len(cell_ratios) < config.min_shared_edge_cells:
        result["reasons"].append("insufficient_matched_edge_regions")
        return result
    spatial_ratio = float(np.median(cell_ratios))
    blurred_fraction = float(np.mean((np.array(cell_ratios) >= config.blur_ratio)
                                     & (np.array(cell_differences) >= config.blur_extra_native_pixels)))
    result.update(spatial_width_ratio=spatial_ratio, blurred_cell_fraction=blurred_fraction)
    if (spatial_ratio >= config.blur_ratio and blurred_fraction >= config.min_blurred_cell_fraction
            and ratio >= config.blur_ratio and width - baseline >= config.blur_extra_native_pixels):
        if config.require_tracked_edge_confirmation:
            tracked = [_tracked_edge_check(view, reference, config) for reference in usable]
            result["tracked_edge_checks"] = tracked
            if sum(check["supported"] for check in tracked) < config.min_comparable_references:
                result["reasons"].append("tracked_edges_do_not_confirm_blur")
                return result
        result.update(verdict="blur", confirmed=config.calibration_verified)
        result["reasons"].append("wider_edges_than_comparable_neighbors")
    elif ratio <= config.sharp_ratio and spatial_ratio <= config.sharp_ratio:
        result.update(verdict="sharp", confirmed=config.calibration_verified,
                      training_eligible=config.calibration_verified)
        result["reasons"].append("consistent_with_sharp_local_reference")
    else:
        result["reasons"].append("borderline_edge_width")
    if not config.calibration_verified:
        result["reasons"].append("thresholds_require_visual_calibration")
    return result


def evaluate_pair(views: dict[str, dict], references: dict[str, list[dict]],
                  config: QualityConfig = QualityConfig()) -> dict:
    """One confirmed blurry lens excludes both images from alignment anchors."""
    if set(views) != {"cam0", "cam1"}:
        raise ValueError("An alignment pair requires exactly cam0 and cam1")
    if any(view.get("camera_id") != lens for lens, view in views.items()):
        raise ValueError("Measurement lens identifiers must match the pair keys")
    if any(not np.isfinite(view.get("time_seconds", np.nan)) for view in views.values()):
        raise ValueError("Lens measurements require finite timestamps")
    if views["cam0"].get("time_seconds") != views["cam1"].get("time_seconds"):
        raise ValueError("Lens measurements must share the same timestamp")
    if views["cam0"].get("source_frame") != views["cam1"].get("source_frame"):
        raise ValueError("Lens measurements must share the same source frame")
    decisions = {lens: evaluate_view(view, references.get(lens, []), config)
                 for lens, view in views.items()}
    blurred = [lens for lens, decision in decisions.items()
               if decision["verdict"] == "blur" and decision["confirmed"]]
    if blurred:
        action, reason = "reject", "one_lens_blurry" if len(blurred) == 1 else "both_lenses_blurry"
    elif all(decision["verdict"] == "sharp" and decision["confirmed"] for decision in decisions.values()):
        action, reason = "keep", "both_lenses_pass_quality"
    else:
        action, reason = "review", "uncertain_or_uncalibrated_quality"
    return {"action": action, "reason": reason, "views": decisions,
            "training_eligible": {lens: decision["training_eligible"] for lens, decision in decisions.items()},
            "automatic_gap_rescue": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument("--reference-frames", type=int, nargs="+", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frame_ids = sorted(set(args.frames + args.reference_frames))
    if len(frame_ids) > 128:
        parser.error("This audit command is limited to 128 explicitly selected pairs per run")
    config = QualityConfig(**json.loads(args.config.read_text())) if args.config else QualityConfig()
    cv2.setNumThreads(1)
    selection = json.loads((args.dataset / "analysis/frame-selection.json").read_text())
    rows = {row["source_frame"]: row for row in selection["selected"]}
    measurements = {}
    for frame in frame_ids:
        row = rows[frame]
        pair = {}
        for lens in ("cam0", "cam1"):
            image_path = args.dataset / "images" / lens / row["filename"]
            mask_path = args.dataset / "masks" / lens / (Path(row["filename"]).stem + ".png")
            view = measure_view(image_path, mask_path, config)
            view.update(source_frame=frame, time_seconds=row["time_seconds"], split=row["split"])
            pair[lens] = view
        measurements[frame] = pair
    references = {lens: [measurements[frame][lens] for frame in args.reference_frames] for lens in ("cam0", "cam1")}
    decisions = {frame: evaluate_pair(measurements[frame], references, config) for frame in args.frames}
    report = {"schema_version": 1, "config": asdict(config), "measurements": measurements,
              "decisions": decisions, "source_files_modified": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "pairs_measured": len(measurements),
                      "decisions": {frame: value["action"] for frame, value in decisions.items()}}))


if __name__ == "__main__":
    main()
