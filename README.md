# Rumah: apartment reconstruction and web viewer

## 1. Project Overview & Live Production Status

[rumah.shizuku.rest](https://rumah.shizuku.rest/) offers three reconstructions of an apartment. Visitors choose a model and press **Open model** before the viewer or model downloads. Deep links preselect a choice; they do not bypass Open.

| Choice | Native payload | Representation and identity |
|---|---:|---|
| **iPhone Fast (Lite)** | 21,144,604 bytes / 21.1 MB | Textured GLB mesh, A003 |
| **iPhone Full** | 435,614,584 bytes / 435.6 MB | Full native GLB mesh, A001 |
| **Osmo 360** | 45,177,102 bytes / 45.2 MB | Gaussian SOG, live A013 |

Sizes are decimal, before optional HTTP gzip. SOG is a Gaussian splat archive, not a triangle mesh. Surface extraction and photo-textured GLBs are separate experimental outputs.

**Current live baseline: 20261031-osmo-clean-v1.** Sources: work/osmo-clean-20261031/review/production/. This handoff changed local portability and repository organization; it did not deploy a website or launch training.

**Latest local WIP: 20261101-osmo-parity-review**, in work/osmo-parity-20261101/. Viewer controls, occupied room bounds (occupied_bounds.py), and dollhouse/top/reversible-shell UI behavior are **implemented and verified**. **Model sharpness, surface quality and outside cutaway visuals failed acceptance.** The 1600px/50k Gaussian remains soft; cutaway artifacts persist; sharper textured surfaces have wrong geometry. review/production/release-approval.json has **approvedForDeployment: false**.

**2026-11-02 cutaway rework (local, not deployed, not re-approved).** The overview cutaway now uses the room's real, non-convex footprint instead of the convex hull of the dense seed. The hull covered about 20% more area than the room (21% of the hull is not room), so concave corridor/bathroom walls were never cut and the halo of unobserved exterior splats stayed visible. occupied_footprint.py derives the footprint from opaque flat splats on the fitted floor, upper ceiling and a detected dropped ceiling (y≈2.00, about half of the apartment). It stores a signed-distance grid, a per-cell local-ceiling selector and the wall band (0.40, chosen by visual A/B against 0.22) in occupiedShell.footprint. gaussian-cutaway.js reads them from one RG8 texture per splat and hides the following whenever See inside is on (the default in Orbit/Top; Walk starts with it off): splats whose 2σ reach crosses the wall line, camera-facing wall layers, the local ceiling, anything outside the floor–ceiling volume, and needle splats near the shell. Default Walk mode and the downloaded model are unchanged. The model hash, the four acceptance gates and the release approval are untouched: visual acceptance is still the architect's call. Regenerate with `python -B occupied_footprint.py review/qa/new-full-50000.ply review/occupied-cameras.json review/calibrated-occupied-cameras.json` (from work/osmo-parity-20261101, NumPy+SciPy+Pillow).

| WIP gate | Recorded result |
|---|---|
| Full-height dollhouse | Behavior passed; visual acceptance failed |
| Navigation / reversible shell | Behavior passed; visual acceptance failed |
| Four-view sharpness improvement | Failed |
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

The clean-clone web check used **Node.js 24.13.1**. Exact package pins: Three.js **0.180.0**; @gltf-transform/core, extensions and functions **4.5.1**; meshoptimizer **0.25.0**; esbuild **0.25.11**; sharp **0.35.5**; @sparkjsdev/spark **2.4.0**. The npm Spark module matches the former vendored module byte-for-byte. The converter pins @playcanvas/splat-transform **3.10.3**. Active builds now use shared npm Sharp/Spark instead of a Codex cache.

requirements/geometry-py314.txt records NumPy **2.4.2**, Pillow **12.2.0**, OpenCV headless **4.13.0.92**, SciPy **1.17.0**, trimesh **5.2.0**, embreex **4.4.0.post1** and rtree **1.4.1**. requirements/surface-py312.txt separately records NumPy **2.3.5**, OpenCV **5.0.0.93**, moderngl **5.13.0**, glcontext **3.1.0**, SciPy **1.18.1**, pymeshlab **2025.7.post1**, scikit-image **0.26.0** and xatlas **0.0.11**. Separate audit and hosting requirements are also provided.

| Retained local dependency folder | Observed wheel ABI / use |
|---|---|
| osmo-improve-20261031/pydeps | ModernGL/glcontext are **cp312**; OpenCV is cp37-abi3. Use Python 3.12 for the GPU baker. |
| osmo-improve-20261031/qa-deps | Embreex is **cp314**; trimesh is pure Python. Use Python 3.14 for CPU ray checks. |
| osmo-parity-20261101/tsdfdeps | SciPy, pymeshlab, scikit-image and xatlas are **cp312**. Use Python 3.12 for those surface tools. |

**Do not put all three folders on one global PYTHONPATH.** That can load a cp312 SciPy package into Python 3.14 and report a misleading broken-install error. A new clone should install the matching requirements into its separate environments. Existing local dependency folders, hosting/.venv and node_modules were preserved; fresh installs do not copy their compiled wheels between interpreters. Some legacy scripts prepend these local folders, so run each with its matching interpreter.

Training also needs the hash-pinned **Spirula 2026.10.30 Windows Vulkan x64** executable under work/osmo-clean-20261031/runtime/spirula-2026.10.30/, a compatible Vulkan GPU/driver, and the external inputs/tool paths recorded in job JSONs. Decode/SfM additionally require the recorded FFmpeg, ALIKED/LightGlue and SfM tools. Source checkout does not install or launch reconstruction automatically.

## 6. Running Tests, Local Preview & Deployment

From the root, **npm test** runs loader-core.test.mjs, choice-gate.test.mjs, model-selection.test.mjs and native-delivery.test.mjs in both production folders, plus the parity cutaway.test.mjs: **54 tests**. Run `npm ci` in work/mobile-20261029 first; otherwise the two Spark SDK checks fail with `Cannot find module '@sparkjsdev/spark'`.

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

The combined check builds both viewers, audits file closure and local HTTP HEAD/ranges, and verifies that the rejected WIP cannot be packaged. On other platforms it writes docs/repo-audit-2026-11-01/handoff-validation-<platform>.json and leaves the dated Windows receipt alone:

    ./.venv-audit/Scripts/python.exe -B tools/run_handoff_checks.py --geometry-python .venv-geometry/Scripts/python.exe

docs/repo-audit-2026-11-01/fresh-clone-validation.json records a source-only Git clone, successful npm ci for both lockfiles, restoration of six canonical models, 37 reference images and the pinned runtime, and passing combined checks. Python validation reused the recorded compatible dependencies; it does not claim a fresh pip installation or physical-phone testing.

Preview after restoring assets and dependencies:

    cd work/osmo-clean-20261031/review/production
    node build.mjs
    node serve.mjs                         # http://127.0.0.1:53271/
    # Stop with Ctrl+C before switching:
    cd ../../../osmo-parity-20261101/review/production
    node build.mjs
    node serve.mjs                         # http://127.0.0.1:53272/

serve.mjs is loopback-only, with static GLB gzip, HEAD and byte ranges. Optional review/test-trusted-fusion.py exercises a small GPU shader separately from default CPU checks.

The historical hosting/remote.py CLI retains --script, --command, --put and --limit. Access is configured through RUMAH_SSH_HOST and the normal SSH agent/config, or RUMAH_SSH_CONFIG pointing to a local JSON file with host and options fields. The source workstation's working settings were preserved in ignored .local/hosting-access.json. Obtain access settings from the operator separately; they are absent from a clone. --help opens no connection.

For deployment, run **python -B prepare-deploy.py --audit-only** in the selected production folder first. Packaging requires a **current approval matching exact model, manifest, cameras and evidence**: --approval release-approval.json --previous /var/www/rumah/releases/<actual-current-release>. Do not assume a historical default is the current server release. The atomic runner verifies files, detaches replacement hardlinks, switches releases and provides guarded rollback. Remote credentials are supplied through local environment/SSH configuration, never committed. This handoff does not execute deployment scripts.

### Next Engineering Priorities for Handover

1. Check dense camera/edge consistency, angular sampling and guidance alignment before another full training run. Preserve the audited frame, masks and timestamp splits. **Found 2026-11-02:** build_explicit_pinhole.py sampled the pinhole RGB/masks with integer-centred rays and passed COLMAP-continuous fisheye coordinates straight to cv2.remap. Every training image therefore sat 0.1–0.9 px (median 0.11 front face, 0.32 side faces, at 1600 px) off the PINHOLE model it was written with, while the SfM keypoints used the correct convention. Both copies now use seed_fisheye.pinhole_face_maps (regression test in test_seed_fisheye.py), and fit_explicit_depth.py / validate_explicit_depth.py now sample depth, masks and seed colour on the same pixel-centre convention (their old half-pixel offsets were about 0.5 depth px). None of this has run on real training data. It only takes effect when the 1200 px base dataset is rebuilt end to end (build_explicit_pinhole → MoGe guidance → continue_explicit_full.py fit/validate) and retrained. prepare-highres.py does not do that: it skips an existing output folder and hard-links depths-trusted/, normals-trusted/ and seed-dense-train.ply from the old base, and verify-input-contract.py asserts those old hashes. prepare-qa.py's reference remap has the same half-pixel pattern and still needs the same fix before reference crops are rebuilt.
2. Compare the recorded mip primitive/appearance corrections with controlled RGB-only and independent-trainer runs at the same four poses, 1920 x 1080 viewport and masks. Small PSNR/crop gains are insufficient without visible full-view gains.
3. Fix geometry and photographic alignment together. TSDF/Poisson/photo-baked alternatives were rejected for unsupported closures, holes, wrong shapes and projection errors despite sharper patches.
4. Deliver a clean full-height cutaway that preserves cabinets, doors/windows and furniture, while keeping reversible roof/wall state and the passing controls behavior.
5. Pass all four acceptance gates, then physical Fold 7/iPhone 17 load, memory and touch checks. Promote only an exact reviewed artifact.

[Historical PDFs and full first-pass inventories on Drive](https://drive.google.com/drive/folders/1gCq9H_xPhAzDwN3Q7JnWj1mtImpua8ib). Local finalized PDFs are preserved; selected handoff PDFs are tracked in Git. Cleanup records distinguish removed logical bytes from physical savings because hardlinks share payloads.
