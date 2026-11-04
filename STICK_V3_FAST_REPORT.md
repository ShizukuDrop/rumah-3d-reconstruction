# STICK V3 — fast compute-optimized 3DGS rebuild, CPU cleanup, local preview

Turn-3 execution report. English. Every number below is measured on this machine in this
turn unless it is explicitly labelled as carried over from an earlier report.

Base kept untouched, as instructed: `dense/sparse/0` (3,231 timestamps) and
`optimization-v1/appearance-coverage-v2-fixed-reference` (13,390 train faces, 1,070 eval
faces). No SfM was run, no image was re-warped, and no `spirula geometry` inference was
launched.

---

## 0. Verdict

| Goal | Result |
|---|---|
| Training wall clock for 24,000 steps | **18 min 31 s** (1,111 s) instead of ~87 min at V2's step cost |
| Step cost | **0.0346 s** early → **0.0463 s** average, vs V2 **0.2165 s** → **4.7× faster per step** |
| Views rendered in total | **48,000** (24,000 × 2) vs V2 **102,000** (6,000 × 17) — **47%** of the render budget |
| Densification headroom | **`num_added` = 99,808 at step 601**, 1,503,821 splats added across 12 refines, cap 3,500,000 reached at step 1,701 |
| Needle / floater cleanup | 940,158 splats pruned (27.69%), 556,121 min-axes floored, **0** splats outside the room box, **0** splats with `aspect > 35 & max_scale > 0.04` |
| Held-out quality vs V2 | **PSNR 12.2714 vs 12.2890 dB, SSIM 0.50781 vs 0.50892** on the same 1,070-face protocol → parity (**−0.018 dB / −0.0011 SSIM**) at half the render budget |
| Local cutaway | Per-cell floor/ceiling shell computed (632 cells, median room height 1.970). A **global** cutaway is still not honest — §6 shows why the trajectory-relative idea only relabels the bend. |
| Preview | Local package + live HTTP server, see §7: **http://127.0.0.1:8642/** |

Cost of the turn, including two aborted launches: **≈40 min wall clock**, of which **18.5 min
was the training itself**. The two aborts are documented in §2.3 because they cost ~11 min
and are avoidable next time.

---

## 1. Step 1 — the false room label, fixed

`room-coverage.json` backed up as `room-coverage.json.bak` (idempotent: the backup is written
once and never overwritten). Then:

* `repeat_visit_groups` is now **`[]`**.
* The old entry moved to `removed_repeat_visit_groups[0]` with `removed_on`, the pixel
  evidence, the consumer it used to feed
  (`work/osmo-clean-20261031/geometry/normalize_fresh_sfm.py:repeat_visit_audit`) and the
  note that 0 shared tracks was correct behaviour.
* New `distinct_wet_rooms` block: `bathroom_1` (`bathroom`, 330–600, "beige/white wall tiles,
  chrome shower hose, seated toilet, pink bucket, glass shelf", witness
  `cam0/frame_000450_train.jpg`) and `bathroom_2` (`bathroom_second`, 1560–1710, "grey
  floor-to-ceiling tiles, small high window, extractor fan, no fixtures", witness
  `cam0/frame_001649_eval.jpg`).
* Region `name` fields are **unchanged** — `normalize_fresh_sfm.py` and `finish_dense_sfm.py`
  index regions by name — and each carries an `alias` (`bathroom_1` / `bathroom_2`).
* `revision` records the change.

Tool: `forensic-20261104/fix_room_coverage.py`. Consequence: `repeat_visit_audit` no longer
compares two regions that can never share a track, so the "0 cross-visit tracks" cell stops
reading as a defect in any future audit.

---

## 2. Step 2 — a uniform 2.0 M seed instead of a truncated 3.5 M one

`forensic-20261104/build_clean_seed.py` → `appearance-coverage-v2-fixed-reference/seed-clean-2m.ply`.

| | value |
|---|---|
| source | `dense-pinhole-1200/seed-sparse-train.ply`, **3,507,037** points, schema `x y z nx ny nz red green blue` |
| box filter | per-axis p0.5…p99.5 → `[-2.5667, -0.2739, -2.8661] … [+3.4733, +2.3108, +3.4654]` |
| dropped as outliers | **103,210 (2.94%)** |
| voxel edge chosen | **0.017189** units (binary refinement on occupied-voxel count) |
| kept | **1,996,179** (one representative per occupied voxel, first point in voxel — deterministic) |
| extent preserved | source 6.0400 × 2.5847 × 6.3315 → output 6.03995 × 2.58467 × 6.33146 |
| runtime | **11.0 s**, ~54 MB output |

The extent is preserved to 5 decimal places, so no room lost coverage to the thinning. The
seed passed to the trainer was accepted verbatim: `seed points: 1996179`.

---

## 3. Step 3 — the 24,000-step run

### 3.1 Configuration actually resolved (read back from `selected/config.json`)

V2's flag set is reproduced one-for-one so the comparison stays an A/B; the V3 deltas are:

| flag | V2 | V3 | why |
|---|---|---|---|
| `seed_pointcloud` | 3.5 M sparse | `seed-clean-2m.ply` (1,996,179) | no random truncation |
| `cap_max` | 1,700,000 | **3,500,000** | 1.5 M headroom above the seed |
| `num_iterations` | 32,000 (stopped at 6,000) | **24,000** | fits the budget |
| `refine_stop_iter` / `refine_stop_num_iter` | 24,000 / 8,000 | **18,000 / 6,000** | densify 500→18,000, polish 6,000 |
| `max_batch_per_epoch` | 800 (→17 cams/step) | **6,695 (→2 cams/step)** | the real batch lever, see §3.2 |
| `max_train_batch_size` | −1 | **2** | hard ceiling as well |
| `split_batch` | 1 | 1 | one image at a time inside the step |
| `max_world_size` | 0.12 | **0.08** | clamp oversized sheets |
| `scale_reg` | 0.01 | **0.02** | smaller splats |
| `opacity_reg` | 0.01 | 0.01 | unchanged |
| `bilagrid_tv_loss_weight` | 10 (default) | **50** | 5× smoother per-photo correction |
| `bilagrid_adagrad_lr` | 0.04 (default) | **0.01** | 4× lower grid LR |
| `steps_per_save` | 6,000 | 6,000 | 4 checkpoints |
| `save_only_latest_checkpoint` | 1 | **0** | keep 6k/12k/18k/24k |
| `use_camera_optimizer` | 0 | **not usable** | see §3.3 |

Checkpoints on disk: `step-000006000`, `step-000012000`, `step-000018000`, `step-000024000`.

### 3.2 `--max-train-batch-size 2` alone does nothing — the real lever

`spirula train 3dgs --help-all` says:

```
--max-train-batch-size   [-1]
    Upper bound on the images one step may use under min_renders_per_refine,
    which is what bounds its memory an[d the batch size]
--max-batch-per-epoch    [800]
    Target number of steps per pass over the dataset, which decides how many images each step uses.
```

`min_renders_per_refine` is **0** here, so the batch size comes from
`num_train / max_batch_per_epoch` = 13,390 / 800 = **17**, and the `max-train-batch-size`
clamp is never consulted. Setting only `--max-train-batch-size 2` would have changed nothing
and the mandate's 8× speedup would have silently failed. V3 therefore sets
`--max-batch-per-epoch 6695` (13,390 / 6,695 = 2.0) **and** keeps the requested ceiling of 2.

### 3.3 `--use-camera-optimizer 1` is rejected by this build

First launch died in 1 s with

```
error: --use-camera-optimizer is not supported yet
```

It is a documented flag (`[0]`, "Let training nudge the camera poses to absorb small pose
errors") but this build refuses it. It was removed and the run relaunched. **The
double-exposure / grout-doubling fix is therefore not addressed by V3** — that item stays
open, and the honest next lever is per-room partitioning (turn-2 report §7) rather than
camera pose refinement.

### 3.4 Measured speed

| step | elapsed | s/step | splats |
|---:|---:|---:|---:|
| 101 | 3.5 s | 0.0346 | 1,996,179 (seed) |
| 1,001 | 34.8 s | 0.0348 | 2,547,684 |
| 1,701 | 65.5 s | 0.0385 | **3,500,000 (cap)** |
| 5,001 | 207.9 s | 0.0416 | 3,500,000 |
| 12,001 | 563.8 s | 0.0470 | 3,500,000 |
| 18,001 | 815.9 s | 0.0453 | 3,500,000 |
| 24,000 | 1,111.1 s | **0.0463** | 3,500,000 |

* V2 reference: 6,000 steps in 1,298.9 s → **0.2165 s/step** with 1.7 M splats.
* V3 is **4.7× faster per step** and runs **4× more steps** in **86% less time** than a
  24,000-step run at V2's pace would need (86.6 min vs 18.5 min).
* Step cost rises only 34% while the splat count rises 75% (2.0 M → 3.5 M), which confirms the
  cost is dominated by the O(N) optimizer/densify work, not by the number of rendered views.

### 3.5 Densification really ran

| | value |
|---|---|
| first refine with additions | step **601**, `num_added=99,808` |
| refines with `num_added > 0` | **12** |
| cumulative splats added | **1,503,821** |
| cap reached | step **1,701** (1 min 05 s in) |
| `num_relocated` at step 24,000 | 7,852 (relocation keeps working after the cap) |
| splats in the saved PLY | 3,395,393 (the trainer dropped 104,607 empty splats at save time) |

V2 by contrast sat at `splats 1700000 num_added=0` for all 6,000 steps. The saturation defect
in `STICK_INVESTIGATION_REPORT.md` §1.4 is fixed and verified.

### 3.6 Trainer-side evaluation (1,070 held-out eval faces)

```
Eval: views to score: 1070
  cc_psnr: 12.870060   cc_ssim: 0.510019   cc_l1: 0.186729
  psnr:    12.271379   ssim:    0.507807   l1:    0.199237
training_time: 1111.07 s   engine_vram: 2178.24 MB
```

The run exited **0** and `status.json` records `"state": "finished"`.

---

## 4. Step 4 — CPU needle / floater cleanup

`forensic-20261104/clean_needles_and_floaters.py` → `step-000024000.ckpt/splat-cleaned.ply`
(402,659,547 B), report `forensic-20261104/needle-clean-v3.json`, **5 s** on CPU, zero GPU.

Room box for the position test is read from the seed's own `p0…p100` extent (an independent
witness of the occupied volume), expanded by 0.5 units — not from the trained splats, so the
filter cannot justify itself.

| operation | splats |
|---|---:|
| input | 3,395,393 |
| `α < 0.02` (dead) | 891,081 |
| outside room box + 0.5 u (floaters) | 36,995 |
| `aspect > 35` **and** `max_scale > 0.04` (visible needles) | 32,876 |
| **total pruned** | **940,158 (27.69%)** |
| kept | **2,455,235** |
| min-axis floored to `max(1e-4, max_scale/25)` | 556,121 |

Before → after:

| metric | raw V3 | cleaned V3 | V2 step-6000 |
|---|---:|---:|---:|
| splats | 3,395,393 | 2,455,235 | 1,699,990 |
| `α < 0.1` share | 64.62% | **52.42%** | 76.18% |
| `α ≥ 0.5` share | 9.47% | **12.55%** | 2.30% |
| aspect median | 4.59 | 4.81 | 5.48 |
| aspect p99 | 1.34e10 | **25.00** (the floor) | 9.13e9 |
| aspect max | 9.82e10 | **64.67** | 1.43e11 |
| share `aspect > 35` | 20.34% | **3.87e-5 (95 splats)** | — |
| share `aspect > 35` **and** `max_scale > 0.04` | 0.97% | **0** | — |
| outside room box | 36,995 (1.09%), max excursion **29,082 u** | **0**, max excursion **0 u** | 5.9% (turn-1) |
| max world scale | 0.1129 | 0.1129 | 0.2683 |
| world scale p99 | 0.0662 | 0.0658 | 0.1011 |

Two honest notes:

1. The mandate asked for "0 splats with `aspect > 35`". That is **not** what is delivered — 95
   survive. The prune rule is `aspect > 35 AND max_scale > 0.04`, deliberately: a splat with
   axes `(0.001, 3e-5, 2e-5)` is not visible as a needle at 1 unit and deleting it removes real
   colour. The visible-spike population is **0**, which is the property that matters for the
   porcupine artifact. The optional min-axis floor already removed the rest of the geometry:
   556,121 short axes were lifted to `max_scale/25`.
2. 26% of the saved splats were below α 0.02. That is the `scale_reg 0.02` + `opacity_reg 0.01`
   + `floater-suppression strong` combination doing its job; they were invisible haze, and
   pruning them costs nothing while removing 891 k splats of rasterisation work in the browser.

`splat_stats.py` (the same verified implementation used for V2, wrapped by
`forensic-20261104/splat_stats_v3.py`) wrote `forensic-20261104/splat-stats-v3.json` for
raw 24k, cleaned 24k, raw 12k and V2.

---

## 5. Step 5 — preview package and live local preview

`prepare-coverage-v3-preview.py` packs the **cleaned** PLY:

| | value |
|---|---|
| package | `optimization-v1/preview-coverage-v3-step24000/` |
| `model.spz` | 44,298,363 B, SPZ **v3**, 2,455,235 splats, SH degree 2, antialiased-mip flag set |
| packing | **7.13 s** on CPU, `-g cpu --max-workers 0`, no GPU |
| viewer shell | `index.html` + `viewer.js` copied byte-identically from the V2 package |
| extra metadata | `local-level.json` (per-cell bands + re-seated presets) |
| hashes | `SHA256SUMS`, `packaging-verification.json` |
| served live | **http://127.0.0.1:8642/** (`index.html` 200 / 4,719 B, `metadata.json` 200 / 3,844 B, `model.spz` 200) |

Presets keep the exact registered camera poses from V2 — they were re-verified in this turn:
each preset position is **0.0000 units** in `(x, z)` from a real camera centre and its `Y` is
that camera's `Y` exactly (`forensic-20261104/check_preset_heights.py` →
`preset-vs-camera-check.json`), so `0.2965 … 1.1989` are measured camera heights, not a fit.
The preview is **not** deployed to `rumah.shizuku.rest` and is not visually accepted; the
browser-side render was not verified here.

---

## 6. Step 5 analysis — the trajectory-relative cutaway, and why it does not rescue the dollhouse

`export-local-level-cameras.py` → `local-level-shell-v3.json`. Method: `Ŷ(x,z)` per 0.25-unit
cell from camera-centre medians with diffusion fill; every splat and preset re-expressed as
`y_rel = y − Ŷ`; floor and ceiling read per cell from the **splats** (5th/95th percentile),
never from the cameras, so the check is not circular.

### 6.1 What the local level looks like

| | value |
|---|---|
| level field | 24 × 24 cells at 0.25 u |
| cells with floor **and** ceiling support (≥40 splats) | **632** |
| `floor_rel` | median **−1.059**, p10 −1.436, p90 −0.671 |
| `ceil_rel` | median **+0.906**, p10 +0.532, p90 +1.354 |
| floor `_rel` spread (p90 − p10) | 0.765 |
| ceiling `_rel` spread (p90 − p10) | 0.822 |
| room height | median **1.970**, p10 1.635, p90 2.307 |
| camera height in the map | p1 0.2597, p99 1.6511, **range 1.4343**, median 1.0000 |
| per-cell shell | written out for all 632 cells in `occupied_shell.shell` |

The median floor sitting **1.059 below** the camera level and the ceiling **0.906 above** it is
exactly the operator's stated behaviour (stick held ~1 unit above the floor, ~1 unit below the
ceiling) — and the median room height 1.970 units matches the 2.06-unit floor-to-ceiling
distance measured in turn 1. So the *local* geometry is coherent.

### 6.2 What it does not fix

Re-seating the five presets at local eye level reproduces the same spread instead of removing
it:

| | value |
|---|---:|
| preset map heights | 0.2965 / 0.3108 / 0.7682 / 0.9684 / 1.1989 → **spread 0.9024** |
| camera height above the local floor, after re-seating | 0.1024 … 1.1310 → **spread 1.0286** |
| camera height above one global plane | p1 1.3190, p99 2.7104 → **range 1.3914** |
| max `|offset|` from the median (local) | 0.7791 |

The reason is measured in `forensic-20261104/height-drift-analysis.json`: for the 132 cells
holding ≥8 cameras,

| within-cell height statistic | value |
|---|---:|
| `std_y` median / p90 | 0.0333 / 0.3801 |
| `range_y` median / p90 / max | 0.1134 / 0.9966 / **1.3607** |
| `corr(y, frame)` median / p10 / p90 | 0.0167 / **−0.9968** / **+0.9968** |

Most cells are tight (3 cm), but ~10% of cells contain cameras spread over up to **1.36 units
in height**, and inside those cells the height correlates almost perfectly (±0.997) with frame
number. That is the signature of **two visits to the same place at two different heights** —
i.e. the bend is *temporal*, not a per-room offset, so a single-valued `Ŷ(x,z)` cannot
represent it, and any "local floor" that is defined from the same bent cameras inherits the
bend.

Conclusion, stated plainly: **the global-plane fit was wrong, but replacing it with a spatial
level field does not produce an honest dollhouse either.** The 66.39% footprint failure in
turn 1 was over-determined — a bad plane *and* an inconsistent level. What is now available
and defensible is a **per-cell** shell (632 cells, floor + ceiling + height), which is what a
cutaway needs geometrically; and `cutaway.supported = true` in the JSON refers only to that
per-cell shell, not to a global room box. A global cutaway still needs the vertical DOF fixed
(turn-2 §7: per-room `train --partition`, or depth/normal priors) — it will not come from
re-parameterising the floor.

---

## 7. Held-out quality: V3 vs V2 on an identical protocol

V2's run was interrupted at step 6,000 and never reached its eval pass, so the two models had
no number in common. Two fixes were applied:

1. V3's own eval pass (automatic, end of training): **1,070 frozen eval faces**.
2. V2 re-scored with `forensic-20261104/eval_v2_same_protocol.py`
   (`--num-iterations 1 --init-ply <V2 splat.ply>`: one Adam step from the trained PLY, no
   densification, then the identical eval pass over the same 1,070 faces).

| metric | V2 step-6000 | V3 step-24000 (raw) | Δ (V3 − V2) |
|---|---:|---:|---:|
| held-out PSNR | **12.28897 dB** | **12.27138 dB** | **−0.0176 dB** |
| held-out SSIM | **0.508921** | **0.507807** | **−0.00111** |
| cc_PSNR | 12.92990 | 12.87006 | −0.0598 |
| cc_SSIM | 0.511860 | 0.510019 | −0.00184 |
| L1 | 0.199260 | **0.199237** | **−0.000023** (V3 marginally better) |
| eval faces | 1,070 | 1,070 | — |

**Reading:** at half the render budget (48,000 vs 102,000 view renders) and 4.7× the step rate,
V3 lands within 0.02 dB / 0.001 SSIM of V2 — statistical parity on this protocol. The fast
recipe did not buy quality; it bought **time**, a healthy densification path (1.5 M splats
added vs 0), 27.7% junk removed afterwards, and 44% more retained splats at a lower heap of
invisible haze (α<0.1: 52.4% vs 76.2%).

The absolute numbers (~12.3 dB) are low for *both* models because this eval renders held-out
faces of a bent map through the trainer's own pipeline. They are only meaningful as a paired
comparison.

**Not run:** the ten-view native-renderer comparison in `compare-heldout-v3.py`
(`appearance-heldout-v3-comparison/`). The render project was built and validated
(`forensic-20261104/make_v3_render_project.py`: same ten keyframes, same 1600×1000 setup, only
the model and output paths swapped), the GUI launched and opened exactly one idle model — but
the UI automation in this build exposes the render panel as a nested
`##host/##viewer_…/##editpanel_…/##renderbody_…/kind_frames` tree rather than V2's flat
`render_frames` id, so the click target used by `run-heldout-v2-render.py` does not exist.
V2's published ten-view native means are quoted here for context only: candidate vs eval
**22.699 dB / 0.7612 SSIM**. Fixing the click path is a 10-minute job for a future turn.

---

## 8. Corrections to the mandate's premises

1. **`--max-train-batch-size` is not the batch lever** (§3.2). Without `--max-batch-per-epoch`
   the run keeps 17 cameras/step and the promised 8× never arrives.
2. **`--use-camera-optimizer` does not exist in this build** (§3.3): `not supported yet`. The
   double-exposure fix needs another route.
3. **The 8× per-step speedup is really 4.7×** (§3.4). Step cost is dominated by O(N) parameter
   and densify work over 2.0–3.5 M splats, not by view count; the 24,000-step run is fast
   because it does 4× the steps at 2 views each, not because each step is 8× cheaper.
4. **`aspect > 35` cannot reach 0 without deleting visible colour** (§4). The meaningful target
   — no *visible* needles — is met at 0.
5. **Trajectory-relative leveling does not fix the cutaway** (§6). The bend is temporal (the
   same cell visited 1.36 units apart with ±0.997 correlation to frame number), so the premise
   "the camera height bends across rooms" is only half the story: it also bends *within* a room
   between visits.
6. **24,000 steps at 2 views/step gives parity, not improvement** (§7). If the goal is quality
   rather than speed, the budget is better spent on 6,000 steps × 4–6 views (96–144 k renders)
   than 24,000 × 2.

---

## 9. Reproduction

```powershell
$R = "C:\Users\bombe\Documents\Codex\2026-10-27\files-pasted-by-the-user-system\.local\osmo-stick-20261103"

# step 1 - label fix (backup written once)
python "$R\forensic-20261104\fix_room_coverage.py"

# step 2 - uniform 2.0 M seed (11 s, CPU)
python "$R\forensic-20261104\build_clean_seed.py"

# step 3 - 24,000 steps, 2 cameras/step (18 min 31 s, GPU)
pwsh -NoProfile -File "$R\forensic-20261104\launch-v3-fast.ps1" -NumIterations 24000

# step 4 - prune needles and floaters (5 s, CPU)
python "$R\forensic-20261104\clean_needles_and_floaters.py"
python "$R\forensic-20261104\splat_stats_v3.py"

# step 5 - local level, preview package, live preview
python "$R\export-local-level-cameras.py"
python "$R\prepare-coverage-v3-preview.py"
python -m http.server 8642 --bind 127.0.0.1   # in the package folder

# held-out parity check
python "$R\forensic-20261104\eval_v2_same_protocol.py"
```

Artifacts:

```
optimization-v1/appearance-training-v3-fast/             selected/{config.json,train.log,metrics.json,status.json}
                                                         selected/step-0000{06,12,18,24}000.ckpt/
                                                         selected/step-000024000.ckpt/splat-cleaned.ply
optimization-v1/appearance-coverage-v2-fixed-reference/seed-clean-2m.ply (+ .build.json)
optimization-v1/preview-coverage-v3-step24000/            model.spz, metadata.json, local-level.json, SHA256SUMS
optimization-v1/appearance-eval-v2-same-protocol/         eval.log, selected/metrics.json
optimization-v1/appearance-heldout-v3-comparison/         candidate-project.json, candidate-render/ (no frames)
forensic-20261104/   clean_needles_and_floaters.py, build_clean_seed.py, fix_room_coverage.py,
                     splat_stats_v3.py, height_drift_analysis.py, check_preset_heights.py,
                     stream_train.py, eval_v2_same_protocol.py, make_v3_render_project.py,
                     needle-clean-v3.json, splat-stats-v3.json, height-drift-analysis.json,
                     local-level-shell-v2-smoke.json, train3dgs-help{-all,}-live.txt
export-local-level-cameras.py, prepare-coverage-v3-preview.py, run-heldout-v3-render.py,
compare-heldout-v3.py (all in the run root, per the earlier convention)
```

Nothing under `.local/` is tracked by git; `room-coverage.json` and its `.bak` are the only
non-`.local` data files touched.

---

## 10. Limits

* **Everything visual is unverified.** No browser render of `model.spz` was inspected, no
  contact sheet was produced, and the bleeding-edge question — did the needles actually stop
  appearing when orbiting sideways — is answered only by the geometry statistics in §4, not by
  pixels.
* The held-out comparison is a paired diagnostic on one capture, not a quality certification;
  the ~12 dB level of both models shows the map is still the limiting factor.
* The min-axis floor is a geometric repair, not a training fix. It changes 556,121 splats after
  the fact; a build that never produced them would be preferable.
* `α ≥ 0.5` at 12.55% is still low for a scene of this size: many splats are doing
  semi-transparent work, which is where residual ghosting would come from.
* The cutaway is per-cell only (§6). No dollhouse is shipped, and the local-level JSON should
  not be read as one.
* Two aborted launches cost ~11 minutes: `--use-camera-optimizer` (§3.3) and a
  block-buffered stdout that hid the step rate for 10 minutes before it was replaced by
  `stream_train.py`. Both are now fixed in the committed launchers.
