# STICK_INVESTIGATION_REPORT — `osmo-stick-20261103` reconstruction defects

**Read-only forensic investigation. No training, SfM, rendering or deployment was started.**
Snapshot: 4 November 2026, Asia/Bangkok. Working checkout: `C:/Users/bombe/Documents/Codex/2026-10-27/files-pasted-by-the-user-system`
(`RUN = .local/osmo-stick-20261103`, `EXP = .local/osmo-stick-20261103/optimization-v1`, as defined in `README.md`).

All numbers below were produced by CPU re-analysis of the preserved artifacts. Nothing in `RUN/`, `EXP/`, `work/` or the
checkpoints was modified. New files exist only under `RUN/forensic-20261104/` (analysis scripts + JSON evidence) and this report.

---

## 0. Verdict in one paragraph

The visible defects are **not** a rendering or web-viewer problem, and they are **not** `cam0` drifting relative to `cam1`
(that pair is numerically perfect: baseline `0.019640137757` units with σ = `7.4e-16`, rotation `179.66475°` with σ = `1.2e-12°`).
They are three independently measurable things:

1. **The trainer never densified.** The splat set was truncated to `cap_max = 1,700,000` at *initialisation*
   (from a `3,507,037`-point seed), so `num_added = 0` in all 134 logged training steps of both arms (73 dense + 61 V2), and
   the run stopped at **6,000 of 32,000 iterations (18.75 %)** with refinement still running (window `500 → 24,000`).
   The model is an initial seed polished for ~7.5 epochs, and 76 % of its splats are effectively transparent while 62.5 %
   of the visible ones are thin discs/needles (aspect > 10; smallest axis down to `1.6e-13` units).
2. **The camera trajectory itself is bent.** The whole rig — both lenses together — deviates up to `±0.75` units from its own
   best-fit plane (RMS `0.359`), the single global floor plane sits at `Y = -0.016` while the five production preset cameras sit
   at `Y = 0.297 / 0.311 / 0.768 / 0.968 / 1.199` (**4.0× spread** for one stick held by one operator), and the two visits to the
   same bathroom share **zero** feature tracks and land `1.223` units apart. This is what doubles surfaces and what makes the
   `Hall cam0` frame render bathroom-free hallway geometry instead of the doorway-into-bathroom the source shows.
3. **A single global floor/ceiling plane cannot fit that bent map**, so the occupied-footprint fit keeps only the
   entry → bathroom → exit chain (7.55 units² of evidence) and **1,086 of 3,231 camera centres (33.6 %) fall outside it** —
   reproducing the `66.2 %` gate failure (`66.39 %` on re-run). `occupiedShell = null`, `cutawaySupported = false` is the
   *correct* consequence of that geometry, not a separate bug.

Depth/normal supervision was never even possible: **MoGe-2 maps were never generated** for this capture (`depths/`,
`normals/`, `depths-trusted/` exist nowhere under `RUN`), although the installed trainer can produce them (`spirula geometry`).

---

## 1. Training epoch starvation and config audit (`step-000006000.ckpt`)

### 1.1 Exact dataset and step counts

| Quantity | Dense baseline | Coverage V2 | Source |
|---|---:|---:|---|
| Native timestamps in the capture | 3,428 | 3,428 | `dense/analysis/frame-selection.json` |
| Registered native images in SfM | 6,462 | (same reference) | `dense/sparse/0/images.txt` |
| Virtual 1,200² training faces | **31,240** | **13,390** | trainer log `Cameras:` line |
| Native training views behind those faces | **6,248** | **2,678** | faces ÷ 5 |
| Evaluation faces | **1,070** | **1,070** (identical) | `dense-pinhole-1200`, `appearance-coverage-v2-fixed-reference` |
| Seed points | **3,507,037** | 3,507,037 (same PLY) | log `seed points:` |
| Splats at step 1 | **1,700,000** | **1,700,000** | log, constant to the last line |
| Steps completed | **6,000** / 32,000 | **6,000** / 32,000 | `step-000006000.ckpt`, `status.json` |
| Wall clock | — | **1,298.89 s**, PID 2160, exit 1 after controlled kill | `EXP/appearance-training-v2/status.json` |

Log evidence:

```
logs/recovery1-dense-train.log:   Cameras: 31240 (31240 after splitting), seed points: 3507037 (train_frame_scale=1)
EXP/appearance-training-v2/train.log: Cameras: 13390 (13390 after splitting), seed points: 3507037 (train_frame_scale=1)
step      1/32000 (  0%)  splats 1700000 ... num_added=0        <- already at cap on the very first step
step   6001/32000 ( 18%)  splats 1700000 ... num_added=0        <- last logged line before the kill
```

### 1.2 Batch size (derived, not a flag)

`spirula train` exposes no `--batch-size`; the only batch-related keys are `max_batch_per_epoch`, `max_train_batch_size`
and `split_batch`. `TrainerCore.cpp:1367` computes it:

```cpp
double n_batch = std::max((double)num_train / std::max(cfg.max_batch_per_epoch, 1), 1.0);
int    train_bs = std::max(1, (int)(n_batch + 0.5));
_batches_per_epoch = max(1, (num_train + train_bs - 1) / train_bs);
```

* Dense: `31,240 / 800 = 39.05` → **39 cameras per optimiser step**, 800 steps per epoch.
* V2: `13,390 / 800 = 16.74` → **17 cameras per optimiser step**, 800 steps per epoch.
* `split_batch: true` (one-camera sub-batches inside the step), `max_train_batch_size: -1`.

Render budget actually spent by step 6,000: `6,000 × 17 = 102,000` camera renders for **1,700,000** splats
(≈ 0.06 renders per splat, ≈ 7.6 dataset epochs). That is the "epoch starvation" in one number.

### 1.3 Densification / refinement schedule — position at step 6,000

From `training/stick-dense-1200-rgb-recovery1/config.json` (V2 `selected/config.json` is byte-identical except the four
allowed fields — verified by diff):

```json
"num_iterations": 32000, "steps_per_save": 2000, "cap_max": 1700000,
"refine_every": 100, "refine_start_iter": 500, "refine_stop_iter": 24000, "refine_stop_num_iter": 8000,
"dead_criterion": "either", "dead_after_epochs": 2, "min_opacity": 0.005,
"max_screen_size": 0.1, "max_world_size": 0.12, "growth_factor": 1.05, "max_split_fraction": 0.1,
"opacity_reg": 0.01, "scale_reg": 0.01, "rgb_distortion_reg": 0.05, "distortion_reg_warmup": 6000,
"alpha_reg_weight": 0, "alpha_reg_warmup": 12000,
"use_revised_densification": true, "use_long_axis_split": true,
"sh_degree": 2, "primitive": "mip", "quality": "high",
"progressive_resolution": false, "progressive_splat_budget": false, "train_resolution_divisor": 1
```

* Effective refinement stop = `max(refine_stop_iter, max_steps - refine_stop_num_iter)` = `max(24,000, 32,000 − 8,000)` = **24,000**
  (`engine/EngineConfig.h:294`). At 6,000 the run is **23.4 % into the refinement window** (5,500 of 23,500 steps) and had performed
  `(6,000 − 500)/100 = 55` refine rounds of the 235 planned.
* **`reset_alpha_every` does not exist in this trainer.** A case-insensitive search of `spirula-source/src` for
  `reset_alpha|opacity_reset|alpha_reset|reset_opacity|reset_every|ResetAlpha` returns **0 hits**; `TrainConfig.h` has no such field.
  The opacity cycle is instead `opacity_reg 0.01` (decay power 1) + relocation: a splat unrendered for `dead_after_epochs = 2`
  epochs (2 × 800 = 1,600 steps) is treated as dead and relocated at the next refine (`dead_criterion: "either"`).
  **So at step 6,000 nothing had been reset** — there was no reset to be "just before" or "just after".
* Observed relocation churn per refine event: dense `num_dead` median **15,393**, max **98,563** (step 3,501);
  V2 median **9,860**, max **125,097** (step 3,501). i.e. 0.6 – 7.4 % churn, no growth.

### 1.4 The decisive finding: zero densification

```
dense-recovery1: logged_steps=73  num_added_values={0}  splat_counts_seen={1700000}
v2            : logged_steps=61  num_added_values={0}  splat_counts_seen={1700000}
```

The seed PLY holds `3,507,037` points; initialisation kept only `1,700,000` (= `cap_max`) — **48.5 % of the seed was discarded
before step 1** — and with the cap already saturated the densifier could never add a splat. Every `num_added=0` line is the
trainer being structurally unable to add detail. All adaptation happened through relocation of ~1 % of splats.
`growth_factor 1.05` and `max_split_fraction 0.1` were never exercised.

### 1.5 Feature flags

| Flag | Value | Where |
|---|---|---|
| `--use-camera-optimizer` (pose refinement) | **`0` / disabled** — absent from the V2 argv, `use_camera_optimizer: false` in both configs | `status.json`, `config.json:90` |
| `--use-ppisp` | **`1`** (`ppisp_param_type: no_crf_no_vig`, `ppisp_adagrad_lr 0.1`, `ppisp_lr 0.002 → 2e-05`) | `config.json:191` |
| `--use-bilateral-grid` | **`1`** (`bilagrid_type: ppisp`, `bilagrid_shape [16,16,8]`, `bilagrid_tv_loss_weight 10`, `bilagrid_adagrad_lr 0.04`, `bilagrid_lr 0.002 → 1e-04`) | `config.json:181` |
| `use_bilateral_grid_for_geometry` | `0` | `config.json:187` |
| `load_depths` / `load_normals` | **`0` / `0`**; `depth_supervision_weight 0`, `normal_supervision_weight 0`, `depth_distortion_reg 0`, `normal_distortion_reg 0` | `config.json:27,28,157,158` |
| `floater_suppression` / `distraction_robustness` | `strong` / `mild` | `config.json:147,93` |
| `cache_images`, `view_sampling` | `disk`, `uniform` | `config.json:229,144` |
| `scene_transform` | `train_from_world` = **identity** (scale 1, no rotation, no translation) | `training/.../scene_transform.json` |

Because the scene transform is the identity, **trained-PLY coordinates are the normalised model coordinates** — every pose number
below is directly in the frame the splats live in.

### 1.6 PLY scale/opacity distribution (CPU, NumPy)

Header: `element vertex 1699990`, 41 float properties (SH degree 2 → 24 `f_rest`), 164 B/splat.

| Metric | Coverage V2 6,000 | Dense baseline 6,000 | Sparse 6,000 |
|---|---:|---:|---:|
| Splats | 1,699,990 | 1,699,963 | 1,699,997 |
| `sigmoid(opacity) < 0.1` | **76.18 %** | **79.22 %** | 67.95 % |
| `sigmoid(opacity) < 0.01` | 10.86 % | 10.80 % | 4.77 % |
| `sigmoid(opacity) ≥ 0.5` | **2.30 %** (39,081 splats) | 1.81 % (30,777) | 2.82 % |
| `sigmoid(opacity) ≥ 0.9` | 0.06 % | 0.03 % | 0.09 % |
| Opacity p50 | **0.0387** | 0.0350 | 0.0563 |
| World scale p50 | **0.01555** | 0.01907 | 0.01171 |
| World scale p90 | 0.04697 | 0.05406 | 0.03639 |
| World scale p99 | 0.10107 | 0.10597 | 0.08861 |
| World scale max | 0.26831 | 0.21001 | 0.45397 |
| Aspect ratio (max/min) p50 | **5.48** | 9.90 | 3.14 |
| Aspect p99 | 9.1e9 | 4.3e10 | 180.2 |
| Aspect max | **1.43e11** | 2.02e11 | 7.9e10 |
| Share aspect > 10 | **36.6 %** | 49.8 % | 16.0 % |
| `max_scale / median_scale` (global) | **17.3** | 11.0 | 38.8 |
| `p99_scale / median_scale` | 6.5 | 5.6 | 7.6 |
| Scene span p0.5–p99.5 (X,Y,Z) | (6.03, 2.68, 6.32) | — | — |
| Scene bbox diagonal | 9.138 | 9.271 | 8.990 |

Needle / degeneracy detail (V2):

| Measurement | Value |
|---|---:|
| Smallest axis p1 / p10 / p50 | 1.60e-13 / 4.67e-05 / 2.18e-03 |
| Share with smallest axis < 1e-2 / 1e-3 / 1e-4 | 85.0 % / 33.5 % / 13.1 % |
| Share with smallest axis < 1e-6 / 1e-8 | 4.5 % / 2.8 % |
| Visible splats (α ≥ 0.3): aspect p50, share > 10, share > 100 | 18.7 / **62.5 %** / 27.2 % |
| "Visible needles" (aspect > 20 **and** α ≥ 0.3) | **52,361 (3.08 %)** |
| Splats outside the p1–p99 box | **100,330 (5.90 %)**, median excursion 0.113, max **566.0** units |
| …of those, visible (α ≥ 0.3) / needle (aspect > 20) | 11,016 / 11,585 |
| Longest axis > `max_world_size` 0.12 | 0.30 % |
| `nx,ny,nz` all zero | **100 %** (MIP export drops normals) |

Interpretation: `max_world_size 0.12` caps the *long* axis while nothing floors the *short* axes, so the optimiser can satisfy a
flat-surface residual by flattening a splat to 1e-8 rather than shrinking it — the classic needle. A single such disc is invisible
along its normal (which is what the capture saw) and a bright spike from every other direction, which is exactly the
"porcupine" behaviour when orbiting. Only 2.3 % of the budget (39 k splats) is actually opaque, so the visible surface is
supported by very few primitives; 76 % of the budget is spend on near-transparent filler.

---

## 2. `Hall cam0`, the dining table, and the doubling: rig vs. trajectory

### 2.1 How `dense/sfm-native/sparse/0/` was solved — the rig was rigid

`dense/sfm-native/sparse/0/` is a **two-camera rig model**: `cameras.bin` holds exactly two `OPENCV_FISHEYE` cameras
(3840×3840; fx/fy 1045.61/1049.76 and 1043.93/1041.80; cx/cy unchanged from factory — principal point fixed by
`--no-final-principal-point`; `k1..k4` unchanged — distortion fixed by `--no-refine-extra-params`),
`rigs.txt` holds one rig, and there is **no `frames.bin`** (poses are per-image; the rig relation lives in `rigs.txt`).

```text
# rigs.txt
osmo360ii-native-stick-dense-20261103 cam0 cam0 1 0 0 0 0 0 0 0 0
osmo360ii-native-stick-dense-20261103 cam1 cam0 -0.00292559963668 -0.00219184516565 0.999992319641 -0.00141327333012 0 0 -0.00695846339208 0 0
```

Manifest (`dense/sfm-manifest-native3840.json`): rig `osmo360ii-native-stick-dense-20261103`, kind `dual-fisheye`,
**member cam0 `fixed: true`**, **member cam1 `fixed: false`** (its single `cam_from_rig` was allowed to refine).

Invocation (`dense/analysis/sfm-native-job.json`, exit 0, 8,419 s):
`spirula sfm auto dense/images -o dense/sfm-native --manifest … --masks dense/masks --camera-model opencv-fisheye
--features aliked-n16rot --matcher lightglue --aliked-max-features 4096 --max-image-size 1920 --pairs prefilter
--sequence cam0,cam1 --prefilter-sequential --overlap 8 --quadratic-overlap --prefilter-neighbors 12 --focal-trials 0
--no-refine-extra-params --no-final-principal-point --level ground --audit`.

### 2.2 Is `cam0` drifting relative to `cam1`? No — measured to machine precision

All 3,231 timestamps that registered, both lenses, in `dense/sparse/0/images.txt`:

| Measurement | Value |
|---|---:|
| Registered timestamps (pairs) | **3,231** of 3,428 (94.25 %) |
| `‖C_cam0,t − C_cam1,t‖` mean | **0.019640137757** units |
| … std | **7.45e-16** (coefficient of variation **3.8e-14**) |
| … min / p50 / max | 0.019640137757014 / …017506 / …021205 |
| Relative rotation, p50 / spread | **179.66475°** / **1.7e-06°** (max 2.7e-06°) |
| Independently recomputed σ (this audit) | distance 9.57e-16; rotation 1.20e-12° |
| `registered-rig-closure-audit.json` (anchor maps) | rotation p50–p100 **0.0°**, translation **3.1e-15** units |

**Conclusion:** `cam0` cannot drift relative to `cam1`. Both lenses are one rigid body per timestamp; every pose error is shared
by both lenses. The rig baseline is the factory value (`0.0069584` source units × normalisation scale `2.822482` =
`0.0196401`), i.e. the "fixed:false" refinement on cam1 changed essentially nothing in translation.

The drift that *does* exist is **temporal, of the whole rig** — section 2.3.

### 2.3 The real drift: the trajectory is bent by ±0.75 units

`dense/geometry/normalization.json` (single similarity for the whole scene, both lenses):
`scale 2.8224820122477117`, rotation `[[1,0,0],[0,0,1],[0,-1,0]]` (source z-up → +Y up), `metric_scale_known: false`,
`scale_basis: "Median camera height = 1 arbitrary unit"`, `source_median_camera_height 0.354298`.

| Measurement (cam0, 3,231 poses, normalised = trained frame) | Value (units) |
|---|---:|
| Camera height `Y` p1 / p50 / p99 | 0.2609 / **0.9981** / 1.6511 |
| Camera height min / max / range / IQR | 0.2398 / 1.6725 / **1.4327** / 0.6336 |
| Best-fit plane normal vs +Y | **3.25°** (up axis is not the problem) |
| Residual to that plane: RMS / p1 / p99 / |max| | **0.3592** / −0.749 / +0.583 / **0.778** |
| Path length / median step / max step | 47.244 / 0.01379 / **1.3102** |
| Steps > 5× median / > 20× median | 10 / 2 |
| Missing adjacent registrations / largest gap | 8 / **114 frames** (frame 1846 → 1960: 1.3102 units, **95×** median) |

> One unit is the median camera height ≈ one metre (ceiling `2.06` above floor `−0.016`). A person cannot move a selfie stick
> 0.75 m up and back down repeatedly inside one room in 2-second cycles, so the `±0.75` residual is reconstruction bend, not motion.

Camera height per 250-frame bin (median) — it flips, it does not ramp:

| Frames | 0–249 | 250–499 | 500–749 | 750–999 | 1000–1249 | 1250–1499 | 1500–1749 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Y | 1.077 | **0.310** | 1.024 | 1.295 | 1.322 | 0.751 | 1.082 |

| Frames | 1750–1999 | 2000–2249 | 2250–2499 | 2500–2749 | 2750–2999 | 3000–3249 | 3250–3499 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Y | **1.491** | 1.365 | 0.674 | 0.623 | 0.883 | **1.564** | 1.231 |

Per region (`coverage_rules.regions`, exact frame ranges from `normalization.json`):

| Region | frames | registered | Y p5 / p50 / p95 | centroid Y |
|---|---|---:|---|---:|
| entry (= "hall") | 240–300 | 61 | 0.241 / **0.299** / 0.333 | 0.291 |
| bathroom | 330–600 | 244 | 0.292 / **1.246** / 1.414 | 1.027 |
| exit_first | 660–750 | 86 | 0.373 / 0.454 / 0.798 | 0.500 |
| entry_second | 1440–1530 | 91 | 1.040 / 1.099 / 1.126 | 1.094 |
| bathroom_second | 1560–1710 | 135 | 0.615 / 1.046 / 1.272 | 0.944 |
| exit_second | 1740–1830 | 91 | 1.346 / **1.449** / 1.538 | 1.445 |
| bedroom | 1890–2580 | 621 | 0.568 / 0.814 / 1.489 | 0.951 |
| main_room | 2820–3330 | 511 | 0.324 / 1.234 / **1.655** | 1.096 |

The bend is what the production camera fallback inherited, and it is visible in the shipped file
`EXP/preview-v2-controls-cameras/cameras.json`:

| Preset | frame | camera height Y |
|---|---|---:|
| Hallway | 270 | **0.2965** |
| Main room | 2997 | **0.3108** |
| Second bathroom | 1647 | 0.7682 |
| Bedroom | 2247 | 0.9684 |
| First bathroom | 450 | **1.1989** |

**4.0× height spread for one handheld stick.** The viewer's own `startCamera` and `homeTarget` sit at `Y = 0.3108`, i.e. the
walk starts at knee height in a model whose ceiling is `2.06` above the floor. This is why rotating in place looks acceptable
(the splats around that camera agree with it) but *translating* — orbiting off the capture path — reveals walls/ceilings that
belong to a differently-placed segment.

### 2.4 What actually caused the "Hall cam0 major scene/layout/occlusion mismatch"

The eval view is `EXP/appearance-heldout-comparison-v2/plan.json` view 0:
`slug hall-000269-cam0`, `frame_id 269`, `split eval`, `position [-0.541618, 0.300912, -1.513861]`,
`target [-0.894079, 0.300912, -0.578034]`, 65° vFOV, 1600×1000. (Frame 269 is eval because `frame % 30 == 29`.)

**Test 1 — is the pose a mis-registration?** Fitting each pose against a linear model of its ±6 neighbours:

| | residual of frame 269 | neighbourhood residual p50 | rank of frame 269 |
|---|---:|---:|---:|
| cam0 | **0.00136** | 0.0034 | **2959 / 3231** (i.e. among the 8 % smoothest) |
| cam1 | **0.00131** | 0.0034 | 2993 / 3231 |

The worst local residuals are frames **622–625** (0.151 / 0.149 / 0.147 / 0.145) and **279–280** (0.101 / 0.090).
Frame 269 is *not* an outlier; there is no single-frame mis-registration to fix.

**Test 2 — what does the render actually show?** `three-version-crops/hall-000269-cam0-detail-1.png`
(source | baseline | sparse | coverage-v2) shows the source looking **through a doorway into a tiled bathroom**
(sink/toilet pipe, buckets), while all three models render **a flat wall with a door edge and a blue bag and no bathroom at all**.
The recorded review agrees (`visual-review.json`, crop 16/17):
> "All three renders show a major layout/occlusion mismatch against the source bathroom view."
> "All models show shifted bathroom fixtures/door occlusion relative to source; V2 does not resolve the shared mismatch."

**Conclusion:** the doorway is *closed by displaced wall geometry*. The entry/hall segment sits at `Y ≈ 0.30`
(0.58 units below the trajectory's best-fit plane, `entry` centroid `Y 0.291`) while the bathroom segment sits at `Y ≈ 1.25`.
The two segments' walls occupy overlapping (X,Z) at different heights, so the hall camera's frustum is filled by the *other*
segment's wall. This is a segment-level registration error, not a per-frame one, and it is the same error that produces every
other doubling symptom. It is *not* ordinary blur: since all three arms share it, it is upstream of appearance training.

### 2.5 Multiple passes and the dining-table doubling

* The capture is essentially **one pass plus one loop closure near the start**. For a pose, the nearest pose at least 300 frames
  (10 s) later is `p50 = 1.006`, `p75 = 1.347` units away; only **1.9 %** of poses have such a later pose within 0.12 units, and
  **11.9 %** within 0.30. The only genuine revisit cluster is frames **21–61 ↔ 764–770**, closing at **0.073 – 0.118** units.
  So the model never got a strong second look at any surface except at the start of the walk.
* **The two bathroom visits never close at all** (`normalization.json → repeat_visit_audit → same_bathroom_two_visits`):
  `registered_images_per_visit [488, 270]`, `sparse_points_observed_per_visit [321765, 202008]`,
  `direct_cross_visit_sparse_tracks: 0`, `cross_visit_tracks_with_two_timestamps_in_each_visit: 0`,
  `share_of_smaller_visit_point_set_linked: 0.0`, `camera_centroid_separation 1.349`,
  `closest_cross_visit_camera_distance **1.223**`, height medians `1.246` vs `1.046` (Δ **0.200**).
  A bathroom is ~1.0–1.5 units across, so two visits to the *same* room are placed **about one room-width apart with zero shared
  geometry**. That is the mechanism behind "doubled/ghosted grout" (visible in
  `three-version-crops/second-bathroom-001649-cam0-detail-1.png`, where V2 shows extra faint parallel grout lines and a broken
  corner) — two independently-placed copies of the same tiling.
* For the main room / dining table region (frames 2820–3330) the camera height inside the region spans **0.324 → 1.655**
  (range 1.33 units) — a vertical sweep of a full metre around furniture, so the table's top surface is observed from
  many heights against mutually inconsistent reconstruction positions: thin discs at slightly different depths around the
  tabletop edge, which is exactly how the ghosting and edge streaks appear when viewed from off-path.

---

## 3. Depth/normal supervision and the footprint gate

### 3.1 MoGe-2 priors: never generated, though the tool exists

* `depths/`, `normals/` and `depths-trusted/` do **not exist** anywhere under `RUN` (searched `dense-pinhole-1200/`,
  `EXP/appearance-coverage-v2-fixed-reference/`, `training/`, all of `RUN` at depth ≤ 3). The only `*depth*` directories on disk are
  CMake targets (`optimization-v1/spirula-build/CMakeFiles/missing_depth_supervision.dir`, `scan_depth_test.dir`).
* Training config: `load_depths: false`, `load_normals: false`, `depth_supervision_weight: 0`, `normal_supervision_weight: 0`,
  `depth_distortion_reg: 0`, `normal_distortion_reg: 0`, `median_*` weights all `0`, `supervision_warmup: 0`.
  The dataset directories contain only `images/`, `masks/`, `sparse/` (+ seed) — nothing to load.
* The capability is installed and unused: `spirula geometry` — *"estimate depth and surface normals for a dataset … Normals are
  written to `normals/` and depth to `depths/`, which both dataset readers find by name"*, with MoGe-2 as the default model
  (`--model`, `--num-tokens`, `--max-size 1064`) and Marigold v2 / Metric3D as alternatives under `tools/moge`, `tools/marigold`,
  `tools/metric3d`.

So depth/normal supervision was not "disabled after a failed experiment" — **it was never attempted**, and the resulting model has
no constraint tying splat extent to surface orientation. That is one of the two mechanisms (with the saturated cap) that lets
splats flatten into needles.

### 3.2 The 66.2 % footprint gate, reproduced and explained

`RUN/export-trained-cameras.py::fit_shell` (line 161):

```python
near_fraction = float(np.mean(grid_distance(centres) <= .25))
if near_fraction < .9:
    raise ValueError(f'Only {near_fraction:.1%} of fresh camera centres are within 0.25 units of the occupied footprint')
```

Re-running the real code path (real `occupied_footprint.footprint`, real `fit_shell`) on the exact V2 PLY:

```
ValueError: Only 66.4% of fresh camera centres are within 0.25 units of the occupied footprint
          (recorded run: 66.2 %  — same failure, RNG-free; small delta from centre ordering)
cameras outside: 1,086 / 3,231
distance to footprint grid: p50 0.141, p90 0.650, p99 1.251, max 1.351 units
```

Fitted shell that the gate used:

```
bounds  [-2.4860, -0.2191, -2.8823] .. [3.6094, 2.2428, 3.3451]      span 6.095 x 2.462 x 6.227
floorY  -0.01560     plane Y = -0.02657x + 0.00282z - 0.01750   inliers 392/472   rmse 0.0413
ceilingY 2.06102     plane Y =  0.02253x + 0.00280z + 2.05968   inliers 173/203   rmse 0.0593
footprint grid  cell 0.05, 162 x 165, interior 3,020 cells = 7.55 units^2
evidence        floor 1,046 cells | upperCeiling 419 cells | wall 618 cells
```

Where the rejects are (this is the answer to "why 33.8 % fell outside"):

| Region | cameras | outside | outside % | median distance |
|---|---:|---:|---:|---:|
| entry | 61 | 0 | **0.0 %** | 0.000 |
| bathroom | 244 | 5 | 2.0 % | 0.000 |
| exit_first | 86 | 0 | **0.0 %** | 0.000 |
| entry_second | 91 | 0 | **0.0 %** | 0.000 |
| bathroom_second | 135 | 0 | **0.0 %** | 0.112 |
| exit_second | 91 | 0 | **0.0 %** | 0.000 |
| **bedroom** | 621 | **451** | **72.6 %** | 0.361 |
| **main_room** | 511 | **367** | **71.8 %** | 0.502 |

Per 250-frame bin: 0 % for frames 0–999, then **60.4 %** (1000–1249), 16.2 %, 0 %, 29.2 %, 45.6 %,
**89.6 %** (2250–2499), 61.2 %, 43.6 %, **85.6 %** (3000–3249), 24.7 %.

Trajectory vs. opaque splats (bounding percentiles, as requested):

| Set | count | p1 (x,y,z) | p99 (x,y,z) | min | max |
|---|---:|---|---|---|---|
| opaque splats α ≥ 0.35 | 82,836 (4.87 %) | −2.495, −0.420, −2.897 | 3.605, 2.559, 3.346 | −4.753, −4.174, −5.558 | **15.361**, 6.374, 7.226 |
| α ≥ 0.5 | 39,081 (2.30 %) | −2.479, −0.393, −2.950 | 3.726, 2.615, 3.339 | −4.753, −2.834, −5.558 | 9.467, 6.374, 7.226 |
| cameras | 3,231 | −2.205, 0.261, −2.138 | 2.865, 1.651, 2.804 | −2.256, 0.240, −2.151 | 2.907, 1.672, 2.842 |

**The cameras are *not* outside the splat hull** — 0 of 3,231 lie outside the opaque p1–p99 box. The rejection is not a bounding
problem; it is a **semantic** one. `footprint()` builds the room from opaque *flat* splats within `PLANE_BAND = 0.06` of the two
**single global planes** (`floor` `Y ≈ -0.016`, `upperCeiling` `Y ≈ 2.061`), keeps components above `MIN_AREA 0.5` units², then
trims to floor reachable from the cameras without crossing wall evidence (`WALL_EVIDENCE 0.55` vertical-bin coverage).
Because the bedroom and main-room segments sit at `Y ≈ 0.8` and `Y ≈ 1.2` instead of `Y ≈ 1.0`, **their floors/ceilings are not
within 0.06 of the global planes**, so they contribute no cells, the wall-evidence test never reaches `0.55` there, and the
resulting interior is only the entry → bathroom → exit corridor chain: **7.55 units² of a 38 units² footprint** — which is exactly
the set of regions with 0 % rejects. The gate is therefore faithfully reporting the bend from §2.3.

`occupiedShell = null` / `cutawaySupported = false` and the recorded warning are correct behaviour:

```json
"cutawaySupported": false, "occupiedShell": null,
"qualityWarning": "Fitted shell rejected:only66.2% of camera centres lie within0.25 scene units of footprint, below90% gate. Do not enable fitted cutaway."
```

The fallback (`EXP/preview-v2-controls-cameras/cameras.json`) uses 30,762 scalars = **10,254 framing points**, bounds
`[-2.479, -0.419, -2.878] .. [3.601, 2.566, 3.349]`, `overviewReference` at `Y 8.307` —
i.e. navigation framing only, as documented, and the five presets at the four inconsistent heights of §2.3.

---

## 4. Mask failure scope

`EXP/mask-failure-root-cause/audit.json` — read-only audit, `gpu_used: false`, `mask_corrections_written: false`,
`source_masks_hash_unchanged_after_audit: true`, scope *"Read-only audit of 7 confirmed failures and bounded neighboring
intervals; no source or frozen dataset changed."*

### 4.1 The seven confirmed failures

| # | lens / frame | raw excluded px | raw excluded frac | mirror | final mask SHA-256 |
|---|---|---:|---:|---|---|
| 1 | cam1 / 380 — operator hand/arm | **0** | 0.0000 | – | `8249863c31b3…` |
| 2 | cam1 / 394 — lower-rim operator body/hand/head | **0** | 0.0000 | – | `8249863c31b3…` |
| 3 | cam1 / 416 — lower-rim operator body/hand/head | **0** | 0.0000 | – | `8249863c31b3…` |
| 4 | cam0 / 1650 — foot/trousers near lower rim | **0** | 0.0000 | – | `8249863c31b3…` |
| 5 | cam1 / 1580 — mirror glass beyond polygon | 189,621 | 0.0129 | yes | `06ec36041f2b…` |
| 6 | cam1 / 1697 — upper mirror/doorway/light | 266,724 | 0.0181 | yes | `9fe299e2b9aa…` |
| 7 | cam1 / 1699 — upper mirror/doorway/light | 237,837 | 0.0161 | yes | `68cc5497dc40…` |

The four operator cases have **raw segmentation = 0 px** and share one identical final mask hash — i.e. those masks contain
nothing but the lens FOV circle. `person_manual_correction` is `null` for all seven: no manual polygon was ever applied.
All 21 pinhole-perspective replay checks report `difference_pixels = 0`, so there is **no resize / coordinate / ordinal-mapping
bug**: the pipeline faithfully propagated an *empty* detector output. (Exact internal detector-vs-tracker cause not established.)

### 4.2 How many views remain contaminated

| | cam1 360–435 | cam0 1635–1666 |
|---|---:|---:|
| frames in interval | 76 | 32 |
| frames with **empty** raw mask | **23** (30.26 %) | **13** (40.63 %) |
| …present in the 31,240-face dense baseline | **8** | **12** |
| …selected into V2 | **0** | **0** |
| …present in repair anchor inputs | 6 | 5 |

Explicit scope limits, from the audit itself: *"Zero-output prevalence, not an automatic assertion that every listed frame
visibly contains an operator"*, and *"this audit does not quantify their causal share in model blur or map failure"*.

### 4.3 Census of the V2 mask set (new, this investigation)

`EXP/appearance-coverage-v2-fixed-reference/masks`: **14,460 faces** = **2,892 native views × 5** (2,678 train + 214 eval), all
1,200 × 1,200 (1,440,000 px).

* Per-view exclusion (all faces): min **46.03 %**, p10 48.52 %, p50 **52.43 %**, p90 60.02 %, max **78.08 %** — dominated by the
  fisheye FOV circle, so this number cannot separate operator/mirror exclusion.
* 500-face random sample, with the static FOV mask estimated per face index as *"pixel = 255 in ≥ 90 % of that face index"*:

| Non-FOV excluded fraction | Value |
|---|---:|
| p10 / p50 / p90 / max | 0.00000 / **0.00000** / 0.01752 / **0.25909** |
| faces with < 0.1 % | **77.6 %** |
| faces with < 1 % | 87.0 % |
| faces with > 5 % | 3.6 % |
| faces with > 10 % | 2.6 % |
| mean over sample | 0.77 % |

**Answer to the question as posed:** within the audited evidence, **7 confirmed contaminated views among the 2,678 V2 training
views, all 7 excluded**, plus the two cohorts (23 + 13 empty-mask frames, of which **0** were selected into V2) — so the
*known-contaminated* count inside V2 is **0**. What the evidence does **not** establish is the count outside the audited intervals:
the audit is explicitly bounded, and the census above shows that ~77.6 % of V2 faces carry no content exclusion at all beyond
the FOV circle, so under-detection (not over-exclusion) is the residual risk. Meanwhile the **dense baseline does contain 20 of
those empty-mask frames (8 cam1 + 12 cam0) in its 31,240 faces**, which is one more reason its geometry is not a clean reference.

---

## 5. Defect → cause matrix

| # | Reported symptom | Measured cause | Evidence |
|---|---|---|---|
| 1 | 3D needle / porcupine spikes and wispy ghosting off-path (storage rack/bins, dining table) | `cap_max 1.7M` saturated at init (48.5 % of the 3.5 M seed discarded) → `num_added = 0` in every logged step of both arms → no detail growth; `max_world_size 0.12` caps the long axis while the short axis may decay to 1.6e-13 (33.5 % of splats < 1e-3, 2.8 % < 1e-8); 62.5 % of *visible* splats have aspect > 10; 100,330 splats (5.9 %) sit outside the p1–p99 box, max excursion 566 units; no depth/normal prior at all | §1.4, §1.6, §3.1 |
| 2 | Double-exposed/ghosted geometry (dining table, chairs, bathroom grout) | Trajectory bent ±0.75 units (RMS 0.359) around a single floor plane at Y −0.016; two bathroom visits share **0** tracks and sit 1.223 units apart with ΔY 0.200; only 1.9 % of poses get a ≥10 s revisit within 0.12 units; 197 timestamps (5.75 %) unregistered, largest gap 114 frames = 1.31 units | §2.3, §2.5 |
| 3 | `Hall cam0` major scene/layout/occlusion mismatch | Not a per-frame mis-registration (frame 269 residual 0.0014 u, rank 2959/3231). Region-level: entry Y ≈ 0.30 vs bathroom Y ≈ 1.25 → the doorway is closed by the other segment's wall; all three arms identical | §2.2, §2.4 |
| 4 | Cellular/blotchy texture on flat white walls | 76 % of splats α < 0.1 and only 2.3 % α ≥ 0.5 → a mosaic of near-transparent thin discs for a low-gradient wall; plus a `16×16×8` bilateral grid (`bilagrid_adagrad_lr 0.04`, `bilagrid_lr 0.002 → 1e-4`, `tv_loss_weight 10`) and per-image PPISP still fitting at 18.75 % of schedule — grid cell ≈ 1/16 of frame ≈ the observed patch pitch | §1.4, §1.6, §1.5 |
| 5 | No dollhouse cutaway (`occupiedShell null`, `cutawaySupported false`) | Single global floor/ceiling plane cannot contain a ±0.75-unit bend → bedroom 72.6 % and main_room 71.8 % of cameras fall outside the fitted footprint → 66.39 % < 90 % gate (1,086/3,231). Gate behaved correctly; not bypassed | §3.2 |
| 6 | General softness everywhere (PSNR 23.2 baseline / 22.4 V2 vs source) | 6,000/32,000 steps with LR schedules still near maximum (means_lr 1.6e-4 → 1.6e-6 over 32 k, i.e. ~1.05e-4 at step 6,000); only 0.06 renders/splat; no pose refinement (`use_camera_optimizer 0`) so every pose residual is baked into the splats | §1.2, §1.5 |

---

## 6. What the Architect should set next (parameter level)

Order matters: **geometry before capacity before appearance.** Anything that raises splat count first will densify into the
same bent skeleton and make items 1–2 worse.

1. **Fix the bend (blocking for everything else).**
   * Re-solve the map with the same rigid rig but a stronger loop constraint, or
   * run `spirula geometry <dataset>` on the staged dataset → writes `depths/` + `normals/`, then enable
     `--load-depths 1 --load-normals 1 --depth-supervision-weight 0.05…0.2 --normal-supervision-weight 0.02…0.1`
     with `--supervision-warmup` (start after the current checkpoint step) and `--input-depth-is-ray-depth 1`.
   * Independent check to accept the fix: camera height p5–p95 range < 0.15 units and plane residual RMS < 0.08 (today: 1.14 and 0.359).
2. **Give densification headroom.** `cap_max` from `1,700,000` → **≥ 4,000,000** (or `--progressive-splat-budget 1`), so
   `num_added > 0` is possible. Sanity criterion: `splats` must increase after step 500.
3. **Keep the 32,000 schedule for a true resume.** `--resume <checkpoint-directory>` (not `splat.ply`), new output/log/status dir,
   verify "restored step 6000". Do not edit `num_iterations`; the refinement window `500 → 24,000` must be allowed to finish so the
   model passes through a full densify → prune cycle.
4. **Bound the degenerate axis.** Keep `use_long_axis_split 1`, but reject/relocate splats whose `exp(scale) < 1e-4`
   (today 13.1 % of splats are below that) and consider `max_world_size 0.12 → 0.06` until `num_added` is healthy; only then
   reconsider `opacity_reg 0.01` / `scale_reg 0.01`.
5. **Isolate the blotch cause with one cheap arm at step 6,000** (no new geometry needed): re-render the frozen heldout plan with
   `use_bilateral_grid 0` and with `use_ppisp 0` in separate arms. If the cellular pattern disappears only in the bilagrid-off arm,
   it is grid under-convergence, not sampling; then `bilagrid_tv_loss_weight 10 → 30…50` or `bilagrid_adagrad_lr 0.04 → 0.01`.
6. **Masks:** create a **new versioned** mask dataset (never edit the hardlinked staged files) covering cam1 360–435 and
   cam0 1635–1666 with reviewed full-boundary polygons, then re-select and re-stage. The four `raw = 0` operator frames prove the
   detector output is the failing stage, so a manual pass is the only reliable fix; automatic full-circle masks are not a mask pass.
7. **Cutaway:** do not bypass the 90 % gate and do not invent a footprint. After step 1 succeeds, re-run `export-trained-cameras.py`.
   If a per-room shell is still wanted for a bent-but-accepted map, it needs a **new, versioned** shell module that fits one plane
   per room (the current `occupied_footprint.footprint` assumes one global floor/ceiling pair) plus its own evidence file — the
   viewer's `cutawaySupported` contract must keep reporting `false` until that exists.
8. **Do not** present any of these as fidelity acceptance: the current preview's own `qualityWarning` stays true until the
   geometry checks in (1) pass on the same frozen heldout plan.

---

## 7. Evidence index and reproduction

New analysis artifacts (all written by this investigation, nothing overwritten):

```
RUN/forensic-20261104/
  splat_stats.py          -> splat-stats.json          (Q1 PLY distributions, 3 arms)
  sfm_rig_audit.py        -> sfm-rig-audit.json        (Q2 rig rigidity, revisits)
  pose_diagnostics.py     -> pose-diagnostics.json     + poses-cache.npz (Q2 height/tilt/jumps)
  footprint_gate.py       -> footprint-gate.json       (Q3 gate reproduction + bounds)
  mask_census.py          -> mask-census.json          (Q4 14,460-face census)
```

Reproduce (CPU only, ~6 min total, no GPU):

```powershell
& C:/Python314/python.exe -B .local/osmo-stick-20261103/forensic-20261104/splat_stats.py
& C:/Python314/python.exe -B .local/osmo-stick-20261103/forensic-20261104/sfm_rig_audit.py
& C:/Python314/python.exe -B .local/osmo-stick-20261103/forensic-20261104/pose_diagnostics.py
& C:/Python314/python.exe -B .local/osmo-stick-20261103/forensic-20261104/footprint_gate.py
& C:/Python314/python.exe -B .local/osmo-stick-20261103/forensic-20261104/mask_census.py
```

Inputs read (unmodified): `RUN/training/stick-dense-1200-rgb-recovery1/{config.json,scene_transform.json,step-000006000.ckpt/*}`,
`EXP/appearance-training-v2/{status.json,train.log,selected/*}`, `RUN/logs/recovery1-dense-train.log`,
`RUN/dense/sparse/0/{images.txt,cameras.txt}`, `RUN/dense/sfm-native/sparse/0/{cameras.bin,rigs.txt,gauge.txt}`,
`RUN/dense/geometry/normalization.json`, `RUN/dense/analysis/{sfm-native-job.json,sfm-native-status.json,frame-selection.json}`,
`RUN/dense/sfm-manifest-native3840.json`, `EXP/mask-failure-root-cause/audit.json`,
`EXP/appearance-heldout-comparison-v2/{plan.json,visual-review.json,three-version-crops/*}`, `EXP/registered-rig-closure-audit.json`,
`EXP/preview-v2-controls-cameras/cameras.json`, `EXP/preview-coverage-v2-step6000/metadata.json`,
`work/osmo-parity-20261101/occupied_footprint.py`, `RUN/export-trained-cameras.py`,
`EXP/spirula-source/src/{config/TrainConfig.h,engine/EngineConfig.h,engine/EngineDensify.cpp,app/TrainerCore.cpp}`.

Model identities untouched: V2 PLY `278,799,367` B / 1,699,990 splats; baseline PLY `278,794,939` B / 1,699,963 splats;
SPZ `30,232,945` B (not re-packed).

### Limits of this investigation

* No GPU work, no rendering, no SfM, no training, no file in `RUN/`/`EXP/`/`work/` was modified.
* The footprint gate reproduces at **66.39 %** vs the recorded **66.2 %**; the gap is consistent with camera ordering /
  time-sorted `selected` mapping in the original run and does not change the verdict.
* The 500-face non-FOV mask estimate is a **sample**, labelled as such; the authoritative upper bound on confirmed mask failures
  remains the audit's 7 + the two bounded cohorts.
* Nothing here converts an unresolved defect into an acceptance decision: hall cam0, the bathroom duplication, the bend,
  the needle population, and the failed shell fit all remain open, and the preview must keep reporting
  `cutawaySupported: false`.
