# STICK V3e final — edge-on disk streaks fixed, seed-supported floaters pruned, deployment-ready

Turn-7 report. English. Zero GPU training: one **3.6 s** CPU cleaner, one 112 s camera export,
one 1.4 s SPZ pack, one site build, headless-Chrome captures. V3c/V3d artifacts untouched.

---

## 0. Verdict

| Check | Result |
|---|---|
| Step 1 — `clean_v3e_edgeon_and_seed.py` | **3,395,393 → 749,721 splats (−77.9 %)** in **3.6 s**. V3d stages reproduced exactly (976,629 identical survivors), then **Rule C pruned 112,196** unsupported floaters and **Rule D pruned 123,965** near-field wafers + clamped **70,328**. |
| Row 4 (orbit-140 px needle fan) | **Substantially cleaned** — the dark streak fan near the drawer tower is reduced to a few short faint marks; the edge-on wafer hypothesis was the right one. |
| Row 3 (bathroom tiles) | Still **zero pinholes** (no isolation rule, on-surface surfels untouched). |
| Row 5 (drawer tower) | Edges, labels and bin colours **unchanged** — the Rule D thickness clamp never touched crisp on-surface opaque surfels. |
| Step 2 — footprint gate on V3e | **`cameraNearFootprintFraction = 1.0`** over 6,462 cameras; `occupiedShell` populated (`floorY −0.02986`, `ceilingY 2.08587`, 48 interior cameras). |
| Pack | **13.6 MB** `model.spz` (V3d 17.8 MB → V3c 42.3 MB → V2 30.2 MB), SPZ v3, SH-2, mip retained. |
| Site | Shared-controls cutaway rebuilt and **serving at http://127.0.0.1:8642/** (V3d site replaced on that port). |

---

## 1. Step 1 — what ran, per rule (all counts incremental/disjoint)

Stages 1, A, B are byte-identical to V3d's run (same input, same thresholds): survivors after
Rule B = **976,629**, matching `STICK_V3D_DEFOG_REPORT.md` exactly.

### 1.1 Seed-support distances (new measurement)

`cKDTree` over the **1,996,179** multi-view triangulated points of
`appearance-coverage-v2-fixed-reference/seed-clean-2m.ply`; `d_seed_k3` = distance to the
3rd-nearest seed point; `d_cam` = distance to the nearest of the 6,462 registered centres.

| percentile of the 976,629 V3d survivors | `d_seed_k3` | `d_cam` |
|---|---:|---:|
| p50 | **0.0188** | 0.658 |
| p90 | 0.0376 | 0.976 |
| p99 | 0.1192 | — |

Most survivors hug triangulated geometry (median 1.9 cm); the Rules only touch the tail.

### 1.2 Rule C — unsupported mid-air floaters

| rule | splats |
|---|---:|
| far floater: `d_seed_k3 > 0.045`, `y > 0.08` (not floor), and (`α < 0.55` OR `d_cam < 0.75` OR `s2/s1 > 10`) | **44,247** |
| corridor: `0.28 ≤ d_cam < 0.65`, `d_seed_k3 > 0.025`, and (`α < 0.45` OR `s2/s1 > 8` OR `s3/s2 > 2`) | **67,949** |
| **Rule C subtotal** | **112,196** |

### 1.3 Rule D — edge-on razor disks

Target set: (`d_seed_k3 > 0.020` OR `α < 0.35`) AND `s2/s1 > 12` AND `s3 > 0.004` — i.e. flat,
thin, off-surface-or-transparent wafers. Crisp on-surface (`d_seed_k3 ≤ 0.020`, `α ≥ 0.35`)
surfels are excluded by construction.

| action | splats |
|---|---:|
| prune near-field wafers: `d_cam < 0.80` AND `α < 0.28` | **123,965** |
| thickness clamp on the rest: `s1 ≥ s2/5` and `s3 ≤ 1.8·s2` | **70,328** targeted — 21,199 `s1` actually raised, 16,072 `s3` actually lowered |
| **final** | **749,721 splats** (22.1 % of raw, 76.8 % of V3d) |

Post-run structure: `α < 0.10` share 21.2 %, median α 0.224, needle ratio p99 3.10 / max 3.20.

---

## 2. Step 2 — gate, pack, site, screenshots

| audit field | value |
|---|---|
| `trainedGaussians` | 749,721 |
| `opaqueSampleCount` | 119,787 (V3d 115,246, V3c 57,755 — rises as haze is removed) |
| **`cameraNearFootprintFraction`** | **1.0** (≥ 0.90 required) |
| `occupiedShell` | populated — `floorY −0.02986`, `ceilingY 2.08587`, 48 interior cameras, footprint `sdfCm`/`lowerCeiling`/`wallBand`/`exteriorMargin` |

Pipeline: `prepare-coverage-v3-preview.py` → `preview-coverage-v3e-step24000` (13.6 MB spz,
**1.4 s**) → `export-trained-cameras.py` (112 s) → `build-stick-preview.mjs` →
`preview-v3e-final-cutaway` → `python -m http.server 8642` (HTTP 200 verified; the V3d site
that held 8642 was stopped; V3d's pack preview stays on 8648, V3e's pack on 8649).

Captures: 16 screenshots in `forensic-20261104/v3e-final-verification/` (entry, orbit, top,
see-inside, dollhouse orbit, A1–D4/E1 recorded views, B1/C1 wall-through controls) plus 9
pack views `v3-browser-renders/v3e-*.png` for the crops.

## 3. Step 3 — visual comparison (sheet: `v3e-final-verification/v3d-vs-v3e-dollhouse-and-zoom.png`, V3d left / V3e right)

| row | reading |
|---|---|
| 1 entry overview | Shell edge tighter, the floating white halo around the apartment reduced, the bright cyan speckle cluster bottom-centre smaller and dimmer; rooms/furniture still read clearly. |
| 2 top-view floorplan | Crisper: fewer white wisps over rooms, same readable floorplan, no new holes in walls or floor. |
| 3 bathroom tiles | Both smooth; **no pinholes** in V3e; slightly less milk overlay. |
| 4 orbit-140 px needle fan | **The mandated fix lands:** V3d's dense dark streak fan over the pink/cyan surface is reduced to a few short faint marks. |
| 5 drawer tower | Edges and bin colours unchanged — the clamp did not soften any texture. |

In-room `A1` (recorded 101 s): curtain, drawer tower, shelf stack, sofa all intact and
visually identical to V3d, with fewer mid-air wisps around the shelf tops.

---

## 4. Deployment — executed and publicly verified (5 November 2026)

Shipped artifact: `optimization-v1/preview-v3e-final-cutaway/` (index.html 16.8 kB, room.json
660 kB, `model.spz` **13,628,582 B, sha256 `21522886976ec995b9407b5eb9eb35fa63a36c18349bdc9775496e2c6f1c0917`**,
7 photos, chunks). Note to §4's earlier one-liner: this workstation reaches Proxmox through
`work/hosting/remote.py` (SSH/SFTP via `.local/hosting-access.json`), not local `pct`; the
§4 transport was corrected accordingly. Actual deploy path:

1. `remote.py --put` staged `osmo-stick-v3e-cutaway.tgz` (17,863,192 B, sha256
   `a8409e5f1c3fdcbbf60ec0f50b28a92c2bd17b73c48d2b9ce2c1e276d0e22c70`), both hash manifests and
   `deploy-v3e-cutaway.sh` into `/var/lib/vz/rumah-deploy/` (host-side sha256 re-check: OK).
2. `remote.py --script deploy-v3e-cutaway.sh` under `/var/lib/vz/rumah-deploy/native-release.lock`:
   asserted live release `20261103-osmo-viewer-v4` and the old chooser symlink target, extracted
   into `previews/osmo-stick-v3e-cutaway.partial`, verified `model.spz`/`index.html`/`room.json`
   hashes inside the container, atomic `mv -T`, created
   `$live/preview/osmo-stick-v3e-cutaway`, atomically repointed
   `$live/preview/osmo-stick-coverage-v2-step6000` to the same directory, re-verified the
   main-site release hashes (iPhone GLB, GLB.gz, Held SOG, room/viewer bundles: **OK**; live
   `index.html` intentionally differs from the release manifest — it is the 3 November chooser
   publish, sha `1a532d01…`), `nginx`+`cloudflared` **active**. Rollback dir
   `previews/osmo-stick-coverage-v2-step6000-shared-controls` untouched; rollback is a symlink
   flip. Receipts: `.local/osmo-stick-20261103/deploy-v3e/deploy-run-receipt.txt` and
   `post-deploy-state.txt`.
3. Public verification (`forensic-20261104/public-v3e-verification/`, receipt JSON + 10 PNGs):
   both `https://rumah.shizuku.rest/preview/osmo-stick-coverage-v2-step6000/` and
   `/preview/osmo-stick-v3e-cutaway/` — **zero model requests before the Open click**, model.spz
   transfer exactly **13,628,582 bytes** on both, Dollhouse entry rendered, Top view, See inside
   and Walk exercised, **zero console/page errors**. The temporary local preview servers on ports
   8642/8643/8646/8648/8649 were stopped after verification.

---

## 5. Reproduction

```powershell
$R = "C:\Users\bombe\Documents\Codex\2026-10-27\files-pasted-by-the-user-system\.local\osmo-stick-20261103"

# Step 1 (3.6 s)
python "$R\forensic-20261104\clean_v3e_edgeon_and_seed.py"

# Step 2
python "$R\prepare-coverage-v3-preview.py" `
    --source "$R\optimization-v1\appearance-training-v3-fast\selected\step-000024000.ckpt\splat-cleaned-v3e.ply" `
    --out "$R\optimization-v1\preview-coverage-v3e-step24000" --step 24000 `
    --title "Osmo Stick V3e - seed-supported, edge-on guarded"
python "$R\export-trained-cameras.py" --dataset "$R\dense" `
    --selection "$R\dense\analysis\frame-selection.json" `
    --normalization "$R\dense\geometry\normalization.json" `
    --trained-ply "$R\optimization-v1\appearance-training-v3-fast\selected\step-000024000.ckpt\splat-cleaned-v3e.ply" `
    --output-dir "$R\optimization-v1\preview-v3e-controls-cameras"
node work/osmo-parity-20261101/review/production/build-stick-preview.mjs `
    "$R\optimization-v1\preview-coverage-v3e-step24000" `
    "$R\optimization-v1\preview-v3e-controls-cameras" `
    "$R\optimization-v1\preview-v3e-final-cutaway"
# serve: python -m http.server 8642 --bind 127.0.0.1  (inside preview-v3e-final-cutaway)
#        python -m http.server 8649 --bind 127.0.0.1  (inside preview-coverage-v3e-step24000)

node "$R\forensic-20261104\capture-cutaway-views.mjs" --url http://127.0.0.1:8642/ --out "$R\forensic-20261104\v3e-final-verification"
node "$R\forensic-20261104\capture-cutaway-pass2.mjs" --url http://127.0.0.1:8642/ --out "$R\forensic-20261104\v3e-final-verification"
node "$R\forensic-20261104\capture-preview-views.mjs" --url http://127.0.0.1:8649/ --out "$R\forensic-20261104\v3-browser-renders" --tag v3e
python "$R\forensic-20261104\assemble-v3d-vs-v3e.py"
```

---

## 6. Limits

* **No eval pass this turn** (same policy as V3d): V3e removes another 227 k survivors beyond
  V3d, so held-out masked PSNR will land below V3d's expected value; run
  `run_masked_eval_passes.py` if a ship decision needs the fidelity number.
* The seed tree is the *V2-era* triangulation (`seed-clean-2m.ply`). Surfaces that only the
  V3 rebuild discovered (thin objects the seed under-sampled) sit in the `d_seed_k3` tail and
  were protected only by their opacity/shape: genuinely new high-opacity flat content with
  `s2/s1 > 12` got thickness-clamped, not deleted — the safe failure mode.
* `d_cam` corridors (`0.28–0.65`, `< 0.80`) are in normalized scene units where the walk-path
  clearance is 0.28; they were transplanted unchanged from the mandate.
* The residual streaks visible in row 4 are the population that walked **between** registered
  centres (no camera exactly there) and is opaque enough (`α ≥ 0.28`, near seed) to survive
  every rule — removing it would need either denser registration or a training-time fix.
* Same shell-fit caveat as V3d: the ceiling cut is a render-time clip, not cleaned geometry.
