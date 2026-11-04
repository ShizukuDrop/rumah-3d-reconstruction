# STICK V3 — visual verification, masked evaluation, and the 1D temporal bend

Turn-4 report. English. No training was started, as instructed: every number here comes from
headless-browser captures, CPU geometry work, or one-step eval passes that only render.

---

## 0. Verdict

| Question | Answer |
|---|---|
| Do the V3 screenshots exist and show the reported artifacts? | **Yes** — 9 views × 2 models in `forensic-20261104/v3-browser-renders/`, contact sheet + zoom sheet included. |
| Did the V3 rebuild fix double exposure and wall blotches? | **Yes, visibly.** Drawer tower edges and the tiled bathroom wall are markedly sharper and less mottled than V2. |
| Did it fix the porcupine needles? | **No.** At 140 px off-axis, V3 has the *same dense needle fan* as V2, and slightly more of it because it carries 44% more splats. |
| Why was the held-out PSNR only ~12 dB? | **Mostly measurement artefact** — the reference frame is 42.8% black padding and the masks hide ~40% of the image. Masked, the same renders score **24.5–25.5 dB**, and V3 raw beats V2 by **+0.75 dB** (§2). |
| Is the bend a 1D temporal drift? | **Yes for the trajectory, no for the geometry.** Detrending levels all five presets to 1.00 ± 0.042 and cuts multi-visit height range p90 from 0.997 to 0.086 — but it injects 24 px (p90) of reprojection displacement and *worsens* the V2 footprint gate from 66.39% to 53.57% (§3). |
| Was Task 3's cap-saturation diagnosis right? | **Partly wrong.** `--progressive-splat-budget` already defaults to 1 and was active; the actual knob is `--growth-factor`, whose default 1.05 predicts the observed cap exactly (§4). |

---

## 1. Task 1a — visual evidence at last

Two local packages were served side by side and captured with the same driver:

| | V2 | V3 |
|---|---|---|
| package | `optimization-v1/preview-coverage-v2-step6000/` | `optimization-v1/preview-coverage-v3-step24000/` |
| URL | `http://127.0.0.1:8643/` | `http://127.0.0.1:8642/` |
| model | 1,699,990 splats | 2,455,235 splats (cleaned) |

Capture harness: `forensic-20261104/capture-preview-views.mjs` — headless Chrome through the
`playwright-core` install already in `work/mobile-20261029`, `--use-angle=d3d11`,
1280×800 viewport, `#open` clicked, wait for the five preset options plus 8 s of progressive
refinement, then `page.locator('#canvas').screenshot()` per view (element screenshot rather than
`toDataURL`, so no `preserveDrawingBuffer` dependency). 32 s per model.

Seven named views plus two extra off-axis drags:

| slug | what it targets |
|---|---|
| `main-room` | the plastic drawer tower and the storage bins (porcupine site) |
| `hallway`, `first-bathroom`, `second-bathroom`, `bedroom` | the other four presets |
| `main-room-orbit-near` | 140 px drag from Main room — inside the room, close to the tower |
| `bedroom-orbit-near` | 140 px drag from Bedroom |
| `main-room-orbit-left` | 320 px drag — this one ends *inside* a wall, kept as a control |

Outputs, all in `forensic-20261104/v3-browser-renders/`:

```
v2-main-room.png … v3-bedroom-orbit-right.png   (18 captures, 1280x701 each)
capture-v2.json, capture-v3.json                (renderer string, per-view status, page errors)
v3-vs-v2-contact.png                            (9 views x [V2 | V3 | |diff|x3])
v3-vs-v2-metrics.json
needle-zoom.png                                 (4 regions at 1.6x: tower, curtain, needle fan, tiles)
```

### 1.1 V2 vs V3, view by view

Pixel comparison of the two captures at the *same registered preset pose* (turn 3 verified the
presets are exact camera centres, `d_xz = 0.0000`), status strip cropped:

| view | MAE (8-bit) | PSNR | SSIM | pixels differing > 8/255 |
|---|---:|---:|---:|---:|
| Main room | 8.79 | 26.38 dB | 0.855 | 60.0% |
| Hallway | 9.40 | 24.47 dB | 0.880 | 50.0% |
| First bathroom | 6.64 | 28.59 dB | 0.888 | 42.9% |
| Second bathroom | 5.69 | 29.09 dB | 0.884 | 29.3% |
| Bedroom | 4.72 | 31.71 dB | 0.900 | 23.5% |
| Main room · orbit 140 px | 29.67 | 16.97 dB | 0.829 | 94.4% |
| Bedroom · orbit 140 px | 5.78 | 29.64 dB | 0.881 | 31.8% |
| Main room · orbit 320 px | 20.83 | 18.63 dB | 0.906 | 92.3% |
| Bedroom · orbit 320 px | 9.74 | 24.94 dB | 0.821 | 64.9% |

These are two different models, not two renders of one model, so MAE of 5–9 counts per channel on the presets
is expected (different PPISP/bilateral gains alone move colour by several counts). The one outlier, Main room at 140 px, is 94.4% of pixels differing: that drag ends with the camera almost touching the drawer tower, and the two models fill that near-field volume very differently — which is also where the needles live. The SSIM
band 0.86–0.90 says the two agree on structure, which is what makes the local diffs meaningful.

### 1.2 What the images actually show

**Drawer tower, main room (`needle-zoom.png`, row 1).** V2 smears the tower into vertical
streaks and doubles the orange/pink drawer edges — the classic double exposure from two visits
blended at one place. V3 resolves the individual plastic boxes, keeps a single edge per seam and
restores the drawer labels. This is the clearest improvement in the whole set.

**Curtain and left bin stack (row 2).** V2 carries a fat white blob across the two grey bins and
a milky wash over the curtain. V3 has a defined bin edge, readable label, and a curtain with
actual folds; a faint ghost remains on the middle bin.

**Needle fan, 140 px off-axis (row 3).** Both models show a dense fan of hair-thin filaments in
front of the tower. **V3's fan is at least as dense as V2's**, and in places more visible,
because V3 keeps 2.46 M splats where V2 keeps 1.70 M. The 5 s CPU cleanup removed every *visible
long spike above 0.04 units* (turn 3 §4) but these filaments are short and thin, so they survive
by construction. **The porcupine is not fixed. It is a training-time defect, not a post-filter
one.**

**Tiled bathroom wall (row 4).** V2 shows the mottled "cellular" blotch across the tiles, exactly
the artefact the operator described. In V3 the wall is nearly uniform and the tile grid reads
cleanly; only a faint vertical smear survives near the left tile edge. The
`bilagrid_tv_loss_weight 50` + `bilagrid_adagrad_lr 0.01` change did what it was meant to do.

**The 320 px drag** ends inside a wall in both models (a cyan wash), which is a viewer-geometry
observation, not a model defect: the drag orbits about the preset target, and past ~200 px the
camera leaves the room. Kept in the sheet so the failure mode is documented rather than hidden.

---

## 2. Task 1b — the 12 dB mystery, and the masked score

### 2.1 Why the number was low

Measured on the first saved eval pair:

| | value |
|---|---|
| reference frame | 1200 × 1200, **42.8%** of pixels are near-black (fisheye padding) |
| rendered frame | same geometry, only **1.4%** near-black — the renderer paints content where the reference is padding |
| operator keep-mask, 200 eval frames | keep fraction min **0.330**, median **0.540**, max 1.000; 27 of 200 masks are fully open. The 200 frames actually scored average **0.603**, i.e. 40% of each frame is excluded |
| V2 unmasked PSNR on one frame | 9.87 dB |

So about two fifths of every scored pixel is either black padding or deliberately masked-out
content. Scoring that as error measures the mask, not the reconstruction.

### 2.2 Method

`forensic-20261104/run_masked_eval_passes.py` runs three one-step `--init-ply` eval passes
(`--num-iterations 1`, eval split unchanged, `--save-eval-images 1`) for V2, V3 raw and V3
cleaned, into `optimization-v1/eval-masked/{v2,v3raw,v3cleaned}/`. Each pass writes
`eval-gt-NNNNN.png` / `eval-render-NNNNN.png` pairs.

The index is **not** the sorted filename order — the first attempt assumed it was and produced a
nonsense 12.07 dB for V3 raw against a 12.27 dB self-report. `score_masked_eval.py` recovers the
mapping **per model** by matching 16×16 mean-removed thumbnails of each run's `eval-gt-*.png`
against the dataset images, asserts the match is one-to-one, then scores only `mask > 127`
pixels with the project's usual metric (RGB SSIM, 11×11 Gaussian σ1.5, range 255, window centres
inside the mask).

### 2.3 Results, 200 of 1,070 held-out faces

| model | **masked PSNR** | masked p10 | masked median | masked SSIM | masked MAE | unmasked PSNR (same 200) | spirula `avg_psnr` (all 1,070) |
|---|---:|---:|---:|---:|---:|---:|---:|
| V2 step-6000 | **24.735 dB** | 20.389 | 24.802 | 0.7671 | 10.771 | 11.703 dB | 12.1674 dB |
| V3 raw step-24000 | **25.484 dB** | 21.162 | 25.587 | 0.7762 | 9.769 | 11.967 dB | 12.2662 dB |
| V3 cleaned | **24.485 dB** | 20.182 | 24.668 | 0.7614 | 11.147 | 12.430 dB | 12.1755 dB |
| Δ V3 raw − V2 | **+0.749 dB** | +0.773 | +0.785 | +0.0091 | −1.00 | +0.26 dB | |
| Δ V3 cleaned − V2 | **−0.250 dB** | −0.207 | −0.134 | −0.0057 | +0.38 | +0.73 dB | |

Mean mask keep fraction 0.603 / 0.611 / 0.621 — so ~40% of each frame is excluded, and the
masked scorer is measuring the ~60% the operator actually cares about.

Three things follow.

1. **The 12 dB figure was almost entirely a scoring artefact.** Masked, the same renders score
   ~25 dB. About 12 dB of the apparent error was black padding plus masked-out pixels.
2. **On valid pixels only, the V3 rebuild is ahead of V2** (+0.75 dB, +0.009 SSIM) — the opposite
   of the unmasked ordering in turn 3, where the two were level. The stronger bilateral-grid
   regularisation and the 6,000-step polish pay off exactly where the operator looks.
3. **The cleanup costs 0.25 dB inside the keep-mask** (25.484 → 24.485) while *improving* the
   full-frame number (11.97 → 12.43). Pruning 940 k splats removes veiling haze that spreads into
   the padding — good for the browser view, slightly bad for the pixels the mask keeps. The
   min-axis floor is the likely culprit: lifting 556,121 short axes to `max_scale/25` thickens
   splats that were contributing sub-pixel detail. It is a real trade, not a free win.

Reproduce: `score_masked_eval.py --models v2 v3raw v3cleaned --limit 200` (~10 min; SSIM at
1200×1200 dominates, which is why this is a 200-frame subsample and not all 1,070).

---

## 3. Task 2 — the 1D temporal bend, measured

`forensic-20261104/detrend_temporal_height.py` (10 s, CPU, no SfM) →
`forensic-20261104/temporal-detrend.json`.

Model: one camera height per timestamp, `Ȳ(t)` = median over the two lenses, then a Gaussian
smoother with σ = 15 timestamps truncated at ±45. The drift to remove is `Δ(t) = Ȳ_smooth(t) − 1`
and `y ← y − Δ(t)`.

### 3.1 The curve

| | value |
|---|---|
| registered timestamps | 3,231 |
| raw height | min 0.23898, max 1.67211, spread **1.4331**, median 1.0009, std 0.3658 |
| smoothed height | min 0.25907, max 1.65725, spread **1.3982**, std 0.3646 |
| Δ(t) | min −0.7409, max +0.6572, std 0.3646 |
| residual after removal (what is kept) | RMS **0.02469** units, \|residual\| p95 **0.0546** — 2.5 cm and 5.5 cm |
| Δ(t) sampled every 250 frames | 0: +0.011, 250: −0.669, 500: +0.306, 750: −0.127, 1000: +0.077, 1250: −0.226, 1500: +0.110, 1750: +0.327, 2000: +0.463, 2250: −0.066, 2500: −0.376, 2750: −0.043, 3000: −0.662, 3250: +0.495 |

The smoother barely shrinks the spread (1.4331 → 1.3982), and that is the informative part: what
the mandate calls "low-frequency drift" is not a slow instrument ramp. Sampling Δ(t) every 250
timestamps shows it swinging between −0.67 and +0.50 within a few hundred frames, i.e. it follows
the **room-to-room transitions of the walk-through**, not a monotone bias. σ = 15 (±0.5 s)
therefore removes sub-second jitter only — RMS 0.0247 units, p95 0.0546 — and leaves the
per-visit level offsets intact.

That is why the mechanism works at all: two visits to the same place happen at different `t`,
hence carry different Δ, and removing each visit's own Δ makes them agree. It is a per-visit level
correction expressed as a function of time, and it is single-valued in `t` by construction.

### 3.2 Gate 1 — the five preset cameras

| | before | after |
|---|---:|---:|
| min | 0.2965 | 0.9581 |
| max | 1.1989 | 1.0236 |
| **spread** | **0.9024** | **0.0655** |
| max abs offset from 1.00 | — | **0.0419** |
| gate "all within 1.00 ± 0.08" | fail | **PASS** |

### 3.3 Gate 2 — the 132 multi-visit cells

| statistic | before | after |
|---|---:|---:|
| height range, median | 0.1134 | **0.0248** |
| height range, p90 | **0.9966** | **0.0857** |
| height range, max | 1.3607 | **0.1489** |
| gate "p90 < 0.15" | fail | **PASS** |

So the hypothesis in the mandate is **right about the trajectory**: once a single smooth
per-timestamp offset is removed, the cameras really do sit at one level.

### 3.4 Gate 3 — what it costs geometrically

A track's 3D point can only receive one shift, its observing cameras receive theirs. The residual
displacement is `|Δ_point − Δ_camera|`, which reprojects to `f · |Δ_point − Δ_camera| / depth`
pixels. Measured on the real sparse reconstruction
(`dense-pinhole-1200/sparse/0`: 32,310 images, 3,507,037 points, `f = 600 px`, **150,000 sampled
points, 804,158 observations**), with each point's shift taken as the median over its track:

| statistic | value |
|---|---:|
| Δ spread inside a track — p50 / p90 / p99 | **0.0184 / 0.1421 / 0.5337** |
| vertical mismatch — p50 / p90 / p99 | **0.0085 / 0.0810 / 0.3574** units |
| approximate pixel error at f = 600, depth = 2 units — p50 | **2.55 px** |
| … p90 | **24.31 px** |
| … p99 | **107.22 px** |

The mandate's premise ("temporally nearby cameras whose ΔY(t) is nearly identical") holds for the
median track and **fails in the tail**: 10% of observations move by more than 24 px, 1% by more
than 107 px. A free per-point shift therefore cannot be applied to the existing points. The
correct consumer of Δ(t) is the **camera trajectory plus a re-triangulation** (bundle adjustment
after the shift), not a translation of solved geometry.

### 3.5 Gate 4 — the footprint gate

`apply_detrend_and_gate.py` writes `splat-detrended.ply` (2,455,235 splats shifted by a 0.25-unit
cell-mean of Δ, range −0.741 … +0.644) and `poses-detrended.npz`, then runs the *real* gate code
path (`export-trained-cameras.py:fit_shell` → `occupied_footprint.py:footprint`).

`gate_v2_detrended.py` does the same for the V2 model, because that is where 66.39% came from:

| model | cameras | footprint cells | near fraction ≤ 0.25 | outside | floor plane |
|---|---:|---:|---:|---:|---:|
| **V2 original** | 3,231 | 3,020 | **66.39%** (1,086 outside) | 1,086 | −0.0156 |
| **V2 detrended** | 3,231 | 1,570 | **53.57%** (1,500 outside) | 1,500 | +0.1786 |
| V3 cleaned original | 3,231 | 9,393 | **100.00%** | 0 | −0.0282 |
| V3 cleaned detrended | 3,231 | 8,723 | **100.00%** | 0 | +0.1539 |

The V2 baseline reproduces turn 1's number **exactly** (0.6638811513463324 = 66.39%, 1,086 of
3,231), so the harness is calibrated. And the detrend makes it **worse, not better**
(66.39% → 53.57%): the footprint is built from splats inside a wall band around the fitted floor,
and shifting splats by a *spatial* field is exactly the operation §3.4 shows cannot represent a
bimodal place — in a cell visited at two heights the cell-mean splits the difference and both
visits end up half-wrong, flattening a floor that was at least locally consistent.

On the V3 cleaned model the gate already passes at 100% before any detrending, so there is no
headroom to show, only the floor/ceiling bands moving (floorY −0.028 → +0.154, ceilingY
2.063 → 2.036 — the room height is preserved to 2 cm while the plane moves up, which is the
signature of a *global* level change with local geometry intact).

**Net:** the 1D temporal detrend is real and it levels the cameras, but it cannot be transferred
to points or splats by translation. The three ways forward, in order of value:

1. detrend the **poses**, then re-triangulate and re-run BA (points follow the cameras instead of
   being shifted), then train on the result — this is the only version that keeps §3.3's win;
2. keep the per-cell shell and cut the dollhouse per room (turn 3 §6);
3. per-room `train --partition`, which sidesteps the problem by never mixing visits in one model.

---

## 4. Task 3 — the cap saturation, with the arithmetic checked

No training was run. The flags were read from `train 3dgs --help-all`:

```
--growth-factor            [1.05]   How fast the splat count grows at each round.
--progressive-splat-budget  [1]     Holds the number of splats below the maximum until the
                                    images are sharp enough to show where more are needed.
--refine-every            [100]
--refine-start-iter       [500]
--max-split-fraction      [0.1]
```

Two corrections to the mandate:

1. **`--progressive-splat-budget 1` is already the default**, so it was active during the V3 run
   and did not prevent the cap. Setting it again changes nothing.
2. **The cap time is fully explained by `--growth-factor`.** With 1,996,179 seed splats,
   `2.0 M × 1.05^n` first exceeds 3,500,000 at n = 12 (1.05¹² = 1.7957 → 3.585 M), and refine
   rounds start at step 500 every 100 steps, so round 12 lands at **step 1,700**. V3 hit the cap
   at step **1,701**. The model is exact.

To spread growth over the whole refinement window (500 → 18,000 = 175 rounds):

```
growth = (3.5 M / 2.0 M) ^ (1/175) = 1.00320
```

so the correct flag is **`--growth-factor 1.0032`**, not 1.004 (1.004¹⁴⁰ ≈ 1.75 only if the seed
is 2.0 M and the exponent is 140 rounds, i.e. a 14,000-step refinement window — the exponent
depends on how many refine rounds the schedule actually has, which is why 1.05 needs 12 and 1.0032
needs 175).

`--max-batch-per-epoch 3348` gives 4 cameras/step; 12,000 steps × 4 = 48,000 renders, the same
render budget as V3's 24,000 × 2. **The per-step cost of 4 cameras is not measured in this turn**
and should be timed on the first 200 steps before committing to 12,000 steps.

---

## 5. Reproduction

```powershell
$R = "C:\Users\bombe\Documents\Codex\2026-10-27\files-pasted-by-the-user-system\.local\osmo-stick-20261103"

# serve the two packages
Start-Process python -ArgumentList '-m','http.server','8642','--bind','127.0.0.1' -WorkingDirectory "$R\optimization-v1\preview-coverage-v3-step24000"
Start-Process python -ArgumentList '-m','http.server','8643','--bind','127.0.0.1' -WorkingDirectory "$R\optimization-v1\preview-coverage-v2-step6000"

# Task 1a
& 'C:\Program Files\nodejs\node.exe' "$R\forensic-20261104\capture-preview-views.mjs" --url http://127.0.0.1:8642/ --out "$R\forensic-20261104\v3-browser-renders" --tag v3
& 'C:\Program Files\nodejs\node.exe' "$R\forensic-20261104\capture-preview-views.mjs" --url http://127.0.0.1:8643/ --out "$R\forensic-20261104\v3-browser-renders" --tag v2
python "$R\forensic-20261104\assemble-v3-vs-v2.py"
python "$R\forensic-20261104\zoom-needles.py"

# Task 1b
python "$R\forensic-20261104\run_masked_eval_passes.py"
python "$R\forensic-20261104\score_masked_eval.py" --models v2 v3raw v3cleaned --limit 200

# Task 2
python "$R\forensic-20261104\detrend_temporal_height.py"
python "$R\forensic-20261104\apply_detrend_and_gate.py"
python "$R\forensic-20261104\gate_v2_detrended.py"
```

---

## 6. Limits

* The browser captures prove what the **user-facing package** looks like, not what the native
  renderer shows. The viewer applies no training-time PPISP gains, so colours shift between
  packages; the structural comparisons (edges, ghosts, needles) are unaffected.
* The off-axis views are pointer drags, not poses on the registered trajectory — they are
  indicative, and the 320 px pair ends inside a wall.
* Masked scoring covers **200 of 1,070** held-out faces (subsample limited by SSIM cost at
  1200×1200). PSNR/SSIM are means over that subsample; the mapping is one-to-one but a handful of
  frames had a thumbnail margin as low as 0.0005, so individual per-frame numbers are less
  trustworthy than the aggregate.
* The reprojection error in §3.4 is a **displacement** estimate, not a re-triangulated residual:
  it assumes a nominal depth of 2 units, so it scales linearly with the true depth. It measures
  the harm a free per-point shift does; it is not a claim about what a BA would achieve.
* The detrended artifacts (`splat-detrended.ply` for V3 and V2, `poses-detrended.npz`) are
  **experimental outputs**, written next to — never over — the originals. Nothing consumed them.
* No training was started, so nothing here says whether training on detrended poses improves the
  splats. That is the next experiment, and it needs the re-triangulation step of §3.5 first.
