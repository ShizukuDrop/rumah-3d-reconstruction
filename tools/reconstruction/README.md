# Paired-camera reconstruction experiments

These tools implement the Osmo Stick optimization study without modifying its
source images, original feature cache, saved 6,000-step checkpoint, or production
viewer. Derived datasets, logs and models belong under `.local/` and stay out of
Git. The full 32,000-step job remains stopped until explicitly resumed.

## What each stage proves

| Stage | Implementation | Evidence and limits |
|---|---|---|
| Paired capture index | `capture.py` | Same source-frame ID/time/split for both lenses; checks image and mask paths. Uses the existing source synchronization audit. |
| Per-lens quality | `quality.py`, `scan_quality.py`, `classify_quality.py` | Masked edge support, noise, comparable neighborhoods, common spatial regions and tracked corresponding edges. Confirmed blur in either lens excludes the alignment pair. Uncertain views remain explicitly uncertain. |
| Prospective motion | `motion.py` | Both-lens masked optical flow, calibrated KB4 bearing inversion and rotation-compensated residuals. Handles backward-facing fisheye rays within the monotonic calibration domain. Residuals are a parallax proxy, not surveyed translation. No completed dense reconstruction is needed. |
| Alignment anchors | `selection.py` | Quality, parallax, orientation change, track survival and maximum-gap checks. Neither coverage rules nor frame-count targets can restore a confirmed blurry pair. Explicit experimental use of unknown quality prevents acceptance. |
| Appearance views | `training_views.py` | Independent per-lens appearance/visibility/direction selection and coverage. Eval timestamps and confirmed blur are excluded. Every retained view still needs a valid pose; unknown quality is review-only. |
| Coverage-controlled training comparison | `coverage_appearance.py`, `stage_training_ablation.py` | Preserve per-lens coverage in difficult intervals. Review overrides name one native view and bind the inspected photo and mask hashes. The fixed-reference comparison reuses the same poses, seed, and evaluation views to isolate the training input change. |
| Useful connections | `pair_graph.py` | Local, spaced, revisit and protected transition connections; actual image matches are distinct from logical rig constraints. Reports missing verified edges and disconnected components. |
| Revisit proposals | `descriptor_retrieval.py` | Mean-pools the same original ALIKED descriptors and proposes bounded same-lens revisits. This is a retrieval heuristic; only subsequent geometric verification can establish overlap. No completed poses or old matches are needed. |
| Isolated anchor workspace | `stage_anchor_dataset.py` | Copies feature records, links/copies image and mask inputs, preserves exact calibrated camera/rig metadata and records source identities. Requires `--no-compact-unused-features` for later original-feature-index localization. |
| Existing match cache | `match_cache.py` | Streams VKMT v4 without inventing image/feature IDs. Preserves the full image table and camera tail. A cached graph experiment does not measure fresh matching speed. |
| Targeted repair | `targeted_repair.py`, `merge_match_cache.py` | Add support only around failed intervals. A delta can be merged without repeating old matches when image tables, feature hashes, calibration bytes, and pair identities agree. New verified edges still require a room continuity check after mapping. |
| Explicit native matching | `patches/` | Pinned Spirula source extension accepts a pair-list graph with its content hash in the stage signature. Original runtime is retained. |
| Matcher comparison | `matcher_benchmark.py` | Identical cached ALIKED coordinates/descriptors, fixed/adaptive 4,096-feature arms and a separate 2,048-feature arm. CPU/GPU timing, warmup, verification and load cost are distinguished. |
| Additional-view pose | `localization.py` | Fixed-map generalized-camera localization with input identities and fixed rig calibration. Output poses require geometry gates. Synthetic API success alone does not prove capture quality. |
| Fresh query matching | `fresh_query_matching.py` | Matches only selected queries to registered anchors using original feature rows. Resumable records preserve match identities, and the raw cache must pass through fixed-map pose validation. |
| Localization input adapter | `prepare_localization.py` | Resolves fresh COLMAP image IDs by exact names, checks original feature-row coordinates, rejects ambiguous point identities and obtains 3D points and refined rig calibration only from the fresh anchor model. Cached 2D correspondences are explicitly distinguished from fresh matching. |
| Batch pose estimation | `localize_batch.py` | Records per-query progress and request-bound results; reports accepted/rejected train/eval views and room coverage. A previously completed result is reusable only for its original request. |
| Pose export | `export_localized_poses.py` | Exports accepted additional poses with untriangulated observations and keeps fresh anchor observations unchanged. The legacy COLMAP export omits stale rig/frame files. A separate whitelist controls training eligibility; an anchor pose alone does not authorize training on that image. |
| Whitelisted training conversion | `work/osmo-clean-20261031/build_explicit_pinhole.py` | Supply both export whitelists and explicit native image, mask, and selection paths. Conversion preserves fresh poses, and unlisted anchors do not enter training. A pose-only view supplies no seed track. |
| Pose comparison | `geometry_compare.py` | Reads camera headers without loading a dense point cloud. Reports complete paired registration per room and similarity-aligned differences from the reference. The old model is a comparison, never ground truth, and evaluation views do not fit the similarity. |
| Post-training splat cleanup | `clean_true_1d_needles.py`, `clean_trajectory_and_fog.py`, `clean_v3e_edgeon_and_seed.py` | CPU-only PLY surgery on trained splats: dead/needle pruning keyed on sorted-axis ratios (`s3/s2`), camera-trajectory free-space tube carving against registered centres, translucent-fog pruning, seed-support filtering against triangulated points, and edge-on razor-disk clamps. Each step prints disjoint rule counts and never inflates `s1` beyond numeric floors. Run against a copied PLY; originals stay untouched. The run root defaults to `.local/osmo-stick-20261103` and can be redirected with `STICK_RUN_ROOT`. |
| Masked held-out scoring | `run_masked_eval_passes.py`, `score_masked_eval.py` | Re-renders the eval split for one Adam step with `--save-eval-images 1`, recovers the render/ground-truth mapping by 16×16 thumbnails, and scores PSNR/SSIM strictly inside the operator keep-masks — the honest alternative to the fisheye-padding-dominant whole-frame score. |
| Uniform seed rebuild | `build_clean_seed.py` | Room-box filtered, voxel-uniform ~2.0 M seed so the trainer's cap cannot randomly truncate half the tracks. |

## Run order

From the repository root, use an environment containing NumPy and OpenCV. The
local benchmark environment additionally contains pinned LightGlue, Torch and
PyCOLMAP. The individual modules expose `--help`.

1. Run `python -m tools.reconstruction.scan_quality --dataset DATASET --output SCAN --workers 4`.
2. Inspect native images and compare the metric's suspected failures against
   nearby clear views. Save the evidence and experimental thresholds. Synthetic
   blur tests are useful but do not replace this inspection.
3. Run `classify_quality` with the saved quality configuration. Use clear
   controls, actual-negative examples and any actual-positive examples. Do not
   label a threshold calibrated merely because it produces the desired count.
4. Run `selection` with the scan, classification, explicit coverage intervals
   and configuration. Review anchor coverage and the separate appearance-view
   manifest. A selected uncertain view is not automatically approved.
5. Generate and inspect the pair graph. Run a cached-edge geometry ablation
   separately from a timed, freshly matched experiment. Preserve feature-row
   identity and disable native feature compaction when later localization needs
   the original indices (`--no-compact-unused-features`). The native `auto`
   command accepts the exact camera/rig manifest; a standalone `match` smoke
   test without that manifest does not establish calibrated production parity.
6. Reconstruct anchors, localize useful additional views and audit every room
   connection. Promote failed/new-geometry intervals for local graph expansion.
7. Compare matcher backends on the same pairs without competing GPU jobs.
8. After the reduced graph is measured, evaluate alternative solvers on the same
   inputs and calibration. Camera-model compatibility is a prerequisite.
9. Compare source images, training projections, raw model, packed model and the
   actual viewer. Include all rooms, both lenses, fixed detail crops, translated
   viewpoints and dollhouse controls. Missing required views are failures.

## Evaluation rules

- Count coverage against the entire original clip, not only selected frames.
- Preserve original train/eval ownership through every derived manifest.
- The existing every-30th-frame split measures same-video interpolation. It is
  not an independent capture and does not prove unfamiliar-view quality. Use
  the same evaluation set for both arms; add a separately labeled blocked-time
  comparison when both training arms exclude those blocks.
- Record selector, feature, matching, mapping, localization, conversion and
  training times. Report reused work separately. Do not compare a warm cache
  against a cold run as an end-to-end speedup.
- Matching success, reprojection statistics, training loss, PSNR and file size
  cannot independently certify usable appearance. Keep per-room/worst-view
  evidence and inspect native-resolution imagery.
- Report the largest gap between registered timestamps per room alongside the
  registered count. A model can register more images while leaving a longer gap.
- Review masks separately from blur. A sharp view can still retain the operator
  or mirror reflections. Record mask failures separately from motion blur.
- A saved model is a benchmark input. Do not publish an optimized replacement
  until the exact model, packed representation and viewer are checked.

## Tests

`python -m unittest discover -s tools/reconstruction -t .` runs the focused
regressions. Tests requiring PyCOLMAP are explicitly skipped when unavailable;
run them in the benchmark environment to exercise the actual pose solver.

The relevant upstream implementations are pinned to
[Spirula v2026.10.30](https://github.com/harry7557558/spirula-studio/tree/v2026.10.30),
with [LightGlue](https://github.com/cvg/LightGlue) and
[PyCOLMAP's generalized pose API](https://colmap.github.io/pycolmap/pycolmap.html#pycolmap.estimate_and_refine_generalized_absolute_pose)
recorded by each experiment. Build and benchmark artifacts include their exact
versions and hashes.
