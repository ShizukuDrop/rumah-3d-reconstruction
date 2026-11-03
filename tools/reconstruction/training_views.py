"""Choose appearance views independently from the camera alignment anchors.

Selection only produces candidates. An eligible candidate must still pass pose
localization before entering training, and a review candidate requires explicit
quality review as well. Evaluation timestamps are always excluded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TrainingViewConfig:
    max_gap_seconds: float = 0.5
    appearance_luma_difference: float = 0.06
    appearance_edge_difference: float = 0.12
    newly_visible_fraction: float = 0.08
    min_common_cells: int = 24
    min_new_visible_cells: int = 6
    direction_change_degrees: float = 15.0
    direction_bin_degrees: float = 45.0
    sharper_width_ratio: float = 1.30
    comparison_history: int = 12
    minimum_views_per_region_lens: int = 1

    def __post_init__(self) -> None:
        if self.max_gap_seconds <= 0 or self.comparison_history < 1:
            raise ValueError("Positive maximum gap and comparison history are required")
        if self.direction_bin_degrees <= 0 or self.direction_bin_degrees > 180:
            raise ValueError("Direction bin must be in (0, 180] degrees")
        if self.minimum_views_per_region_lens < 1:
            raise ValueError("Coverage requires at least one view per region and lens")


def _frame_value(values: dict, frame_id: int) -> dict:
    try:
        return values[frame_id]
    except KeyError:
        return values[str(frame_id)]


def _direction(frame: dict, lens: str) -> np.ndarray | None:
    directions = frame.get("view_directions", {})
    value = directions.get(lens)
    if value is None:
        return None
    direction = np.asarray(value, dtype=float)
    if direction.shape != (3,) or not np.isfinite(direction).all() or np.linalg.norm(direction) < 1e-8:
        raise ValueError("Optional view directions must be finite nonzero 3D vectors")
    return direction / np.linalg.norm(direction)


def _direction_bin(direction: np.ndarray | None, config: TrainingViewConfig) -> str | None:
    if direction is None:
        return None
    azimuth = math.degrees(math.atan2(direction[0], direction[2])) % 360
    elevation = math.degrees(math.asin(float(np.clip(direction[1], -1, 1))))
    return f"az{int(azimuth // config.direction_bin_degrees)}:el{int((elevation + 90) // config.direction_bin_degrees)}"


def compare_appearance(current: dict, previous: dict,
                       config: TrainingViewConfig = TrainingViewConfig()) -> dict:
    """Compare masked spatial content. Global exposure shifts add no novelty."""
    a, b = current.get("signature"), previous.get("signature")
    if not a or not b:
        return {"measured": False, "novel": True, "reason": "missing_appearance_signature"}
    av, bv = np.asarray(a["valid"]) > 0.8, np.asarray(b["valid"]) > 0.8
    if av.shape != bv.shape or av.ndim != 1:
        raise ValueError("Appearance signatures must use the same spatial grid")
    common, newly_visible = av & bv, av & ~bv
    new_cells = int(np.count_nonzero(newly_visible))
    new_fraction = new_cells / max(int(np.count_nonzero(av)), 1)
    new_coverage = new_cells >= config.min_new_visible_cells and new_fraction >= config.newly_visible_fraction
    if np.count_nonzero(common) < config.min_common_cells:
        return {"measured": False, "novel": True, "reason": "insufficient_common_visible_cells",
                "new_visible_cells": new_cells, "new_visible_fraction": new_fraction}
    ca, cb = np.asarray(a["luma"])[common], np.asarray(b["luma"])[common]
    differences = ca - cb
    luma_difference = float(np.mean(np.abs(differences - np.median(differences))) / 255)
    ea, eb = np.asarray(a["edge"])[common], np.asarray(b["edge"])[common]
    norm = np.linalg.norm(ea) * np.linalg.norm(eb)
    edge_difference = float(1 - np.clip(np.dot(ea, eb) / norm, 0, 1)) if norm > 1e-8 else 0.0
    novel = (new_coverage or luma_difference >= config.appearance_luma_difference
             or edge_difference >= config.appearance_edge_difference)
    reasons = []
    if new_coverage:
        reasons.append("new_visible_content")
    if luma_difference >= config.appearance_luma_difference:
        reasons.append("spatial_appearance_change")
    if edge_difference >= config.appearance_edge_difference:
        reasons.append("new_texture_layout")
    return {"measured": True, "novel": novel, "reasons": reasons,
            "common_cells": int(np.count_nonzero(common)), "luma_difference": luma_difference,
            "edge_difference": edge_difference, "new_visible_cells": new_cells,
            "new_visible_fraction": new_fraction}


def _quality_status(decision: dict) -> tuple[str, str]:
    if decision.get("verdict") == "blur" and decision.get("confirmed"):
        return "excluded", "confirmed_blur"
    if (decision.get("verdict") == "sharp" and decision.get("confirmed")
            and decision.get("training_eligible")):
        return "eligible_pending_pose", "quality_passed"
    return "review_required", "quality_review_required"


def _coverage(views: list[dict], regions: tuple | list, config: TrainingViewConfig) -> tuple[list, list]:
    reports, gaps = [], []
    scopes = list(regions) or [{"name": "capture", "source_frame_min": min(v["frame_id"] for v in views),
                               "source_frame_max": max(v["frame_id"] for v in views)}]
    for region in scopes:
        minimum = region.get("minimum_training_views_per_lens", config.minimum_views_per_region_lens)
        for lens in ("cam0", "cam1"):
            available = [v for v in views if v["lens"] == lens and v["split"] == "train"
                         and region["source_frame_min"] <= v["frame_id"] <= region["source_frame_max"]]
            eligible = [v for v in available if v["selected"] and v["status"] == "eligible_pending_pose"]
            review = [v for v in available if v["selected"] and v["status"] == "review_required"]
            reports.append({"region": region["name"], "lens": lens,
                            "eligible_view_count": len(eligible), "review_view_count": len(review),
                            "minimum_required": minimum, "quality_coverage_passed": len(eligible) >= minimum,
                            "direction_bins": sorted({v["direction_bin"] for v in eligible if v["direction_bin"] is not None}),
                            "pose_coverage_verified": False})
            if not available:
                continue
            times = [available[0]["time_seconds"]] + [v["time_seconds"] for v in eligible] + [available[-1]["time_seconds"]]
            for start, end in zip(times, times[1:]):
                if end - start > config.max_gap_seconds + 1e-6:
                    gaps.append({"region": region["name"], "lens": lens, "from_seconds": start,
                                 "to_seconds": end, "seconds": end - start,
                                 "reason": "no_quality_approved_view_within_gap"})
    return reports, gaps


def select_training_views(capture: dict, quality_decisions: dict, measurements: dict,
                          config: TrainingViewConfig = TrainingViewConfig(),
                          regions: tuple | list = ()) -> dict[str, Any]:
    """Select appearance candidates without consulting alignment anchor flags.

    Optional capture frame ``view_directions`` values must be world-space unit
    directions (one per lens). Absent orientation is reported as unavailable.
    ``measurements[id]`` may contain the cam0/cam1 dict directly or under views.
    """
    frames = sorted(capture["frames"], key=lambda row: (row["time_seconds"], row["id"]))
    if not frames or len({frame["id"] for frame in frames}) != len(frames):
        raise ValueError("Capture must contain unique frame identifiers")
    history = {"cam0": [], "cam1": []}
    last_quality_approved = {}
    seen_directions = set()
    records = []
    for frame in frames:
        if frame["split"] not in ("train", "eval") or not math.isfinite(frame["time_seconds"]):
            raise ValueError("Capture has an invalid split or timestamp")
        quality = _frame_value(quality_decisions, frame["id"])["views"]
        measured = _frame_value(measurements, frame["id"])
        measured = measured.get("views", measured)
        memberships = [region["name"] for region in regions
                       if region["source_frame_min"] <= frame["id"] <= region["source_frame_max"]]
        scope = tuple(memberships) or ("capture",)
        for lens in ("cam0", "cam1"):
            direction = _direction(frame, lens)
            bucket = _direction_bin(direction, config)
            status, quality_reason = _quality_status(quality[lens])
            row = {"frame_id": frame["id"], "time_seconds": frame["time_seconds"],
                   "lens": lens, "split": frame["split"], "image": frame["images"][lens],
                   "mask": frame.get("masks", {}).get(lens), "regions": memberships,
                   "direction_bin": bucket, "direction_available": direction is not None,
                   "selected": False, "status": status, "reasons": [quality_reason],
                   "pose_verified": False, "ready_for_training": False}
            if frame["split"] == "eval":
                row.update(status="excluded", reasons=["held_out_timestamp"])
                records.append(row)
                continue
            if status == "excluded":
                records.append(row)
                continue
            # Unreviewed candidates cannot suppress a subsequently clear view.
            previous = [item for item in history[lens] if item["scope"] == scope
                        and (status == "review_required" or item["status"] == "eligible_pending_pose")]
            previous = previous[-config.comparison_history:]
            novelty_reasons, comparisons = [], []
            if not previous:
                novelty_reasons.append("first_view_in_region")
            else:
                comparisons = [compare_appearance(measured[lens], item["measurement"], config) for item in previous]
                if all(item["novel"] for item in comparisons):
                    novelty_reasons.append("appearance_not_covered_by_retained_views")
                sharp_width = measured[lens].get("edge_width_native_px")
                comparable = [item for item, comparison in zip(previous, comparisons) if comparison["measured"] and not comparison["novel"]]
                if sharp_width and comparable and all(
                    item["measurement"].get("edge_width_native_px") is not None
                    and item["measurement"]["edge_width_native_px"] >= config.sharper_width_ratio * sharp_width
                    for item in comparable
                ):
                    novelty_reasons.append("sharper_view_of_existing_content")
            if bucket is not None and (lens, scope, bucket, status) not in seen_directions:
                novelty_reasons.append("new_viewing_direction_bin")
            oriented = [item["direction"] for item in previous if item["direction"] is not None]
            if direction is not None and oriented:
                angles = [math.degrees(math.acos(float(np.clip(np.dot(direction, other), -1, 1)))) for other in oriented]
                if min(angles) >= config.direction_change_degrees:
                    novelty_reasons.append("viewing_direction_change")
                row["nearest_retained_direction_degrees"] = min(angles)
            last = last_quality_approved.get((lens, scope))
            if status == "review_required":
                last = previous[-1]["time_seconds"] if previous else None
            if last is not None and frame["time_seconds"] - last >= config.max_gap_seconds:
                novelty_reasons.append("maximum_appearance_gap")
            row["appearance_comparisons"] = comparisons
            if novelty_reasons:
                row["selected"] = True
                row["reasons"].extend(novelty_reasons)
                history[lens].append({"scope": scope, "status": status, "direction": direction,
                                      "measurement": measured[lens], "time_seconds": frame["time_seconds"]})
                seen_directions.add((lens, scope, bucket, status))
                if status == "eligible_pending_pose":
                    last_quality_approved[lens, scope] = frame["time_seconds"]
            else:
                row.update(status="excluded", reasons=row["reasons"] + ["appearance_already_covered"])
            records.append(row)
    coverage, gaps = _coverage(records, regions, config)
    eligible = sum(row["selected"] and row["status"] == "eligible_pending_pose" for row in records)
    review = sum(row["selected"] and row["status"] == "review_required" for row in records)
    return {"schema_version": 1, "source_selection_sha256": capture.get("source_selection_sha256"),
            "configuration": asdict(config), "views": records, "coverage": coverage,
            "unresolved_gaps": gaps, "eligible_view_count": eligible, "review_view_count": review,
            "heldout_view_count": sum(row["split"] == "eval" for row in records),
            "quality_coverage_passed": bool(eligible) and all(row["quality_coverage_passed"] for row in coverage) and not gaps,
            "appearance_acceptance_passed": False, "pose_validation_required": True,
            "source_images_modified": False, "alignment_anchor_membership_used": False}
