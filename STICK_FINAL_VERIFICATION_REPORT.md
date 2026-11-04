# STICK final verification — true 1D needles, the V4 attempt, and the unlocked cutaway

Turn-5 report. English. No long training run completed this turn; one 600-step diagnostic did
(§2). Everything else is CPU work, one-step eval passes, the native exporter, and headless Chrome.

---

## 0. Verdict

| Step | Result |
|---|---|
| **1. True 1D needle filter (`s3/s2`)** | Implemented and run in **2.8 s**. Pruned 1,138,030 splats (33.5%), needle ratio p99 **7.28 → 3.70**, max **88.5 → 5.92**, share above 4 **3.87% → 0.0027%**. |
| Masked PSNR after the new filter | **24.35 dB (with k-NN isolation) / 24.42 dB (without)** — the hope of recovering 25.48 dB was **not** realised: the `s1` floor was **not** the cause of the earlier 1.0 dB loss (§1.3). |
| Visual effect on the row-3 needle fan | **The long hairs are gone**; a shorter, denser fuzz remains. V2's frame-crossing streaks are no longer present. |
| Side effect of the `d8 > 0.06` isolation rule | **Pinholes in the tiled wall** — attributed and quantified in §1.4; the no-isolation build is the better one. |
| **2. V4 smoothing pass** | **Failed, twice, for measured reasons**: VRAM at `cap-max 3.5 M` (Vulkan `vkQueueSubmit` failure) and **0.848 s/step** at a cap that fits — 18× the V3 cost, i.e. **5.6 h** for 24,000 steps. Recipe is infeasible on this machine as specified (§2). |
| **3. Dollhouse cutaway** | **Unlocked.** The official exporter reports `cameraNearFootprintFraction = 1.0` over **6,462** cameras, `occupiedShell` fully populated, and the shared-controls site is built and running with a working **Top view** that shows the ceiling cut away (§3). |

---

## 1. Step 1 — true 1D needles (`s3 / s2`), not `s3 / s1`

`forensic-20261104/clean_true_1d_needles.py` →
`optimization-v1/appearance-training-v3-fast/selected/step-000024000.ckpt/`
`splat-cleaned-v2.ply` (v3b, default rules) and `splat-cleaned-v2-noiso.ply` (v3c).

### 1.1 What ran (2.8 s, CPU)

Sorted axes per splat, then:

| rule | splats |
|---|---:|
| `alpha < 0.02` | 891,081 |
| outside seed box + 0.35 units | 39,030 |
| `s3/s2 > 6.0` (any size) | 53,446 |
| `s3/s2 > 4.0` AND (`s3 > 0.004` OR `alpha > 0.08`) | 131,239 |
| isolated: 8th-neighbour `d8 > 0.06` AND `alpha < 0.50` | 98,175 |
| **total pruned** | **1,138,030 (33.5%)** |
| kept (v3b) | **2,257,363** |
| kept (v3c, isolation rule disabled) | **2,355,538** |

Modifications, not deletions: **104,193** cigars with `3.0 < s3/s2 ≤ 4.0` had their **longest** axis
shrunk to `3.0 × s2` (never inflating `s1`), and **187,599** axes were lifted to the numeric floor
`1e-5` — a bit-level guard, not the old `s3/25` thickening.

The ratio statistics confirm the diagnosis in the mandate:

| | before | after |
|---|---:|---:|
| needle ratio `s3/s2` p50 | 1.398 | 1.428 |
| p99 | **7.279** | **3.702** |
| max | **88.48** | **5.92** |
| share > 4 | **3.869%** | **0.0027%** (61 splats) |
| disk ratio `s2/s1` p50 | 2.740 | — (untouched by design) |
| `alpha < 0.1` | 64.62% | 54.19% |

### 1.2 Masked score, 200 of 1,070 held-out faces

| model | masked PSNR | masked SSIM | spirula unmasked `avg_psnr` (1,070) |
|---|---:|---:|---:|
| V2 step-6000 | 24.735 | 0.7671 | 12.1674 |
| V3 raw step-24000 | **25.484** | **0.7762** | 12.2662 |
| V3 old cleaned (`s1 → s3/25`) | 24.485 | 0.7614 | 12.1755 |
| **V3b** new, `s3/s2` + isolation | **24.350** | 0.7597 | 12.0589 |
| **V3c** new, `s3/s2`, no isolation | **24.416** | 0.7575 | 12.0964 |

### 1.3 The hypothesis in the mandate is wrong

The mandate predicted that flooring `s1` on 556,121 flat disks caused the drop from 25.48 to
24.48 dB, and that keying on `s3/s2` would recover it. Measured: with the `s1` floor replaced by a
mere `1e-5` numeric guard, the score is **24.35–24.42 dB** — statistically the same as the old
24.485, and still **1.0 dB below** the raw model.

So the 1.0 dB is the price of **pruning itself**, not of axis inflation: the 891 k dead splats and
132 k needles are not inert — at `alpha` between 0.02 and 0.1 they contribute to the composited
image, and removing them removes both haze *and* a little signal. There is no free lunch in the
post-filter direction: **the raw model is the best scorer and the worst to look at.** The cleanup
is a visual choice with a measurable 1 dB price, and every variant of it lands in the same place.

### 1.4 The `d8 > 0.06` isolation rule punches holes in flat walls

`needle-zoom-v3way.png` puts V2, V3b (isolation on) and V3c (isolation off) side by side on the
same pixels:

* **Tiled wall (row 1):** V3b shows scattered **black pinholes** along the grout lines and in the
  shadow; V3c is smooth. A planar surface has roughly half the volumetric neighbour density of a
  solid, so a 6 cm 8th-neighbour threshold clips splats on genuinely thin surfaces — exactly the
  surfels the cleaner is supposed to protect.
* **Needle fan (row 2):** both V3 variants are much better than V2 — V2's hair filaments **cross
  a third of the frame**, V3's are short and clustered. The `s3/s2` rule did its job on the long
  1D cases.
* **Drawer tower (row 3):** V3b/V3c keep the sharp single edges that earned the masked win.

**Recommendation:** keep the `s3/s2` prune, drop or greatly raise the isolation threshold
(≥0.12), or gate it on `alpha < 0.2` as well. V3c is the model used for the cutaway export below.

---

## 2. Step 2 — the V4 smoothing pass, and why it cannot run as specified

### 2.1 Attempt 1 — cap 3.5 M — out of device memory

```
step 1/24000  splats 1996179  rgb_loss=0.1558 ...
error: Vulkan backend: dispatch of intersect_tile.tile_active_map failed:
       vkQueueSubmit failed (VkResult -4)
```

GPU memory had reached **15,384 MiB of 16,303**. V3, with the same cap and the same seed, ran at
**5.3 GB** — so the added `--depth-distortion-reg 0.01` (plus `--normal-reg-weight 0.02`) is what
pushes the allocator over the edge at `cap-max 3,500,000`.

### 2.2 Attempt 2 — cap 2.6 M — fits, but 18× slower

A 600-step diagnostic (`optimization-v1/v4-smoke/`) with the identical recipe at
`--cap-max 2600000`:

| | value |
|---|---|
| steps completed | 600 / 600 |
| wall clock | **8 min 28.6 s** |
| **per step** | **0.848 s** |
| V3 reference | 0.0463 s/step |
| ratio | **18.3×** |
| projected 24,000 steps | **≈ 5.6 hours** |
| exit | `0xC0000005` after training, during the eval pass |

So the V4 recipe is blocked twice over: it does not fit at the cap the mandate specifies, and at a
cap that fits it costs 18× per step because the distortion regulariser adds a per-pixel pass that
two cameras per step cannot amortise. **No V4 model exists.** What would work, in order:

1. `--depth-distortion-reg 0.01` with `--max-batch-per-epoch 13390` (8 cameras/step) and ~6,000
   steps — same 48 k renders, 4× fewer per-step overheads;
2. or `--depth-distortion-reg 0.003` at 24 k steps, if the penalty is effective at a third of the
   weight;
3. or keep V3 and rely on the `s3/s2` post-filter, accepting the fuzz.

---

## 3. Step 3 — the dollhouse cutaway, unlocked

### 3.1 Official camera export (112 s)

```
python export-trained-cameras.py --dataset dense --selection dense/analysis/frame-selection.json
    --normalization dense/geometry/normalization.json
    --trained-ply .../splat-cleaned-v2-noiso.ply   # V3c
    --output-dir optimization-v1/preview-v3d-controls-cameras
```

| audit field | value |
|---|---|
| `trainedGaussians` | 2,355,538 |
| `opaqueSampleCount` | 57,755 |
| `cameraCount` | **6,462** |
| **`cameraNearFootprintFraction`** | **1.0** (was 0.662 / “66.2% nearby cameras; 90% required” for V2) |
| `occupiedShell` | **populated** — `floorY −0.0303`, `ceilingY 2.0807`, `interiorCameras` 49 points, `footprint` with `sdfCm`, `lowerCeiling`, `exteriorMargin`, `wallBand` |
| shell method | “Horizontal coverage in the trained Gaussians, robust plane fits below/above the fresh camera-height envelope.” |

The 66.39 % failure from turn 1 is gone: the same gate reports **1.0** over all 6,462 cameras.

### 3.2 Shared-controls site built (1 s)

```
node work/osmo-parity-20261101/review/production/build-stick-preview.mjs \
     optimization-v1/preview-coverage-v3c-step24000 \
     optimization-v1/preview-v3d-controls-cameras \
     optimization-v1/preview-v3-final-cutaway
```

Output: `index.html` (16.8 kB), `room.json` (660 kB manifest with the camera set), `model.spz`
(42.3 MB), 7 source photos, and the esbuild chunks. Served at **http://127.0.0.1:8646/**. The
shell carries `Walk · Orbit · Top view · See inside · Reset view · Photos · More`, i.e. the same
controls as the other shared previews.

### 3.3 Screenshots — `forensic-20261104/v3-final-verification/`

| file | what it shows |
|---|---|
| `A3-top-view-after-preset.png` | **the dollhouse floorplan** — ceiling removed, bathroom fixtures, bedroom, main room and corridor all readable |
| `04-see-inside-dollhouse.png` | `See inside` from the loaded overview (whole model in frame, but far away) |
| `05-dollhouse-orbit.png` | cutaway orbited after `See inside` |
| `A1-main-room-preset.png`, `D1-second-bathroom.png`, `D2-first-bathroom.png`, `D3-bedroom.png`, `D4-entry.png` | the seven recorded viewpoints, used as the room shortcuts |
| `E1-main-room-orbit-140px.png`, `11-main-room-orbit-140px.png` | off-axis needle inspection inside the room viewer |
| `B1-main-room-zoomed.png`, `C1-see-inside-zoomed.png` | **control images of a failure mode**: six wheel notches drive the camera through a wall, so the frame is a colour wash. Kept, not hidden. |
| `01-entry-overview.png` | **the dollhouse entry view** — the default load already shows the apartment from a three-quarter angle with the ceiling cut away: both wet rooms, the bedroom, the main room and the corridor |
| `02-orbit.png`, `03-top-view-floorplan.png` | the same state after `Orbit` and `Top view` |

The cutaway site is served at **http://127.0.0.1:8642/** (the mandate's port); `01-entry-overview.png`
is the three-quarter dollhouse and `A3-top-view-after-preset.png` is the plan view. `See inside` from a
far camera leaves the model small in frame, so the two annotated views above are the ones to read.

---

## 4. Reproduction

```powershell
$R = "C:\Users\bombe\Documents\Codex\2026-10-27\files-pasted-by-the-user-system\.local\osmo-stick-20261103"

# Step 1
python "$R\forensic-20261104\clean_true_1d_needles.py"                     # v3b, with isolation
python "$R\forensic-20261104\clean_true_1d_needles.py" `
    --output "$R\optimization-v1\appearance-training-v3-fast\selected\step-000024000.ckpt\splat-cleaned-v2-noiso.ply" `
    --isolated-distance 1e9                                                # v3c, recommended
python "$R\prepare-coverage-v3-preview.py" --source <ply> --out <dir> --step 24000
node "$R\forensic-20261104\capture-preview-views.mjs" --url http://127.0.0.1:8644/ --out "$R\forensic-20261104\v3-browser-renders" --tag v3b
python "$R\forensic-20261104\zoom-threeway.py" needle-zoom-v3way.png
python "$R\forensic-20261104\run_masked_eval_passes.py" v3clean2 v3clean3
python "$R\forensic-20261104\score_masked_eval.py" --models v3clean2 v3clean3 --limit 200

# Step 2 (the two runs that define the limit)
pwsh -NoProfile -File "$R\forensic-20261104\launch-v4-smooth.ps1" -NumIterations 24000   # OOM at step 1
# 600-step diagnostic at cap 2.6 M: 0.848 s/step  -> optimization-v1/v4-smoke/

# Step 3
python "$R\export-trained-cameras.py" --dataset "$R\dense" --selection "$R\dense\analysis\frame-selection.json" `
    --normalization "$R\dense\geometry\normalization.json" `
    --trained-ply "$R\optimization-v1\appearance-training-v3-fast\selected\step-000024000.ckpt\splat-cleaned-v2-noiso.ply" `
    --output-dir "$R\optimization-v1\preview-v3d-controls-cameras"
node work/osmo-parity-20261101/review/production/build-stick-preview.mjs `
    "$R\optimization-v1\preview-coverage-v3c-step24000" `
    "$R\optimization-v1\preview-v3d-controls-cameras" `
    "$R\optimization-v1\preview-v3-final-cutaway"
python -m http.server 8646 --bind 127.0.0.1     # inside preview-v3-final-cutaway
node "$R\forensic-20261104\capture-cutaway-pass2.mjs" --url http://127.0.0.1:8646/ --out "$R\forensic-20261104\v3-final-verification"
```

---

## 5. Limits

* The masked scores cover 200 of 1,070 held-out faces; the aggregate is reliable, individual
  frames less so (thumbnail mapping margin as low as 0.0005).
* Visual judgements are mine, on 1440×900 and 1690×3394 crops, not a formal blind review.
* The V3b/V3c difference is one threshold; other values between 0.06 and ∞ were not swept, so
  “no isolation at all” is the safest of the two, not a tuned optimum.
* The cutaway is verified **only** through the browser package. No native-renderer check, no mobile
  check, and the ceiling cut is a render-time clip, not a cleaned geometry claim.
* V4 does not exist. The 0.848 s/step and the Vulkan failure are the evidence for why, not an
  opinion about the recipe's value — at 8 cameras per step the arithmetic changes, and that is the
  experiment to run next.
