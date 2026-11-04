# STICK V3d — trajectory free-space tube carved, mid-air fog pruned, dollhouse re-verified

Turn-6 report. English. Zero GPU training: one 3.3 s CPU cleaner, one 112 s camera export, one
1.6 s SPZ pack, one site build, headless-Chrome captures. All V3c/V2 artifacts from earlier
turns are untouched; every V3d artifact is a new file.

---

## 0. Verdict

| Check | Result |
|---|---|
| Step 1 — trajectory carve + fog prune | **3,395,393 → 976,629 splats (−71.2 %)** in **3.3 s**. Rule A (tube) removed **378,090**; Rule B (fog) removed **924,494**; proven V3c geometry rules removed 1,116,180. |
| Haze band `0.02 ≤ α < 0.10` | **64.62 % of raw → 21.40 % of V3d** (V3c was 54.19 %). Median α **0.053 → 0.223**. |
| Needle ratio `s3/s2` after | p99 **3.09**, max **3.20** (the cigar cap; raw max was 88.5). |
| `images.txt` frame check | `dense/sparse/0/images.txt` parses to **6,462 centres; 6,462/6,462 match** `poses-cache.npz` at ≤ 2.8e-15 — same frame, so the tube is carved in the trained splat frame directly. |
| Step 2 — footprint gate on V3d | **`cameraNearFootprintFraction = 1.0`** over 6,462 cameras; `occupiedShell` populated (`floorY −0.03145`, `ceilingY 2.0767`, 48 interior cameras, footprint with `sdfCm`/`lowerCeiling`/`wallBand`). Still pass. |
| Visual result | The milky cloud in the main room/corridor is **visibly thinner** in both mandated views and the top-view floorplan reads clearly; tiles stay 100 % pinhole-free (no isolation rule); the drawer tower is cleaner. Cloud-box mean luma drops **−4.9 (entry) / −5.0 (top view)** — the veil measure that actually moves. |

---

## 1. Step 1 — `clean_trajectory_and_fog.py` (3.3 s, CPU)

Input `step-000024000.ckpt/splat.ply` → `splat-cleaned-v3d.ply`. Rules applied in order,
counts are incremental (disjoint), so they sum exactly.

### 1.1 Stage 1 — the proven V3c geometry rules (mandate-tightened, no isolation rule)

| rule | splats |
|---|---:|
| `alpha < 0.02` | 891,081 |
| outside seed box + 0.35 | 20,487 |
| `s3/s2 > 5.0` (any size) | 79,441 |
| `s3/s2 > 3.2` AND (`s3 > 0.003` OR `alpha > 0.06`) | 125,171 |
| **stage-1 subtotal** | **1,116,180** |

Modified, not deleted: **148,400** cigars (`2.2 < s3/s2 ≤ 3.2`) had their longest axis shrunk to
`2.2 × s2` (never inflating `s1`), and **73,368** axes were lifted to the `1e-5` numeric floor.

### 1.2 Rule A — camera-trajectory free-space tube (new)

Camera centres: `forensic-20261104/poses-cache.npz`, **6,462** centres / 3,231 timestamps,
y median 1.000, y p05 0.330, y p95 1.526, **660 centres below y 0.5** (the crouch cohort that
could touch the floor with the clearance sphere). Cross-checked against
`dense/sparse/0/images.txt` parsed directly: 6,462/6,462 match, max distance 2.8e-15.

| rule | splats |
|---|---:|
| lens clearance sphere: Euclidean `d < 0.28` of any centre | **140,455** |
| body/stick cylinder: `d_xz < 0.35`, `−0.50 ≤ Δy ≤ +0.22`, splat non-solid (`α < 0.50` or `s3/s2 > 2.0`) | **237,635** |
| **Rule A subtotal** | **378,090 (11.1 % of the raw file)** |

The cylinder test queries the `k = 24` nearest centres in (x, z) per splat. Reach: every
surviving splat sees at least one centre within 1.03 units in xz (p99 of the 24th-neighbour
distance), so on the dense walk path the test is effectively exact; only a sliver of height-
boundary cases at path ends can be missed (under-prune, never over-prune).

### 1.3 Rule B — translucent mid-air fog (new)

| rule | splats |
|---|---:|
| haze: `alpha < 0.06` (raised from 0.02) | **700,265** |
| large puffs: `alpha < 0.18` AND `s3 > 0.020` | **224,229** |
| **Rule B subtotal** | **924,494** |

The `0.08` variant was counted, not built: **123,420 survivors (12.6 % of V3d) are still below
0.08**, so a second pass at 0.08 would cut a further 12.6 %. Left out because the 0.06 build
already clears the mandated views and every extra point of pruning costs held-out fidelity.

### 1.4 Alpha structure, before → after

| | raw `splat.ply` | V3d |
|---|---:|---:|
| `alpha < 0.02` | 26.24 % | 0 % |
| `0.02 ≤ α < 0.10` | 38.37 % | **21.40 %** |
| `alpha < 0.10` | 64.62 % | **21.40 %** |
| `alpha < 0.18` | 76.02 % | 40.50 % |
| median α | 0.053 | **0.223** |
| p90 α | 0.478 | 0.750 |

Output: **976,629 splats** (28.8 % of the raw model). Byte-exact property copy for survivors;
scale edits written back onto the original unsorted slots so quaternions stay meaningful.

---

## 2. Step 2 — gate, pack, site (all green)

### 2.1 Official camera export on `splat-cleaned-v3d.ply` (112 s)

```
python export-trained-cameras.py --dataset dense --selection dense/analysis/frame-selection.json
    --normalization dense/geometry/normalization.json
    --trained-ply .../splat-cleaned-v3d.ply
    --output-dir optimization-v1/preview-v3d-defog-controls-cameras
```

| audit field | value |
|---|---|
| `trainedGaussians` | 976,629 |
| `opaqueSampleCount` | 115,246 (V3c: 57,755 — the fog was diluting the opaque sample) |
| `cameraCount` | 6,462 |
| **`cameraNearFootprintFraction`** | **1.0** (≥ 0.90 required; V3c also 1.0) |
| `occupiedShell` | **populated** — `floorY −0.03145`, `ceilingY 2.0767`, `interiorCameras` 48, `footprint` with `sdfCm`, `lowerCeiling`, `wallBand`, `exteriorMargin` |

### 2.2 Pack + shared-controls site

* `prepare-coverage-v3-preview.py` → `preview-coverage-v3d-step24000`: **17.8 MB** `model.spz`
  (V3c was 42.3 MB), SPZ v3, SH degree 2, mip flag retained, packed in **1.6 s**.
* `build-stick-preview.mjs` → `preview-v3d-final-cutaway`: `index.html` 16.8 kB, `room.json`
  660 kB, 7 source photos, chunks. Same Walk · Orbit · Top view · See inside · Reset view ·
  Photos · More shell.
* **Serving now at http://127.0.0.1:8642/** (the turn-5 V3c site that occupied the port was
  stopped and replaced). The V3d pack preview for the needle crops serves on
  http://127.0.0.1:8648/ (both verified HTTP 200).

---

## 3. Step 3 — visual comparison

Sheet: `forensic-20261104/v3d-final-verification/v3c-vs-v3d-dollhouse-and-zoom.png`
(1382 × 2982; left V3c, right V3d in every row).

| row | what it shows | reading |
|---|---|---|
| 1 | Dollhouse entry overview (`01-entry-overview.png`, both models) | The thick milk cloud filling the main room and corridor in V3c is **gone as a solid mass** in V3d — room boundaries, doorways and furniture read through. Residual white fuzz remains around wall tops and the corridor ceiling line. |
| 2 | Top-view floorplan (`A3-top-view-after-preset.png`) | The plan view is the biggest win: bathroom fixtures, bedroom rug and bed, main-room desk, kitchen counters and the corridor are all readable; V3c's overlay blurred exactly these. The floor is **continuous along the walk path** — the 660 crouch poses' clearance spheres did **not** punch visible holes. |
| 3 | Second bathroom tiled wall (crop) | **Zero pinholes** (the k-NN isolation rule stayed off). V3d is marginally more transparent; grout lines survive. |
| 4 | Orbit-140 px needle fan near the tower (crop) | Streaks are reduced but **not eliminated** — short fuzz survives, as in turn 5. |
| 5 | Drawer tower (crop) | Cleaner front face, slightly more saturated bin colours (haze layer removed); edges kept. |

In-room check (`A1-main-room-preset.png`, recorded 101 s view): curtain, drawer tower with
coloured bins, right shelf stack, left bin stack all intact. The floor directly in front of the
camera — the carved tube itself — now renders as a clean white smear instead of streaky fuzz,
which is the mandated free-space behaviour seen from inside.

### 3.1 Pixel metric (supporting, honestly mixed)

`fog_pixel_metrics.py` measures a "milky" signature (luma > 150, saturation < 35) over a fixed
crop and over the fixed cloud box:

| view | cloud-box mean luma V3c → V3d | cloud-box milky share | global milky share |
|---|---|---:|---:|
| entry overview | 118.4 → **113.5 (−4.9)** | 28.80 % → 27.59 % | 12.30 % → 12.19 % |
| top view | 133.7 → **128.7 (−5.0)** | 28.06 % → 27.84 % | 13.59 % → 14.83 % |

The veil measure that moves is **cloud-box mean luma, down ~5 units in both views** — the
compounded α-wash is thinner. The global milky share stays flat (and rises in the top view)
because legitimate white geometry dominates that bucket and de-fogging *reveals* bright floor
that the cloud was hiding. Pixel shares over-census white surfaces; the sheet is the evidence
that matters, and the structural α statistics in §1.4 are the cause.

### 3.2 New artifacts

* `forensic-20261104/clean_trajectory_and_fog.py`, `trajectory-fog-clean-v3d.json`,
  `assemble-v3c-vs-v3d.py`, `fog_pixel_metrics.py`, `fog-pixel-metrics.json` (in
  `v3d-final-verification/`)
* `.../appearance-training-v3-fast/selected/step-000024000.ckpt/splat-cleaned-v3d.ply`
* `optimization-v1/preview-coverage-v3d-step24000/`,
  `optimization-v1/preview-v3d-defog-controls-cameras/`,
  `optimization-v1/preview-v3d-final-cutaway/`
* `forensic-20261104/v3d-final-verification/` — 16 screenshots (entry, orbit, top views,
  see-inside, dollhouse orbit, A1–D4/E1 recorded views, the two wall-through controls B1/C1)
  + the comparison sheet + metrics
* `forensic-20261104/v3-browser-renders/v3d-*.png` — 9 pack-preview views for the crops

---

## 4. Reproduction

```powershell
$R = "C:\Users\bombe\Documents\Codex\2026-10-27\files-pasted-by-the-user-system\.local\osmo-stick-20261103"

# Step 1 (3.3 s)
python "$R\forensic-20261104\clean_trajectory_and_fog.py"

# Step 2
python "$R\prepare-coverage-v3-preview.py" `
    --source "$R\optimization-v1\appearance-training-v3-fast\selected\step-000024000.ckpt\splat-cleaned-v3d.ply" `
    --out "$R\optimization-v1\preview-coverage-v3d-step24000" --step 24000 `
    --title "Osmo Stick V3d - trajectory-carved, de-fogged"
python "$R\export-trained-cameras.py" --dataset "$R\dense" `
    --selection "$R\dense\analysis\frame-selection.json" `
    --normalization "$R\dense\geometry\normalization.json" `
    --trained-ply "$R\optimization-v1\appearance-training-v3-fast\selected\step-000024000.ckpt\splat-cleaned-v3d.ply" `
    --output-dir "$R\optimization-v1\preview-v3d-defog-controls-cameras"
node work/osmo-parity-20261101/review/production/build-stick-preview.mjs `
    "$R\optimization-v1\preview-coverage-v3d-step24000" `
    "$R\optimization-v1\preview-v3d-defog-controls-cameras" `
    "$R\optimization-v1\preview-v3d-final-cutaway"
# serve: python -m http.server 8642 --bind 127.0.0.1   (inside preview-v3d-final-cutaway)
#        python -m http.server 8648 --bind 127.0.0.1   (inside preview-coverage-v3d-step24000)

# captures
node "$R\forensic-20261104\capture-cutaway-views.mjs"  --url http://127.0.0.1:8642/ --out "$R\forensic-20261104\v3d-final-verification"
node "$R\forensic-20261104\capture-cutaway-pass2.mjs"  --url http://127.0.0.1:8642/ --out "$R\forensic-20261104\v3d-final-verification"
node "$R\forensic-20261104\capture-preview-views.mjs"  --url http://127.0.0.1:8648/ --out "$R\forensic-20261104\v3-browser-renders" --tag v3d
python "$R\forensic-20261104\assemble-v3c-vs-v3d.py"
python "$R\forensic-20261104\fog_pixel_metrics.py"
```

---

## 5. Limits

* **No eval pass this turn.** Turn 5 established that pruning itself costs ~1.0 dB masked PSNR
  (25.48 raw → 24.4 cleaned); V3d removes a further 52 % of survivors, most of them low-α, so
  the held-out score will land below 24.4. This turn was explicitly visual-first; score V3d
  with `run_masked_eval_passes.py` only if a fidelity number is needed for a ship decision.
* The 0.08 fog variant was counted (12.6 % of survivors would go) but not built; sweeping it
  needs the browser loop again, and the mandated views already read at 0.06.
* The cylinder rule uses the `k = 24` nearest centres in xz; exact `query_ball_point` over
  976 k × 6,462 pairs was not run. The approximation can only under-prune at height-boundary
  path ends, never over-prune.
* The tube is carved against **registered centres only**. Splats the operator walked past
  between captures (no camera exactly there) are untouched by Rule A and survive on Rule B
  thresholds alone — that is the residual fuzz still visible off-axis at 140 px.
* The floor inside the tube renders as a soft smear from inside the room; that region is now
  free space by construction. Dollhouse/top views show no holes.
* The ceiling cut remains a render-time clip; `occupiedShell` numbers are the exporter's fits,
  not a cleaned-geometry claim.
