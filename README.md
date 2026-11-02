# Rumah: apartment reconstruction and web viewer

## 1. Project Overview & Live Production Status

[rumah.shizuku.rest](https://rumah.shizuku.rest/) offers three reconstructions of an apartment. Visitors choose a model and press **Open model** before the viewer or model downloads. Deep links preselect a choice; they do not bypass Open.

| Choice | Native payload | Representation and identity |
|---|---:|---|
| **iPhone Fast (Lite)** | 21,144,604 bytes / 21.1 MB | Textured GLB mesh, A003 |
| **iPhone Full** | 435,614,584 bytes / 435.6 MB | Full native GLB mesh, A001 |
| **Osmo 360** | 44,904,208 bytes / 44.9 MB | Gaussian SOG, existing A018 with the updated viewer |

Sizes are decimal, before optional HTTP gzip. SOG is a Gaussian splat archive, not a triangle mesh. Surface extraction and photo-textured GLBs are separate experimental outputs.

**Current live release: 20261103-osmo-viewer-v1.** Sources: work/osmo-parity-20261101/review/production/. DavidN8 PRs #1 and #2 are approved and merged. The viewer adds the fitted layout overview, improved cutaway/framing/controls and display sharpening. Inferred walls and furniture are explicitly labeled on desktop and phones; **View photographic scan** opens the actual Gaussian Walk view. No retraining was launched. The existing A018 photographic sharpness remains unaccepted, and physical Fold 7 / iPhone 17 validation remains unverified. [Integration and release evidence](docs/release-2026-11-03/README.md). The former live release, 20261031-osmo-clean-v1, is retained on the server for rollback.

**Historical reconstruction review: 20261101-osmo-parity-review**, in work/osmo-parity-20261101/. Viewer controls, occupied room bounds (occupied_bounds.py), and dollhouse/top/reversible-shell UI behavior are **implemented and verified**. **Model sharpness, surface quality and outside cutaway visuals failed acceptance.** The 1600px/50k Gaussian remains soft; cutaway artifacts persist; sharper textured surfaces have wrong geometry. review/production/release-approval.json has **approvedForDeployment: false**.

**2026-11-02 cutaway rework (deployed as a viewer update on 2026-11-03; photographic reconstruction quality remains unaccepted).** The overview cutaway uses the room's real, non-convex footprint instead of the convex hull of the dense seed. The hull covered about 20% more area than the room, so concave corridor/bathroom walls were never cut and the halo of unobserved exterior splats stayed visible. occupied_footprint.py derives the footprint from opaque flat splats on the fitted floor, upper ceiling and a detected dropped ceiling (y≈2.00, about half of the apartment), then trims it to the floor the capture path reaches without crossing wall evidence (opaque vertical splats over more than half of the 0.3-2.0 band and reaching above 1.6, so a metre-high shelf or a 1.4 high bedding stack against a wall stays furniture in front of it). Raw floor evidence ran 0.1-0.5 past the walls (doorways, reflections, blur) and left a fuzzy belt of wall-top shards inside the cut; wall faces now sit 0.05-0.20 outside the edge (61% of opaque vertical splats within 0.5 of it; furniture fronts stay inside). It stores a signed-distance grid, a per-cell local-ceiling selector, the wall band (0.25) and the exterior margin (0.22) in occupiedShell.footprint. gaussian-cutaway.js reads them from one RG8 texture per splat and hides the following whenever See inside is on (the default in Orbit/Top; Walk starts with it off): splats whose 2σ reach crosses the wall line; the wall layer that faces the camera or stands on the camera's side of the orbit target (jog walls would read as free-standing fins); the local ceiling; anything outside the floor–ceiling volume; needles near the shell and long needles anywhere. **Fitted shapes in the overview:** when the shape file below is present, the Orbit/Top overview draws its walls (dark tops, doors, curtained windows) and furniture as simple shapes, over the photoreal splat floor, with the fitted floor (unlit, in the scan's floor colour) just under it. Walls that face the camera or stand on its side of the room drop to 0.35 stubs, so every room keeps its outline. It hides every splat standing on the floor (the model is soft on cluttered furniture and the soft splats read as blur next to crisp walls), large soft blobs (they read as stains; the fitted floor shows there), splats within 0.08 of the footprint edge, needles near it, and the clutter band along cut walls. Walls stay full height as shapes; there is no cabinet-height cut. Walk keeps the photoreal room, even with See inside on. Orbit and Top square up to the walls (the shape file's Manhattan yaw), centre the room and fit it to the screen; Top uses a 12° lens so it reads as a plan. Walk starts where a photographer would stand: from a capture position, back toward the wall behind and looking along the longest open sightline, at the recorded eye height and 10° down, with a 75° horizontal lens (at most 75° tall on a portrait phone). The downloaded model is unchanged. The model hash, the four acceptance gates and the release approval are untouched: visual acceptance is still the architect's call. Regenerate with `python -B occupied_footprint.py review/qa/new-full-50000.ply review/occupied-cameras.json review/calibrated-occupied-cameras.json` (from work/osmo-parity-20261101, NumPy+SciPy+Pillow). While the camera moves, the cutaway regenerates at most every 100 ms (about 10 times per second of motion instead of once per frame) and once more when the camera rests. A 90-frame orbit drag at 120 Hz went from 90 full regenerations to 8-9; at 60 Hz the same drag would give about 16. Cuts at the wall line and on camera-facing walls fade over a short alpha ramp instead of switching on and off.

**Sharpening (local).** The Gaussian model is soft (the sharpness gate above), most visibly on small, cluttered objects; moving the camera does not change that. The viewer now sharpens finished Gaussian frames with contrast-adaptive sharpening (sharpen.js, strength 0.9 of 1; 0 leaves the frame as it is): it copies the rendered canvas and draws it back through a CAS shader, so splats still blend in the display space they were trained in. At 2x pixel density it raises the mean edge gradient of the walk view by 30% at the same mean brightness; letterbox bars and draw-call diagnostics are untouched. On localhost, `?ablation=1&sharpen=0` turns it off for A/B. The block model is not sharpened.

**Simple shapes view (local).** The Osmo viewer has a **Simple shapes** toggle that swaps the Gaussian model for a block model of the same rooms: floor and ceiling slabs, walls, and one box or cylinder per piece of furniture, coloured from the splats it replaces. simple_shapes.py fits it from the 50k model and the footprint. Everything is snapped to the room's dominant direction (about -26°). The plan is the floor the capture path reaches without crossing wall evidence, squared off, snapped to a 0.2 grid and straightened (steps up to 0.2 become straight edges), so floor and walls share one clean outline. Walls are extruded around it in one off-white with dark tops, up to the higher ceiling, with no overlapping corners; dark wood-coloured runs 0.6-1.3 wide become door openings with a lintel and a recessed leaf, and dark cool-coloured runs 0.6-3 wide curtained windows. Each ceiling level is one flat slab set with a solid step between them; dropped-ceiling fragments under 1 square unit are ignored. Furniture is split into 2.5D pieces by top height, using material below the dropped-ceiling line only (soffits and the AC above it would otherwise hide what stands beneath) and including soft, semi-transparent splats; a second pass below 0.65 finds what a tabletop or an overhang hides, splitting a packed blob (bottles and chairs under a table) into items. Pieces are squared to the walls, stood on the floor and kept inside the plan; one whose top run starts high still stands when solid material ends at most 0.3 below it (a shelf with things on top). A piece with open space under most of its top becomes a table (top and four legs), and a round one (empty corners, no long axis) a cylinder. Floating pieces and thin, tall ones (an open door, a jamb) are dropped. Item-sized pieces may sit under a table; other overlaps are cut back, so no two shapes intersect. Colours are the median of each piece's side-facing splats (a table's top surface) without the darkest quarter: many splats carry a dark base colour and get their brightness from view-dependent terms. The result is review/simple-shapes.json (12.2 KB, deterministic): 85 shapes, namely 9 floor slabs, 13 ceiling slabs, 41 wall pieces (with lintels, door leaves and curtains) and 22 objects (81 boxes, 4 cylinders in all), checked against the packed model's source hash. It is lit by an overhead key light and a warm fill, with soft shadows in the angled orbit view only (from straight above or under a ceiling they read as level changes); furniture is outlined. prepare-deploy.py packages it with the release and checks its size and content hash. build.mjs copies it into public/ and records the Manhattan yaw for the orbit views. The viewer fetches it after the Gaussian model loads (for the overview walls); the overview hides ceilings and cuts camera-facing and near-side walls to stubs. Regenerate with `python -B simple_shapes.py review/qa/new-full-50000.ply review/calibrated-occupied-cameras.json review/simple-shapes.json` (NumPy, SciPy, Pillow). It is an abstraction for reading the layout, not a measured model.

**Cleaner model file (local, optional).** clean_splats.py copies the 50k PLY without splats that add almost nothing: near-invisible ones (opacity < 0.02, 385,338), extreme needles (5,984) and blobs more than 0.4 units beyond the footprint (6,227). Floor reflections stay. Packed with work/osmo-clean-20261031/review/pack-sog.py (`--gpu 0` uses Metal, 16 s), it gives review/final-clean.sog: 2,563,805 splats and 39.4 MB, against 2,960,980 and 44.9 MB for A018. At the four QA poses it scores the same as A018 (aligned crop PSNR 26.05 vs 26.07 dB, SSIM 0.837 for both; review/qa-mac/scores.json). So it is lighter for phones, not sharper. It is not the reviewed candidate: candidate.json still points at A018, and swapping it needs a new review plus updated footprint and shape lineage. Those counts used the footprint before the wall trim. Regenerate with `python -B clean_splats.py review/qa/new-full-50000.ply review/calibrated-occupied-cameras.json review/final-clean.ply`.

| WIP gate | Recorded result |
|---|---|
| Full-height dollhouse | Behavior passed; visual acceptance failed |
| Navigation / reversible shell | Behavior passed; visual acceptance failed |
| Four-view sharpness improvement | Failed (2026-11-02 registered re-score: +0.3 dB aligned PSNR over live A013, gradient ratio 0.749 vs 0.754; review/qa-mac/scores.json) |
| Quota / explicit choice | Passed; zero model bytes before Open |

Read EXECUTION-STATE.json, acceptance-gates.json, then review/production/release-approval.json. **Fold 7 and iPhone 17 physical-device validation remains unverified.** Emulated touch/DPR and successful loading do not prove visual quality or phone memory safety. Historical approvals identify exact old hashes and do not authorize altered artifacts.

## 2. Repository Architecture & Directory Map

    .
    |-- README.md / .gitignore / assets-manifest.json
    |-- requirements/                 # pinned Python environments
    |-- tools/                        # restore, checks, inventory, dated cleanup
    |-- docs/
    |   |-- viewer-resources.json     # reference-photo archive and hashes
    |   |-- runtime-assets.json       # pinned trainer archive and hashes
    |   `-- repo-audit-2026-11-01/     # cleanup / backup / verification records
    |-- output/pdf/                   # finalized handoff PDFs
    |-- outputs/                      # local iPhone Full and older reports
    `-- work/
        |-- osmo-clean-20261031/       # live baseline and reconstruction foundation
        |   |-- geometry/ / masking/
        |   |-- runtime/spirula-2026.10.30/  # local, ignored by Git
        |   `-- review/production/    # viewer, build, tests, release gates
        |-- osmo-parity-20261101/      # rejected WIP and diagnostic experiments
        |   |-- review/production/    # corrected controls / experimental cutaway
        |   `-- tsdfdeps/             # local, ignored by Git
        |-- osmo-reconstruct-20261031/ # shared camera / fisheye I/O
        |-- osmo-improve-20261031/     # shared photographic baking / dependencies
        |-- osmo-format-20261031/      # OSV metadata / calibration tools
        |-- mobile-20261029/           # shared Node installation / iPhone tools
        |   `-- iphone-baseline/      # preserved metadata / restored asset closure
        `-- hosting/                  # historical Proxmox / SSH operations

| Location | Purpose / importance |
|---|---|
| work/osmo-clean-20261031/ | Live baseline plus select_frames.py, calibrated build_explicit_pinhole.py, SfM normalization in geometry/, and SAM2-assisted/manual operator + mirror masking in masking/. Reviewed masks and annotations are source inputs. |
| work/osmo-parity-20261101/ | Latest room-viewer.js and gaussian-cutaway.js in review/production/; occupied_bounds.py; prepare-highres.py and pilot-runs.py; TSDF/Poisson in review/fuse-trusted.py and poisson-surface.py; record-acceptance.py and acceptance-gates.json. |
| **work/osmo-reconstruct-20261031/seed_fisheye.py** | **Shared core:** COLMAP binary/text I/O, OPENCV_FISHEYE ray projection, transforms and seed PLY export. Imported across sibling folders through sys.path. **Do not move/rename without updating imports.** |
| **work/osmo-improve-20261031/photo_bake_agent.py** | **Shared core:** GPU ModernGL visibility, first-hit checks and multi-view consensus photographic texture baking. Helpers and local pydeps/qa-deps remain dependencies. |
| work/osmo-format-20261031/ | DJI OSV protobuf metadata, dvtm_osmo360.proto, Kannala-Brandt lens calibration and KB5-to-KB4 approximation. |
| work/mobile-20261029/ | Shared package.json / package-lock.json, pack-phone.mjs mesh simplification/compression and exact iPhone baseline metadata. Active builds no longer require retired release folders. |
| tools/ and docs/repo-audit-2026-11-01/ | Hash-checked restore/check tools, asset receipts and exact deletion records. The original map PDF describes the first snapshot; deep-cleanup-result.json and deep-cleanup-journal.jsonl describe the later cleanup. |

Retired osmo-web-20261031, -v2, -v3, fullheight-20261029 and the duplicate old report code/ tree were removed after migrating retained consumers. Historical JSON/PDF records still mention former paths. Old diagnostic comparisons require explicitly restoring their trial models from Drive; they are outside the default preview.

## 3. End-to-End Video-to-Model-to-Website Pipeline

    Dual-fisheye OSV
      -> sharpness/motion timestamp selection; native 3840 x 3840 lens views
      -> per-frame operator and mirror masks
      -> ALIKED + LightGlue SfM; coherent component; one +Y-up transform
      -> calibrated pinholes; cross-time scale-only trusted depth and seed
      -> cold-start Spirula 3DGS; raw PLY evaluation; SOG / surface experiments
      -> web build; explicit-choice gate; exact approval; atomic deployment

1. **Decode/select:** select_frames.py and format tools use original timestamps and sharpness/motion evidence. Preserve lens calibration; a stitched panorama is not a normal pinhole image.
2. **Mask:** 255 = keep, 0 = exclude. Project each operator/mirror mask consistently with its RGB view. Retain annotations and reviewed native masks.
3. **SfM/normalize:** ALIKED features and LightGlue matches establish fresh poses. geometry/normalize_fresh_sfm.py applies one audited +Y-up similarity. The timestamp holdout is photometric: SfM used all images, so it is not independent held-out geometry validation.
4. **Pinhole/depth:** build_explicit_pinhole.py generates five faces per lens. MoGe-2 guidance uses **scale only, offset = 0**, checked across distinct timestamps. Ranges, normals and the train-only dense seed must share the exact camera/world frame. Euclidean ray range is not camera-Z depth; scale is not surveyed metric truth.
5. **Train/extract:** spirula.exe train 3dgs starts cold from the audited seed. The recorded baseline/WIP uses **--primitive mip**; RGB-only 3dgs variants are separate diagnostics. pack-sog.py records source SHA, count and SH degree. TSDF/Poisson and photo-textured GLBs are alternatives, not automatically accepted replacements.
6. **Build/deliver:** build.mjs validates the candidate and creates content-addressed assets. chooser.js defers loading until Open. prepare-deploy.py checks closure, hashes, quota and approval before packaging atomic deployment. Building does not deploy.

## 4. Cloud Asset Archive & External Dataset Restoration (assets-manifest.json)

[Model/video archive: Rumah - 2026-11-01 - Models and 360 Source](https://drive.google.com/drive/folders/1VnJGQIDFISPC_v4uFLROvZF_JcDiPj7I).

assets-manifest.json indexes **A001-A056**: 54 model/seed exports plus original OSV/LRF, **9,834,491,960 bytes**. Each entry has full local SHA-256/MD5, its permanent Drive link, remaining registered local paths and historical aliases. Drive filename, byte count and destination were read back; remote SHA verification is not claimed. An empty local_paths list means no remaining registered alias, not that every external training directory was searched.

Models, video, extracted images, installed environments and generated builds are excluded from Git. The original is **DJI Osmo 360 OSV**, not Insta360 INSV; LRF is its preview proxy.

| Default restore | Canonical checkout-relative path |
|---|---|
| A001 iPhone Full | outputs/iPhone_Wide_Full_Native.glb |
| A003 iPhone Fast | work/mobile-20261029/public-phone.glb |
| A006 live raw export | work/osmo-clean-20261031/review/checkpoints/explicit-full-final.ply |
| A013 live packed Osmo | work/osmo-clean-20261031/review/clean-final.sog |
| A018 rejected packed WIP | work/osmo-parity-20261101/review/final-sharp.sog |
| A034 rejected 50k raw export | work/osmo-parity-20261101/review/qa/new-full-50000.ply |

Download those six files using their manifest drive_name filenames. Also download the [reference-photo ZIP](https://drive.google.com/file/d/1gDz-2TAD_6KDGnEfozxzJ5He9wQyA0Dj/view) and, for reconstruction, [pinned trainer ZIP](https://drive.google.com/file/d/1-4yyj3SWXnl2dlGXuceXPnF_BjVDpolY/view). docs/viewer-resources.json and docs/runtime-assets.json record their hashes and destinations. Existing private Drive permissions apply.

From the checkout root, substitute your own download directory:

    python -B tools/restore_assets.py --downloads C:/Downloads/Rumah --reference-archive C:/Downloads/Rumah/viewer-reference-resources-2026-11-01.zip --runtime-archive C:/Downloads/Rumah/spirula-2026.10.30-windows-vulkan-x86_64.zip
    python -B tools/restore_assets.py --check

macOS/Linux: download the six default models and the reference ZIP into one folder (model files may sit in subfolders; pass the ZIP's actual path), omit the Windows-only runtime archive, and use Python 3.11+ (for example .venv-audit/bin/python from section 5). The combined handoff check needs all six models, including A006; `--ids A001 A003 A013 A018 A034` is enough to build and preview both viewers. A subset restore without A001/A003 skips the iPhone transfer copies.

    .venv-audit/bin/python -B tools/restore_assets.py --downloads ~/Downloads/Rumah --reference-archive ~/Downloads/Rumah/viewer-reference-resources-2026-11-01.zip
    .venv-audit/bin/python -B tools/restore_assets.py --check

The tool verifies hashes, refuses differing existing files, writes only inside the checkout, restores iPhone aliases and regenerates gzip transport from protected GLBs. Gzip can differ across zlib versions; decoded model identity must match. Use --ids A004 for a specific archived experiment. External dataset restoration is manual.

--check also verifies the iPhone baseline files listed in asset-files.json, and checks that each .gz decodes to its protected model hash; a different compressed size is only reported. Model downloads, and a --reference-archive/--runtime-archive path that does not exist, are looked up by name and size under --downloads, including subfolders. Non-default --ids go to the manifest's canonical_local_path when it is set and inside the checkout, otherwise to the asset's first in-checkout historical_local_paths entry; A046 goes to outputs/restored-legacy/osmo-lite-30ed8cb766.glb, which work/osmo-clean-20261031/review/server.mjs reads. Exports whose only destination was a retired folder (A045, A047-A053) are refused rather than recreating removed osmo-web-20261031* folders. After the dated cleanup, deep_cleanup_repo.py --refresh-manifest and finalize_repo_audit.py refuse to rewrite the tracked assets-manifest.json without --force, because a refresh writes this machine's local paths into it.

Original workstation data locations:

    C:/Users/bombe/OneDrive/Documents/ChatGPT/Ruang Kamare/roomscan-reconstruction/data/
    |-- 20261027_IPHONE_WIDE/
    `-- 20261031_OSMO360/
        |-- originals/                  # CAM_20261031005909_0004_D.OSV / LRF
        |-- clean-v3/dataset/           # native calibrated RGB, masks, SfM
        |-- clean-v3/explicit-full-v1/  # pinholes, trusted ranges, seed, training
        `-- parity-20261101/            # 1600px dataset, pilots, 50k training

Cleanup did not modify these folders. **Exports plus video are not a full training-state backup:** extracted RGB, masks, annotations, COLMAP databases, calibration and optimizer states remain separate. Historical processing scripts/job JSONs retain original absolute data/executable paths. Restore the dataset and adjust those explicit paths before reconstruction on another machine. The default web build uses relative inputs and needs no retraining.

## 5. Environment Setup & Reproducibility Guide

The recorded native setup is Windows x64: **CPython 3.14.3** for CPU geometry/ray checks; **3.12.14** for ModernGL photographic baking, TSDF/Poisson/UV work and document tooling. Keep separate environments; compiled wheels are ABI-specific.

    cd work/mobile-20261029
    npm ci
    cd ../osmo-clean-20261031/review/converter
    npm ci
    cd ../../../..
    py -3.14 -m venv .venv-geometry
    ./.venv-geometry/Scripts/python.exe -m pip install -r requirements/geometry-py314.txt
    py -3.12 -m venv .venv-surface
    ./.venv-surface/Scripts/python.exe -m pip install -r requirements/surface-py312.txt
    py -3.12 -m venv .venv-audit
    ./.venv-audit/Scripts/python.exe -m pip install -r requirements/audit-py312.txt

macOS/Linux equivalent (verified on Apple Silicon; uv fetches the interpreters). Use `.venv-*/bin/python` wherever this guide says `Scripts/python.exe`:

    uv venv -p 3.14 .venv-geometry && uv pip install -p .venv-geometry -r requirements/geometry-py314.txt
    uv venv -p 3.12 .venv-audit && uv pip install -p .venv-audit -r requirements/audit-py312.txt

The clean-clone web check used **Node.js 24.13.1**. Exact package pins: Three.js **0.180.0**; @gltf-transform/core, extensions and functions **4.5.1**; meshoptimizer **0.25.0**; esbuild **0.25.11**; sharp **0.35.5**; @sparkjsdev/spark **2.4.0**. The npm Spark module matches the former vendored module byte-for-byte. The converter pins @playcanvas/splat-transform **3.10.3**. Active builds now use shared npm Sharp/Spark instead of a Codex cache. work/mobile-20261029 also pins **playwright-core 1.64.1** (devDependency, no bundled browser). The review harnesses (qa-capture, verify-controls, verify-choice-and-phone-policy, display-ablation), pack-phone.mjs, the mobile build.mjs and build.mesh-reference.mjs resolve their modules from that node_modules. The browser harnesses drive the installed Google Chrome: channel 'chrome' with ANGLE Metal on macOS, the recorded chrome.exe with ANGLE d3d11 on Windows; CHROME_PATH overrides on any platform. verify-controls accepts any hardware WebGL renderer, rejecting only software rasterizers, and records it.

requirements/geometry-py314.txt records NumPy **2.4.2**, Pillow **12.2.0**, OpenCV headless **4.13.0.92**, SciPy **1.17.0**, trimesh **5.2.0**, embreex **4.4.0.post1** and rtree **1.4.1**. requirements/surface-py312.txt separately records NumPy **2.3.5**, OpenCV **5.0.0.93**, moderngl **5.13.0**, glcontext **3.1.0**, SciPy **1.18.1**, pymeshlab **2025.7.post1**, scikit-image **0.26.0** and xatlas **0.0.11**. Separate audit and hosting requirements are also provided.

| Retained local dependency folder | Observed wheel ABI / use |
|---|---|
| osmo-improve-20261031/pydeps | ModernGL/glcontext are **cp312**; OpenCV is cp37-abi3. Use Python 3.12 for the GPU baker. |
| osmo-improve-20261031/qa-deps | Embreex is **cp314**; trimesh is pure Python. Use Python 3.14 for CPU ray checks. |
| osmo-parity-20261101/tsdfdeps | SciPy, pymeshlab, scikit-image and xatlas are **cp312**. Use Python 3.12 for those surface tools. |

**Do not put all three folders on one global PYTHONPATH.** That can load a cp312 SciPy package into Python 3.14 and report a misleading broken-install error. A new clone should install the matching requirements into its separate environments. Existing local dependency folders, hosting/.venv and node_modules were preserved; fresh installs do not copy their compiled wheels between interpreters. Some legacy scripts prepend these local folders, so run each with its matching interpreter.

Training also needs the hash-pinned **Spirula 2026.10.30 Windows Vulkan x64** executable under work/osmo-clean-20261031/runtime/spirula-2026.10.30/, a compatible Vulkan GPU/driver, and the external inputs/tool paths recorded in job JSONs. Decode/SfM additionally require the recorded FFmpeg, ALIKED/LightGlue and SfM tools. Source checkout does not install or launch reconstruction automatically.

## 6. Running Tests, Local Preview & Deployment

From the root, **npm test** runs loader-core.test.mjs, choice-gate.test.mjs, model-selection.test.mjs and native-delivery.test.mjs in both production folders, plus the parity cutaway.test.mjs and simple-shapes.test.mjs: **57 tests**. Run `npm ci` in work/mobile-20261029 first; otherwise the two Spark SDK checks and the simple-shapes three.js check fail with `Cannot find module`.

    npm test
    # Equivalent per-viewer command:
    cd work/osmo-parity-20261101/review/production
    node --test loader-core.test.mjs choice-gate.test.mjs model-selection.test.mjs native-delivery.test.mjs
    cd ../../../..

CPU geometry checks are executable unittest/synthetic harnesses:

    ./.venv-geometry/Scripts/python.exe -B work/osmo-reconstruct-20261031/test_seed_fisheye.py
    ./.venv-geometry/Scripts/python.exe -B work/osmo-clean-20261031/geometry/test_operator_pinhole.py
    ./.venv-geometry/Scripts/python.exe -B work/osmo-clean-20261031/geometry/test_preparation_synthetic.py
    ./.venv-geometry/Scripts/python.exe -B work/osmo-clean-20261031/geometry/test_negative_rays.py
    ./.venv-geometry/Scripts/python.exe -B work/osmo-parity-20261101/test_simple_shapes.py

Plain runs only check: they leave the committed evidence JSON untouched, and test_preparation_synthetic builds its fixture in the system temp dir. Add `--record` to rewrite an evidence file. The geometry harnesses are also collected by `python -B -m unittest discover -s work/osmo-clean-20261031/geometry` and by pytest. negative_ray_audit.py uses embreex when installed and otherwise trimesh's pure-Python ray_triangle intersector. work/recovery-report/reference_pack/implementation/scripts/test_colmap_io.py checks colmap_io's camera-model table against seed_fisheye's, and work/hosting/test_remote.py checks the deploy CLI without a network. geometry/make_native_manifest.py now requires `--image-dir`, needs calibration.json, kb4-fit-report.json and the git-ignored djmd-first.bin, and writes nothing unless every input exists.

The combined check builds both viewers, audits file closure and local HTTP HEAD/ranges, runs tools/test_restore_assets.py, and verifies that the rejected WIP cannot be packaged. build.mjs now verifies every carried iPhone file against asset-files.json and that a regenerated .gz decodes to the protected bytes. On other platforms it writes docs/repo-audit-2026-11-01/handoff-validation-<platform>.json and leaves the dated Windows receipt alone:

    ./.venv-audit/Scripts/python.exe -B tools/run_handoff_checks.py --geometry-python .venv-geometry/Scripts/python.exe

Four-view QA from the original video (verified on macOS):

    cd work/osmo-parity-20261101/review
    ../../../.venv-geometry/bin/python -B qa-mac/extract-qa-frames.py ~/Downloads/Rumah/CAM_20261031005909_0004_D.OSV   # A056; needs ffmpeg/ffprobe
    ../../../.venv-geometry/bin/python -B prepare-qa.py --frames qa-mac/frames --out qa-mac
    node build-qa.mjs
    node serve.mjs                                   # http://127.0.0.1:53270/review/qa-viewer.html, separate shell
    QA_DIR=qa-mac node qa-capture.mjs clean-final final-sharp new-full-50000
    ../../../.venv-geometry/bin/python -B score-qa.py qa-mac
    ../../../.venv-geometry/bin/python -B qa-mac/test_qa_mac.py

extract-qa-frames.py checks the video's size and hash, then decodes the exact native 3840×3840 lens frame for each QA pose. It confirms each frame by timestamp, by the recorded sharpness score, and against the stored source crops (43–44 dB at the right frame vs 19–23 dB one frame off). The operator/mirror keep masks are in neither the checkout nor the video, so these references are unmasked and score the full 600×600 crop boxes. score-qa.py keeps the historical cropPSNR and adds SSIM, PSNR/SSIM after ECC registration inside each crop, and a gradient-energy ratio (render vs photo, below 1 means softer). It also records each model's hash. Results for 2026-11-02 are in review/qa-mac/scores.json. Aligned PSNR means: A013 live 25.76, A018 rejected 26.07, A034 raw 26.13 dB. Gradient ratios: 0.754 / 0.749 / 0.748. So the 1600 px / 50k rebuild is not measurably sharper than the live model. The registration also exposes a pose error. The dining view is off by about 9.5 px (roughly (-7.8, +5.6)) in all three models, while the fridge, fan and bathroom views register within 1 px. An offset shared by every model points to that capture's camera pose or calibration rather than the trainer, and fits priority 1 below. The dining source frame 1197 is also among the blurrier selected frames.

docs/repo-audit-2026-11-01/fresh-clone-validation.json records a source-only Git clone, successful npm ci for both lockfiles, restoration of six canonical models, 37 reference images and the pinned runtime, and passing combined checks. Python validation reused the recorded compatible dependencies; it does not claim a fresh pip installation or physical-phone testing.

Preview after restoring assets and dependencies:

    cd work/osmo-clean-20261031/review/production
    node build.mjs
    node serve.mjs                         # http://127.0.0.1:53271/
    # Stop with Ctrl+C before switching:
    cd ../../../osmo-parity-20261101/review/production
    node build.mjs
    node serve.mjs                         # http://127.0.0.1:53272/

serve.mjs is loopback-only, with static GLB gzip, HEAD and byte ranges, and refuses symlinks that resolve outside public/. In the viewer, arrow keys turn the walk view or orbit the overview, and the touch D-pad appears only on touch devices, whatever the window width. Optional review/test-trusted-fusion.py exercises a small GPU shader separately from default CPU checks.

The historical hosting/remote.py CLI takes exactly one of --script, --command or --put, plus an optional --limit (seconds, default 45); no action, or two, is a usage error. --script stops the remote run after --limit minus 5 seconds (minimum 1). --put only uploads under /var/lib/vz/rumah-deploy/ to an already-normalised path with no '..', and neither path may contain quotes, backslashes or newlines, because both are written into the sftp batch file. Access is configured through RUMAH_SSH_HOST and the normal SSH agent/config, or RUMAH_SSH_CONFIG pointing to a local JSON file with host and options fields. The source workstation's working settings were preserved in ignored .local/hosting-access.json. Obtain access settings from the operator separately; they are absent from a clone. --help opens no connection.

For deployment, run **python -B prepare-deploy.py --audit-only** in the selected production folder first. Packaging requires a **current approval matching exact model, manifest, cameras and evidence**: --approval release-approval.json --previous /var/www/rumah/releases/<actual-current-release>. Do not assume a historical default is the current server release. The atomic runner verifies files, detaches replacement hardlinks, switches releases and provides guarded rollback. The separately authorized 20261103 viewer update uses viewer-update-approval.json: this binds only the exact existing A018 model and tested viewer assets, preserves the failed reconstruction records and explicitly records no retraining, inferred shapes and unverified physical phones. It cannot authorize a replacement model or mark photographic sharpness as passed. Remote credentials are supplied through local environment/SSH configuration, never committed. This handoff does not execute deployment scripts.

### Next Engineering Priorities for Handover

1. Check dense camera/edge consistency, angular sampling and guidance alignment before another full training run. Preserve the audited frame, masks and timestamp splits. **Found 2026-11-02:** build_explicit_pinhole.py sampled the pinhole RGB/masks with integer-centred rays and passed COLMAP-continuous fisheye coordinates straight to cv2.remap. Every training image therefore sat 0.1–0.9 px (median 0.11 front face, 0.32 side faces, at 1600 px) off the PINHOLE model it was written with, while the SfM keypoints used the correct convention. Both copies now use seed_fisheye.pinhole_face_maps (regression test in test_seed_fisheye.py), and fit_explicit_depth.py / validate_explicit_depth.py now sample depth, masks and seed colour on the same pixel-centre convention (their old half-pixel offsets were about 0.5 depth px). None of this has run on real training data. It only takes effect when the 1200 px base dataset is rebuilt end to end (build_explicit_pinhole → MoGe guidance → continue_explicit_full.py fit/validate) and retrained. prepare-highres.py does not do that: it skips an existing output folder and hard-links depths-trusted/, normals-trusted/ and seed-dense-train.ply from the old base, and verify-input-contract.py asserts those old hashes. prepare-qa.py now uses the same convention (regression test in review/qa-mac/test_qa_mac.py), and the four references were rebuilt from the original video in review/qa-mac/. The registered re-score there finds the dining view off by about 9.5 px in every model while the other three views agree within 1 px, so per-view pose accuracy is the strongest lead for the next experiment.
2. Compare the recorded mip primitive/appearance corrections with controlled RGB-only and independent-trainer runs at the same four poses, 1920 x 1080 viewport and masks. Small PSNR/crop gains are insufficient without visible full-view gains.
3. Fix geometry and photographic alignment together. TSDF/Poisson/photo-baked alternatives were rejected for unsupported closures, holes, wrong shapes and projection errors despite sharper patches.
4. Deliver a clean full-height cutaway that preserves cabinets, doors/windows and furniture, while keeping reversible roof/wall state and the passing controls behavior.
5. Pass all four acceptance gates, then physical Fold 7/iPhone 17 load, memory and touch checks. Promote only an exact reviewed artifact.

[Historical PDFs and full first-pass inventories on Drive](https://drive.google.com/drive/folders/1gCq9H_xPhAzDwN3Q7JnWj1mtImpua8ib). Local finalized PDFs are preserved; selected handoff PDFs are tracked in Git. Cleanup records distinguish removed logical bytes from physical savings because hardlinks share payloads.
