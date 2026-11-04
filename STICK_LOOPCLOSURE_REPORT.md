# STICK_LOOPCLOSURE_REPORT — Phase 1: unbending the `osmo-stick-20261103` trajectory

**Status: Phase 1 ran to completion and FAILED its gate. The gate's premise is wrong — see §5.1.**
Read-only w.r.t. every preserved artifact: nothing under `dense/`, `training/`, `optimization-v1/` was modified.
All new output is confined to `.local/osmo-stick-20261103/sfm-loopclosed-v1/`.

Snapshot: 4 November 2026, Asia/Bangkok. Repository root
`C:/Users/bombe/Documents/Codex/2026-10-27/files-pasted-by-the-user-system`,
`RUN = .local/osmo-stick-20261103`, `WS = RUN/sfm-loopclosed-v1`.

---

## 0. Verdict

The loop-closed solve ran end to end (3 h 22 m, `RESULT: OK`, 1.81 px reprojection) and **all six Phase 1 gates
fail**. The reason is not a tuning failure: **the two intervals the gate wanted closed are two different rooms.**
`bathroom` (330–600) shows beige tiles, a shower hose, a seated toilet and a pink bucket; `bathroom_second`
(1560–1710) shows grey floor-to-ceiling tiles, a small high window and an extractor fan, with no fixtures at all.
`entry` and `entry_second` are two different doorways into two different wet areas. The
`same_bathroom_two_visits` entry in `room-coverage.json` is a label error, so `0` cross-visit tracks was correct
behaviour all along, and no solver can manufacture 500 shared tracks between surfaces that do not exist in both
intervals.

Handed 26,000 targeted loop proposals (8,672 specifically bathroom-1↔2, 12,428 cross-lens), the matcher verified
87.5 % of everything, the assembly stage **refused 8 merges**, and the map ended with **1** shared track, a *worse*
bend (plane residual 0.359 → 0.419 units) and **108 fewer registered timestamps**. A follow-up global bundle
adjustment (`ba --loss cauchy`, 50 iterations) recovered only 0.010 units of that. Loop closure is not the lever for
this capture; the vertical degree of freedom is unobserved, which is also why the incremental BA drifted.

What the phase did produce and keep: a working explicit-pair SfM path (`--pairs-file`, 111,148 pairs, feature cache
reused in 50 s instead of 8 m 18 s), an independent cross-visit checker validated to reproduce the baseline
exactly, and a native-units gate script. **The reference map `dense/sparse/0` is unchanged and remains the
reference**; Phases 2 and 3 stay blocked only in the part that needs an unbent map (§7).

---

## 1. Why the original map bent (root cause, verified in this turn)

`dense/analysis/sfm-native-job.json` ran `spirula sfm auto` with
`--pairs prefilter --prefilter-sequential --overlap 8 --quadratic-overlap --prefilter-neighbors 12`.
The resulting match set is a **temporal chain plus a 12-neighbour content prefilter**, which by construction
contains almost no edges between two passes of the same room:

| Evidence (from `dense/sfm-native` and `dense/geometry/normalization.json`) | Value |
|---|---|
| Candidate pairs matched | 82,791 / 84,680 |
| Registered native images | 6,462 of 6,856 (3,231 of 3,428 timestamps) |
| Registered timestamps, per lens | cam0 3,260, cam1 3,260 |
| Components produced | **5** (6,462 + 44 + 32 + 24 + 16 images) |
| `direct_cross_visit_sparse_tracks` between Bathroom 330–600 and 1560–1710 | **0** |
| `closest_cross_visit_camera_distance` | **1.223** units |
| Camera-height range (normalised, 1 unit = median camera height) | **1.4327** (`0.2398 → 1.6725`) |
| Trajectory residual to its own best-fit plane | RMS **0.3592**, extremes **−0.749 / +0.583** |
| Largest single-step camera move | **1.3102** units at frames 1846→1960 (114-frame registration gap) |

A chain-only graph cannot constrain the relative placement of two visits that share no edge, so the mapper
was free to bend vertically: each visit is internally consistent, and the two visits plus the bedroom/main-room
segments sit at mutually inconsistent heights. Everything downstream inherited that: the 4.0× preset-height
spread (`0.2965` hallway vs `1.1989` first bathroom in the shipped `cameras.json`), the closed `Hall cam0`
doorway, and the `66.39 % < 90 %` footprint rejection.

The pair-set is the defect; the solver is not. This phase therefore changes **only the pair proposal**, and
keeps every other SfM parameter, the calibration, the masks, the rig definition and the feature cache identical.

---

## 2. What was built: an explicit loop-closed pair list

Because the patched `--pairs-file` **replaces every automatic proposal** (automatic, GPS, prefilter and
rig-mate expansion all skip when it is set — see `tools/reconstruction/patches/spirula-v2026.10.30-pairs-file.patch`),
the file must be a complete substitute. It is composed of three parts.

| Part | Count | How it is generated |
|---|---:|---|
| Sequential chain (per lens, faithful to `Pairing.h::sequentialPairs`) | **81,720** | offsets 1…8 (`--overlap 8`) plus the quadratic offsets 16/32/64/128 |
| Rig mates (`cam0_t ↔ cam1_t`) | **3,428** | one pair per registered timestamp |
| Loop / revisit pairs (new) | **26,000** | bounded global retrieval + region-targeted blocks, §2.2 |
| **Total** | **111,148** | 6,883,713-byte JSON array, SHA-256 `ad8aaebb6c3423bd1e15cb21df1d9da990f245828286a967eb18c7bd5dbd85e2` |

Chain semantics were replicated from the binary's own code path (`sfm/feature/Pairing.h`):

```cpp
// Each image with the next `overlap` of its sequence and, with `quadratic`,
// the ones 2^k ahead for k < overlap (COLMAP's quadratic_overlap).
```

so a lens sequence of 3,428 images yields 12 distinct offsets per image (1–8, 16, 32, 64, 128) and the two lenses
are separate runs: 40,860 pairs per lens, 81,720 total.

**How this differs from the original match set, honestly stated.** The original `--pairs prefilter
--prefilter-sequential` set was `84,680` candidates, which decomposes as *content-prefilter pairs* + an 8-offset
chain + rig mates (a plain 8-chain is 54,790 and rig mates 3,428, leaving ≈26 k for the prefilter). That
content-prefilter component is a GPU mini-match over every pair and is not reproducible from a static list.
This phase replaces it with the region-targeted and retrieval-bounded loop families, and uses the full quadratic
chain (the `--pairs sequential` definition) instead of the plain one. Net effect: the same order of matching work,
but the ~26 k "content-similar anywhere" edges become ~26 k edges chosen to close specific seams.

### 2.1 Retrieval signal

Two global descriptors per image, both computed from **cached data only** (no images were re-decoded at full
resolution, no prior poses or matches were read):

* **mean-pooled masked ALIKED descriptor**, L2-normalised — the same construction
  `tools/reconstruction/descriptor_retrieval.py` documents, read straight from the 6,856 cached
  `VKFT v6` feature files (layout verified in this turn: 28-byte header, `count × 16 B` keypoints, then a
  contiguous `count × 128` float32 descriptor block at offset `28 + count*16`);
* **48 × 48 masked-grayscale thumbnail**, mean-subtracted and L2-normalised.

`score = 0.5 · cosine(descriptor) + 0.5 · correlation(thumbnail)`.

### 2.2 Loop families and budgets

Same-lens and cross-lens candidates are ranked and capped **separately**. A single global score cap would let
same-lens pairs crowd out the cross-lens pairs, and the cross-lens ones are what a 360 walk produces: walking
into a room `cam0` looks forward and `cam1` backward, so walking back out the *same* surface is seen by the
*opposite* lens. Cross-lens loop pairs therefore get their own budget, and at least
`--min-cross-loop-pairs 9000` of the kept loop set must connect the two lenses.

| Family | frames A | frames B | same-lens K | cross-lens K | min \|Δt\| | proposals |
|---|---|---|---:|---:|---:|---:|
| `bathroom_visit1_vs_visit2` | 330–600 | 1560–1710 | 6 | 10 | 120 | 8,672 |
| `entry_visit1_vs_visit2` | 240–300 | 1440–1530 | 6 | 10 | 120 | 1,952 |
| `exit_visit1_vs_visit2` | 660–750 | 1740–1830 | 6 | 10 | 120 | 2,912 |
| `registration_gap_bridge` | 1800–1980 | 1800–1980 | 6 | 10 | 30 | 4,755 |
| `main_room_vs_hall_transitions` | 2820–3330 | 0–239, 750–1440, 2400–2819 | 6 | 6 | 120 | 12,264 |
| `bedroom_multi_pass` | 1890–2580 | 1890–2580 | 6 | 4 | 120 | 13,072 |
| `main_room_multi_pass` | 2820–3330 | 2820–3330 | 5 | 4 | 120 | 8,600 |
| `bathroom_multi_pass` | 330–600 | 330–600 | 4 | 4 | 120 | 4,126 |
| `bathroom_second_multi_pass` | 1560–1710 | 1560–1710 | 4 | 4 | 120 | 818 |
| `bedroom_vs_main_room` | 1890–2580 | 2820–3330 | 5 | 5 | 120 | 13,705 |
| `global_retrieval` | all 6,856 | all 6,856 | 4 | 4 | 300 | 43,955 |

114,831 unique loop proposals were generated and the strongest **26,000** were kept under a cap that reserves
9,000+ for cross-lens (final kept: **12,428 cross-lens / 13,572 same-lens**). Region ranges are the project's
own `room-coverage.json` intervals, so the families are the documented room boundaries, not new guesses.

Budget rationale: the original matched 84,680 pairs in 5,612 s (15.1 pairs/s measured on that run), so ~111 k
pairs is a ~2.7 h matching stage. This analysis measured **11.5 pairs/s** for the new list, consistent with
non-adjacent pairs being more expensive per pair than chain neighbours.

---

## 3. How the solve was run (provenance and isolation)

Executable: `.local/osmo-stick-20261103/optimization-v1/spirula-build/spirula-sfm.exe`
(19,203,584 B, SHA-256 `257228de1b5b0c6e6cab9fd53eed541ba27d266f6471a98ff445ca042541ff51`,
upstream `harry7557558/spirula-studio` v2026.10.30 commit `6ad73ef`, plus
`tools/reconstruction/patches/spirula-v2026.10.30-pairs-file.patch`, self-reported as `6ad73ef-dirty`).

> The stock runtime `work/osmo-clean-20261031/runtime/spirula-2026.10.30/spirula.exe` has **no**
> `--pairs-file` (`error: unknown option --pairs-file`); the first launch attempt failed on exactly that and
> was re-issued against the patched standalone tool, whose `auto` subcommand takes the same options.

```
spirula-sfm.exe auto RUN/dense/images
  -o WS/sfm-native
  --manifest RUN/dense/sfm-manifest-native3840.json   # rigid dual-fisheye rig, cam0 fixed
  --masks RUN/dense/masks
  --camera-model opencv-fisheye --data-type video --quality high
  --features aliked-n16rot --matcher lightglue --aliked-max-features 4096 --max-image-size 1920
  --pairs sequential --sequence cam0,cam1 --overlap 8 --quadratic-overlap
  --pairs-file WS/pairs/loopclosed-pairs.json
  --focal-trials 0 --no-refine-extra-params --no-final-extra-params --no-final-principal-point
  --level ground --audit --threads 12 --device 0
```

Identical to the original job in every geometric, calibration and quality option. The only differences are the
output directory, the pair source, and `--pairs sequential` (inert once `--pairs-file` is set; it only guards the
hypothetical case of the flag being ignored).

**Feature reuse.** `dense/sfm-native/features/cam{0,1}/*.bin` (3,428 + 3,428 files, `VKFT v6`, 3,582–4,096
ALIKED features each) were **hard-linked** into `WS/sfm-native/features/` and `.resume/extract.sig` was copied
across, so the 8 m 18 s extraction stage was reused. The log confirms it:
`Features an earlier run already wrote: 6856/6856 images -- keeping them.`
No `match.sig` was copied, so matching was forced to re-run — which is the point of the phase. Hard links cost
no disk and cannot mutate the source cache.

**Isolation.** The job writes only under `WS/`; `dense/sfm-native/` (source model, matches, features) and
`dense/sparse/` (normalized model) are untouched, and `dense/geometry/normalization.json` is not rewritten.

---

## 4. Gate tooling (deterministic, re-runnable)

| Script | Role |
|---|---|
| `forensic-20261104/build_loopclosed_pairs.py` | builds/validates the pair list (§2), writes `pairs/loopclosed-pairs-provenance.json` |
| `WS/launch-loopclosed-sfm.ps1` | records `job.json` + `status.json`, launches the solve detached with logs |
| `forensic-20261104/normalize_loopclosed.py` | runs the project's own `normalize_fresh_sfm.py` on `WS/sfm-native`, producing `WS/sparse/0` + `WS/geometry/normalization.json` (rig audit, repeat-visit audit, continuity, reprojection) |
| `forensic-20261104/phase1_gate.py` | recomputes the six mandate gates from those artifacts and prints PASS/FAIL against the baseline |
| `forensic-20261104/sfm_rig_audit.py`, `pose_diagnostics.py` | unchanged analysis, now `--run-dir` parameterised so they can audit any workspace |

---

## 5. Phase 1 gate result — FAILED, and the target was wrong

### 5.1 The decisive finding: Bathroom Visit 1 and Visit 2 are different rooms

The mandate's primary gate asks for ≥ 500 shared sparse tracks between `bathroom` (330–600) and
`bathroom_second` (1560–1710), and a closest cross-visit camera distance ≤ 0.25 units. That gate presumes the two
intervals show the same room. They do not. Inspecting the source frames directly:

| Frame | Region | What the fisheye actually shows |
|---|---|---|
| `cam0/frame_000450_train.jpg` | bathroom 330–600 | beige/tan lower tiles, **white upper walls with large tiles**, chrome **shower head on a hose**, **seated toilet**, **pink bucket**, glass shelf with bottles, wall vent, ceiling lamp |
| `cam0/frame_001649_eval.jpg` | bathroom_second 1560–1710 | **uniform grey tiles floor to ceiling**, **small high window**, **extractor-fan grille**, orange floor box, dark tile band, **no fixtures at all** |
| `cam0/frame_000270_train.jpg` | entry 240–300 | view *through a dark-wood doorway* into the first bathroom (toilet, pink buckets, blue slippers) |
| `cam0/frame_001500_train.jpg` | entry_second 1440–1530 | view **through a different dark-wood doorway** into a **third** wet area: white **water heater**, curved shower screen, shelving, **squat toilet**, tan floor mat |

Four different views, two different doorways, two different sets of fixtures and two different tile schemes. The
`repeat_visit_groups: [{"name": "same_bathroom_two_visits", "region_names": ["bathroom", "bathroom_second"]}]` entry
in `room-coverage.json` — which this project's own `repeat_visit_audit` and my turn-1 report both used — is a
**label error**, and the 20–25 s corridor walk between the two intervals (750–1440) is what you would expect
between two different bathrooms in a flat, not between two visits to one.

Consequences, stated plainly:

* `direct_cross_visit_sparse_tracks = 0` in the baseline was **correct behaviour**, not a loop-closure defect.
  Two different rooms share no feature tracks.
* `closest_cross_visit_camera_distance = 1.223` units is the true distance between two different rooms.
* The Phase 1 gate G1/G2 cannot be satisfied without fabricating geometry. No solver setting can produce 500
  shared tracks between surfaces that do not exist in both intervals.
* The genuinely measured revisit in this capture is the **start/end loop** (frames ~21–61 ↔ 764–770), which was
  already closing at 0.073 units in the baseline.

### 5.2 What the loop-closed solve actually produced

Solver: `RESULT: OK -- 91% of the images registered, 1.81 px mean reprojection`, total wall clock **3 h 22 m 35 s**
(matching 2 h 04 m, mapping 1 h 18 m, assembly 42 m, finishing 25 m).

```
Matching:  02:04:07   Pairs kept: 97298/111148   Inliers: 118918316/130038265
Mapping:   01:17:51   Registered: 6246/6856 images   Points: 3523487   Cameras: 2
Assembly:  00:42:08   Models: 17 -> 6     Merged: 10   Refused: 8   Grown: 478   Coverage: 6288 -> 6392
Components: 6, covering 6392/6856 distinct images
cam0: 3196/3428 registered      cam1: 3196/3428 registered
Components: 0: 6246 | 1: 216 | 2: 66 | 3: 34 | 4: 16 | 5: 12 images
```

### 5.3 The six gates, measured on the solver's own largest component

Computed by `forensic-20261104/phase1_gate_native.py` directly on `sfm-native/sparse/0`, with heights and
distances divided by the median camera height so the numbers are in the same unit as the baseline (and as the
mandate's thresholds). Cross-visit tracks were counted by a second, independent implementation
(`crossvisit_check.py`, validated by reproducing the baseline's `0` tracks and `1.2230` units exactly).

| Gate | Loop-closed | Baseline | Threshold | Verdict |
|---|---:|---:|---:|---|
| G1 cross-visit sparse tracks (bathroom 1 ↔ 2) | **1** | 0 | ≥ 500 | **FAIL** |
| G2 closest cross-visit camera distance | **1.2857** | 1.2230 | ≤ 0.25 | **FAIL** |
| G3 camera-height plane residual RMS | **0.4188** | 0.3592 | ≤ 0.10 | **FAIL** |
| G4 preset heights within ±0.20 of median | **1.1884** (main room −1.188) | 0.6993 (hall −0.699) | ≤ 0.20 | **FAIL** |
| G5 registered timestamps | **3,123** | 3,231 | > 3,231 | **FAIL** |
| G6 no single step > 0.25 | **1.2166** (frames 1878→1969) | 1.3102 | ≤ 0.25 | **FAIL** |

Height range went from 1.433 to **1.924** units (p1 −0.161, p50 1.000, p99 1.669). Five of six metrics got
**worse**; only the largest single step shrank (1.313 → 1.217), and that only because the registration hole moved
(114 → 91 missing frames).

Where the "loop" edges went: all 8,672 bathroom-1↔2 proposals were matched, and the assembly stage **refused 8
merges** (baseline refused 6). The solver was offered the merge and declined it on geometry — which is the correct
answer for two different rooms, and it is also why the map did not improve.

### 5.4 Honest attribution limit

This A/B is **not** a one-variable experiment. The pair set changed in three ways at once: the loop families were
added, the GPU content-prefilter pairs (~26 k in the baseline) were removed, and the full quadratic chain replaced
the plain 8-chain. The −108 timestamps and +0.06 plane RMS cannot be attributed to the loop edges alone. What *can*
be attributed is the merge outcome: the solver was given thousands of verified cross-visit edges and still produced
1 shared track between the two bathrooms.

### 5.5 The two follow-up measurements the mandate asked for

**Start/end revisit — the only genuine loop in this capture** (frames 1–70 vs 750–790, both lenses, in normalized
units):

| | baseline | loop-closed |
|---|---:|---:|
| Closest approach of the two passes | **0.0723** | 0.0760 |
| Nearest later pose (≥300 frames) p50 / p10 | 1.009 / 0.258 | 1.059 / 0.265 |

The real closure neither tightened nor broke; the new pair set added ~5 % noise to the general revisit statistic.

**Global bundle adjustment on the merged model** (`spirula-sfm ba 0 0-ba --loss cauchy --max-iters 50`,
50 iterations, 7 accepted, 146 s, 7.7 GB VRAM):

| Metric | before BA | after BA | baseline | threshold |
|---|---:|---:|---:|---:|
| Camera-height plane residual RMS | 0.4188 | **0.4088** | 0.3592 | ≤ 0.10 |
| Preset max abs offset | 1.1884 | **1.1061** | 0.6993 | ≤ 0.20 |
| Max single step | 1.2166 | 1.3908 (frames 2675→2676) | 1.3102 | ≤ 0.25 |
| Cross-visit tracks | 1 | 1 | 0 | ≥ 500 |

BA shaved 0.010 units off the bend — two orders of magnitude short of the target — and loosened one pose into a new
single-frame jump. The vertical DOF is unobserved by this pair graph, which is the same reason incremental BA
drifted. Reported, not worked around: no height warping was applied, because that would fabricate the geometry the
gate exists to measure.

---

## 6. Interpretation and risk

### 6.1 What this experiment established

1. **The loop-closure target does not exist.** Two different bathrooms were relabelled as two visits to one. Every
   number that turn 1 reported from `repeat_visit_audit` (`0` shared tracks, `1.223` units apart) was a faithful
   reading of the audit — and the audit was reading a wrong region label. This is the single most important finding
   of Phase 1 and it was only visible by looking at the pixels.
2. **Loop closure is not the lever for this capture's bend.** With 26,000 targeted loop proposals — 8,672 of them
   specifically bathroom-1↔2, 12,428 cross-lens to catch the reverse-direction case — the matcher verified 87.5 %
   of all pairs and the assembly stage still refused 8 merges and produced 1 shared track between the two rooms.
   There is nothing to close.
3. **A robust global bundle adjustment does not flatten the bend either.** `spirula-sfm ba --loss cauchy
   --max-iters 50` on the merged 6,246-image model (50 iterations, 7 accepted, 146 s) moved the plane residual from
   0.4188 to **0.4088** units and left the preset spread at 1.106 units. The vertical DOF is simply unobserved:
   every view is nearly horizontal, there is no gravity sensor, no floor plane and no metric anchor, so no sequence
   of pairwise constraints pins height. This is the same reason incremental BA drifted in the first place.
4. **The bend therefore needs a constraint this SfM does not have.** Options, in order of cost:

   | Route | Mechanism | Cost | Verdict |
   |---|---|---|---|
   | per-room `train --partition` | never asks one floor plane to fit the whole flat; each part trains and merges in the viewer | moderate; trainer already supports `partition` | **best value**, sidesteps the global-floor assumption that also broke the footprint gate |
   | MoGe-2 depth/normal supervision | pins each view's surface scale/shape to a learned prior, so the *model* is consistent per view even if the camera chain is bent | moderate | **recommended**, and already planned in Phase 3 |
   | custom soft height prior in BA | add a residual on camera Y to a pycolmap BA (spirula `ba` exposes no such flag — verified from `ba --help`) | high, new code, and a prior is a modelling choice the project has not approved | research task only |
   | floor plane from the trained model as a BA constraint | needs the model to be right first | circular | reject |

5. **Separate, real defects that this run did expose** and that are worth fixing regardless of the bend: the
   registration holes are not random. They sit on the empty-mask cohorts (386–415, 431–434, 1681–1696) and on the
   doorway turn at 1847–1959 — the largest jump in the map (1.22–1.39 units) is always at a hole edge. Those frames
   are lost because the operator crosses a doorway with contaminated masks, not because the pair graph is thin.

### 6.2 Risk register

* **Do not relax the gate to make this run look acceptable.** `normalize_fresh_sfm.py` refused to select a component
  here because the largest holds 6,246/6,856 = 91.1 % of images but only 88.2 % of *timestamps* pair-complete, below
  its 0.90 rule. Lowering `--min-registration` to get a normalized model out of this workspace would convert a
  truthful refusal into a silent acceptance. The gate numbers above were therefore computed independently of that
  selection step.
* **Do not treat the loop-closed map as a replacement reference.** It registers 108 fewer timestamps, bends more,
  and has one extra component. `dense/sparse/0` remains the reference for Phase 3.
* **The pair-set capability is reusable** even though this experiment failed: `--pairs-file` works end-to-end on
  111 k explicit pairs (97,298 verified), and the feature cache can be reused through hardlinks in ~50 s instead of
  8 m 18 s. That machinery is the right tool for a *real* revisit, of which this capture has exactly one
  (start/end, 0.073 units).

---

## 7. Revised plan, and what the Architect must decide

Phase 1 as written cannot pass, so Phases 2 and 3 stay blocked **only in the part that depends on an unbent map**.

1. **Fix the data label first (5 minutes).** `RUN/room-coverage.json` → `repeat_visit_groups` currently asserts
   `same_bathroom_two_visits`. The imagery shows two different bathrooms and two different doorways. Correct the
   label so `repeat_visit_audit` stops reporting a real, benign separation as a closure failure. Everything
   downstream that cites "0 cross-visit tracks" — including my own turn-1 report — must carry that correction.
2. **Re-scope Phase 1** to what is actually broken: the two registration holes (1830–1960, and the empty-mask
   cohorts inside both wet rooms), not a nonexistent loop. Measurable target: recover the 113-frame hole and get the
   largest component back above the 0.90 registration rule, with the pair list unchanged from the baseline recipe
   plus *genuine* revisits only.
3. **Unblock Phases 2 and 3 on the existing reference map.** The splat and priors defects from
   `STICK_INVESTIGATION_REPORT.md` — cap saturation at 1.7 M with `num_added = 0`, 62.5 % needle-shaped visible
   splats, missing MoGe-2 supervision, under-converged bilateral grid — are **independent of the trajectory bend**.
   Correcting them on `dense-pinhole-1200` (or on the V2 selection) does not require an unbent map and does not
   depend on this phase's outcome. Recommended order: `cap_max 4 M`, MoGe-2 `depths/`+`normals/` with the
   supervision weights in §10.3, camera optimizer on, `bilagrid_tv_loss_weight 50` / `bilagrid_adagrad_lr 0.01`,
   train to 24 k–32 k.
4. **Handle the dollhouse per-room, not globally.** The footprint gate assumes one floor/ceiling pair. With a bent
   map that assumption fails at 66 %; with per-room partitions it becomes a per-partition fit and the single-global
   plane requirement disappears. Keep `cutawaySupported: false` until a per-room shell carries its own evidence file.
5. **If a vertical constraint is still wanted**, it needs new code (a soft height residual in a pycolmap BA) and an
   explicit Architect decision that a prior is permitted. It is not a parameter a flag can switch on: `spirula-sfm
   ba --help` exposes only solver knobs (`--solver`, `--max-iters`, `--damping`, `--rtol`, `--patience`,
   `--cg-iters`, `--cg-fallback`, `--vram-budget`, `--device`, `--loss`, `--loss-param`, `--rig`, `--real`).

---

## 8. Reproduction

Measured wall clocks on the recorded hardware (RTX 5080, 12 threads): pair list 2 m 03 s, matching **2 h 04 m**
(111,148 pairs, 12.3 pairs/s), mapping 1 h 18 m, assembly 42 m, finishing 25 m, **total 3 h 22 m 35 s**;
bundle adjustment 146 s; the gate itself ~90 s per model.

```powershell
# 1. pair list (CPU, ~2 min)
& C:/Python314/python.exe -B RUN/forensic-20261104/build_loopclosed_pairs.py `
  --features RUN/dense/sfm-native/features --images RUN/dense/images `
  --output WS/pairs/loopclosed-pairs.json --provenance WS/pairs/loopclosed-pairs-provenance.json `
  --overlap 8 --quadratic

# 2. stage (hardlinked feature cache + extract.sig) and solve
pwsh -NoProfile -File WS/launch-loopclosed-sfm.ps1

# 3. the six gates, computed directly on the solver's model (native -> normalized units)
& C:/Python314/python.exe -B RUN/forensic-20261104/phase1_gate_native.py `
  --workspace WS --component 0 `
  --output RUN/forensic-20261104/phase1-gate-native.json

# 3b. independent second reading of the two loop figures
& C:/Python314/python.exe -B RUN/forensic-20261104/crossvisit_check.py `
  --model WS/sfm-native/sparse/0 --normalization WS/geometry/normalization.json

# 4. optional: global bundle adjustment, then re-gate with --component 0-ba
& .local/osmo-stick-20261103/optimization-v1/spirula-build/spirula-sfm.exe `
  ba WS/sfm-native/sparse/0 WS/sfm-native/sparse/0-ba --loss cauchy --max-iters 50 --device 0
```

`RUN/forensic-20261104/normalize_loopclosed.py --apply` is also wired up (it runs the project's own
`normalize_fresh_sfm.py` against this workspace), but on this solve it refuses by design: its
`--min-registration 0.90` rule is not met, because the largest component holds 91.1 % of the *images* but only
88.2 % of the *timestamps* pair-complete. That refusal is the correct outcome and was not lowered — the gate
numbers in §5.3 come from `phase1_gate_native.py`, which does not depend on that selection step.

## 9. Limits of this phase

* Nothing here is an appearance or quality acceptance decision; Phase 1 only moves geometry.
* The retrieval signal is an appearance heuristic, not a verified-overlap certificate. False proposals are
  expected and are rejected downstream by LightGlue + RANSAC (`--min-inliers 15` default) and the mapper's own
  gates; the phase is judged by the resulting **geometry**, never by proposal count.
* Gate numbers are computed in the project's normalized frame (median camera height = 1 arbitrary unit,
  `metric_scale_known: false`), so they are relative, not surveyed, tolerances.

---

## 10. Appendix — Phase 2/3 commands prepared (NOT executed this turn)

Recorded here so the next phase runs from fixed text rather than a paraphrase. Nothing below was run.

### 10.1 Which timestamps the old map lost (what Phase 1 has to recover)

The baseline registered 3,231 of 3,428 timestamps; the 197 missing ones are not spread evenly but form eight
runs, and three of them sit on the mask-failure cohorts:

| Missing run | Frames | Region | Note |
|---|---:|---|---|
| 386–392, 400–415, 431–434 | 27 | first bathroom | inside the empty-mask cohort 360–435 |
| 645–664 | 20 | exit_first | |
| 1287–1289 | 3 | corridor | |
| 1681–1696 | 16 | second bathroom | adjacent to the 1680→1697 jump (0.285 units) |
| **1847–1959** | **113** | pre-bedroom | the 114-frame hole; 43 of 60 frames in 1830–1890 lost (71.7 %) |
| 2587–2604 | 18 | post-bedroom | |

Component 0 held all 6,462 registered images; the four extra components held 116 images total, so 168
timestamps were registered nowhere. The gap family (`1800–1980`, cross-lens) and the bathroom families target
exactly these runs.

### 10.2 Phase 2 — staging with the unbent poses, seed export, MoGe-2 priors

```powershell
# (a) whitelists — the V2 selection is 2,678 views (all split=train) inside
#     appearance-coverage-v2-reviewed-final/training-views.json["views"], filter selected=true.
#     The eval set is 114 timestamps x 2 lenses = 228 names, frame % 30 == 29, from frame-selection.json.
#     (build_explicit_pinhole.py takes JSON views[].image or a plain name list; it does NOT filter
#      `selected` itself, so hand it a pre-filtered list or the whole capture would be staged.)

# (b) stage the unbent dataset with the V3 poses — never reuse the old poses
& .local/reconstruction-bench-env/Scripts/python.exe work/osmo-clean-20261031/build_explicit_pinhole.py `
  --source RUN/sfm-loopclosed-v1/sparse/0 `
  --output RUN/optimization-v1/appearance-coverage-v3-unbent `
  --subset all --size 1200 --workers 2 `
  --images-dir RUN/dense/images --masks-dir RUN/dense/masks `
  --selection RUN/dense/analysis/frame-selection.json `
  --train-whitelist RUN/optimization-v1/appearance-coverage-v3-unbent/train-whitelist.json `
  --eval-whitelist  RUN/optimization-v1/appearance-coverage-v3-unbent/eval-whitelist.json

# (c) geometry priors — NOTE: --depth is OFF by default in this build; normals-only otherwise
& work/osmo-clean-20261031/runtime/spirula-2026.10.30/spirula.exe geometry `
  RUN/optimization-v1/appearance-coverage-v3-unbent `
  --model moge2-vitl --depth --depth-units relative --max-size 1064 --num-tokens <N>

# (d) seed export: >=3 observations, <=2.0 px, operator-mask clean, voxel-downsampled
#     to 1.5-2.0 M points so cap_max is not saturated at step 1
```

Build options: `spirula geometry` accepts `--model {moge2-vits|moge2-vitb|moge2-vitl|moge3-vitl|metric3d-*|marigold-v2}`;
the mandate's `moge2-vitl-normal` is the id `moge2-vitl`, and `--depth` must be passed explicitly or the stage writes
`normals/` only. `--face-res {output|source}` decides whether a split samples the frame at the written map size or
at the frame's own resolution — it changes inference cost by several times, so fix it deliberately and record it.

Two ways to feed the trainer; pick one and record it: run geometry on the **staged face dataset** (13,390 images,
so `depths/` and `normals/` sit next to `images/` exactly as the loader expects), or run it on the 2,892 native
views and extend the warper to emit face depth/normal maps. The staged-face route needs no new warper code.

### 10.3 Phase 3 — training recipe deltas from the audited baseline

Baseline config (`RUN/training/stick-dense-1200-rgb-recovery1/config.json`) changed by:

| Setting | baseline | Phase 3 | why |
|---|---:|---:|---|
| `cap_max` | 1,700,000 | **4,000,000** | the cap was saturated at init; `num_added` was 0 in all 134 logged steps |
| `load_depths` / `load_normals` | 0 / 0 | **1 / 1** | no surface constraint existed at all |
| `depth_supervision_weight` | 0 | **0.05** | ray-depth (with `input_depth_is_ray_depth 1`) |
| `normal_supervision_weight` | 0 | **0.02** | |
| `normal_reg_weight` | 0 | **0.03** | |
| `max_world_size` | 0.12 | **0.08** | the cap permits 0.12-long needles against a 1.6e-13 short axis |
| `scale_reg` | 0.01 | **0.02** | |
| `use_camera_optimizer` | false | **true** | residual pose jitter was baked into splats |
| `bilagrid_tv_loss_weight` | 10 | **50** | a 16×16 grid that can imprint cellular patches |
| `bilagrid_adagrad_lr` | 0.04 | **0.01** | |
| `num_iterations` | 32,000 | 32,000 (unchanged) | a resume must keep the schedule; save at 6 k/15 k/24 k/32 k |
| `steps_per_save` | 2,000 | 6,000 + explicit 15,000 | |

Then re-run `RUN/export-trained-cameras.py` and require `near_fraction >= 0.90`; a pass unlocks
`occupiedShell` and `cutawaySupported: true` through the existing gate, with no threshold change.

If Phase 1 closes the loops but a residual low-frequency bend survives, the legitimate next move is a
**bundle adjustment over the merged model** rather than any height warping:

```powershell
spirula-sfm.exe ba RUN/sfm-loopclosed-v1/sfm-native/sparse/0 RUN/sfm-loopclosed-v1/sfm-native/sparse/0-ba `
  --loss huber --loss-param 2
```

`ba` reads the rigs from the model's `rigs.txt` unless `--rig` overrides them, so the rigid dual-fisheye
constraint is preserved. Warping camera heights by hand is not an option: it would fabricate the geometry the
gate is supposed to measure.
