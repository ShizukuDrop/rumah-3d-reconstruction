# Rumah project handover

**Snapshot: 4 November 2026, Asia/Bangkok.** This README is the single current handover. Dated files under `docs/` and `work/` are source, receipts, or historical evidence. Use the current live-state section below for decisions.

## Start here

| Question | Answer |
|---|---|
| What is live? | [Rumah](https://rumah.shizuku.rest/) offers iPhone Lite, Omso Held, and an [Osmo Stick Preview](https://rumah.shizuku.rest/preview/osmo-stick-coverage-v2-step6000/). An explicit Open action is required before the model downloads. |
| Which Stick model? | Coverage V2, step 6,000, 30,232,945-byte SPZ. It uses shared Walk, Orbit and touch navigation. This is an experimental appearance preview. |
| Is training running? | No Spirula trainer or mapper was running at handover. All six inspected Rumah scheduled tasks were Disabled. The requested 15,000-step continuation was cancelled. |
| Is quality accepted? | No. The full-reference Stick run scored better than both smaller training sets. The reduced alignment maps still failed first-bathroom continuity, and the current Stick preview has no validated cutaway. |
| What should the next owner preserve first? | The local Git handover snapshot, original Stick OSV, capture and calibration manifests, masks, exact deployed payloads, full checkpoints and recovery evidence. The older Drive archive does not cover all new Stick work. |
| Where is the code map? | [Graphify HTML](graphify-out/graph.html), [graph JSON](graphify-out/graph.json), and [scope](graphify-out/scope.json). |

- [Repository, storage, recovery and live deployment](#repository-storage-recovery-and-live-deployment)
- [Osmo Stick experiments and recovery](#osmo-stick-reconstruction-experiments-and-recovery)
- [Validation and cleanup](#validation-and-cleanup)
- [Graphify map](#graphify-map)

## Repository, storage, recovery and live deployment

This section was checked on **4 November 2026, approximately 00:25 Bangkok time** (3 November, 17:25 UTC). The Git remote and current server paths/services/model hashes were inspected read-only. Drive inventory below comes from the recorded upload/readback receipts; it was not re-enumerated on Drive during this handover. The deployment section records the state as inspected. It supersedes the older release notes where they differ.

### Authoritative project and publication state

- Working checkout: `C:/Users/bombe/Documents/Codex/2026-10-27/files-pasted-by-the-user-system`.
- Repository: [ShizukuDrop/rumah-3d-reconstruction](https://github.com/ShizukuDrop/rumah-3d-reconstruction). This is the deployment/reconstruction repository. Do not confuse it with `ShizukuDrop/RuangKamar` or the contributor fork `DavidN8/rumah-3d-reconstruction`.
- Local branch: `codex/osmo-stick`; pre-handover base: `88dc61a` (`Add optional Osmo Stick viewer and release support`).
- A fresh `git ls-remote origin HEAD refs/heads/codex/osmo-stick refs/heads/main refs/heads/master` returned remote HEAD/main at `035e3ecddefe2344b5b957f62d02385780f55e89`. It returned no remote `codex/osmo-stick` branch. Thus the local Stick commit and subsequent working changes were **not recoverable from the remote branch at the time of this inspection**.
- The local Git index contains 935 tracked files: 859 under `work/`, 54 under `docs/`, 10 under `tools/`, four requirements files, three PDFs and five root files. These are index counts, not a count of all local files or experiment outputs.
- DavidN8 PRs [#1](https://github.com/ShizukuDrop/rumah-3d-reconstruction/pull/1) and [#2](https://github.com/ShizukuDrop/rumah-3d-reconstruction/pull/2) were approved and merged earlier. Recorded merge commits are `a600cc614ec548ae75c0a5e1941ec77fa6885eb2` and `9b4e7f550dc96c7e67486cd35756bc8b9374bff1`; see `docs/release-2026-11-03/README.md`. The contributor fork is a separate Git repository, not another name for a pull request.

The handover source snapshot includes the new `tools/reconstruction/` modules, strict pinhole whitelists, shared preview viewer builder, and Graphify outputs. The ignored `.local/` workspace is a separate backup responsibility. A clone of the inspected remote main does not provide the current Stick code, data or checkpoints.

### Repository map and ownership

```text
repository root
├── README.md                         canonical project handover and operations guide
├── assets-manifest.json              older model/source archive index with hashes and Drive IDs
├── .gitignore / .gitattributes        binary, generated, environment and private-file policy
├── package.json                      combined viewer test entry point
├── requirements/                     pinned Python dependency sets by interpreter/task
├── docs/                             restore manifests and dated release/cleanup evidence
├── output/pdf/                       three retained, tracked architectural/audit PDFs
├── tools/                            restore, hygiene, inventory and dated cleanup utilities
│   └── reconstruction/               current optimization implementation and focused tests
├── work/
│   ├── osmo-parity-20261101/          Held experiments and active shared viewer sources
│   ├── osmo-clean-20261031/           older clean baseline and reusable reconstruction stages
│   ├── osmo-reconstruct-20261031/     shared calibrated fisheye/COLMAP utilities
│   ├── osmo-improve-20261031/         photo baking, mesh and rendering dependencies/helpers
│   ├── osmo-format-20261031/          OSV metadata and camera calibration extraction
│   ├── mobile-20261029/               iPhone Lite asset closure and shared Node dependencies
│   └── hosting/                      Proxmox/SSH release tooling and historical server receipts
└── .local/                           ignored; essential active data, not disposable by default
    ├── reconstruction-bench-env/      isolated Torch/LightGlue/PyCOLMAP environment
    └── osmo-stick-20261103/
        ├── dense/                    all synchronized native images, masks and source SfM
        ├── dense-pinhole-1200/        fixed-reference pinhole images, masks, poses and seed
        ├── training/                 original/recovery full-data training checkpoints
        ├── stopped/                  preserved user-stop records
        ├── optimization-study/       source investigations and matcher pilot evidence
        ├── optimization-v1/          controlled alignment/localization/appearance experiments
        ├── preview-step6000/         first paused-training preview package
        ├── shared-controls-site/     current separate Stick preview browser build
        └── shared-preview-qa/         local/public loading and navigation receipts/screenshots
```

The following authored source groups are especially important:

| Files/group | Purpose and preservation priority |
|---|---|
| `work/osmo-parity-20261101/review/production/room-viewer.js` | Shared rendering, navigation, camera, disposal and UI behavior. This is the relevant active viewer source; generated bundles are derived outputs. |
| `loader-core.js`, `chooser.js`, `room-shell.html` in that folder | Model identity/selection, explicit download gate and page structure. Deep links may preselect a model; they must not automatically download it. |
| `gaussian-cutaway.js`, `sharpen.js`, simple-shape helpers | Held-specific shell/representation and display operations. Their presence does not establish a valid Stick dollhouse shell. |
| `build.mjs`, `build-stick-preview.mjs`, `serve.mjs` | Build the main site or isolated Stick preview and serve local outputs. The Stick builder validates packed-model size/hash and uses its own camera set. |
| `prepare-deploy.py`, `deploy-native.template.sh`, `rollback-native.template.sh` | File/approval closure, immutable release packaging and guarded atomic promotion/rollback. Keep the exact approval and manifest with each generated release. |
| `work/osmo-reconstruct-20261031/seed_fisheye.py` | Calibrated fisheye geometry and COLMAP I/O, including pixel-centre-correct pinhole maps. Used by several dated pipelines. |
| `work/osmo-clean-20261031/build_explicit_pinhole.py` | Current reusable conversion entry point with explicit native image/mask/selection paths and strict train/eval whitelists. Do not substitute an older dated copy casually. |
| `tools/reconstruction/capture.py` | Paired native-frame identity and train/eval ownership. |
| `quality.py`, `scan_quality.py`, `classify_quality.py` | Masked per-view measurements and explicit sharp/blur/unknown decisions. Global low texture is not automatically blur. |
| `motion.py`, `selection.py`, `training_views.py` | Prospective geometric/appearance selection; alignment anchors and training photographs have different requirements. |
| `coverage_appearance.py`, `stage_training_ablation.py` | Coverage-aware fixed-reference appearance experiment. Per-view manual approvals bind exact inspected image/mask hashes; uncertain views are not silently promoted. |
| `descriptor_retrieval.py`, `pair_graph.py`, `stage_anchor_dataset.py` | Bounded candidate connections, revisits and isolated calibrated anchor workspaces. Original feature indices are preserved. |
| `match_cache.py`, `merge_match_cache.py`, `targeted_repair.py` | Strict cache identity and targeted graph expansion. More verified edges do not guarantee a better reconstructed component. |
| `matcher_benchmark.py`, `fresh_query_matching.py` | Fair cached-feature matcher comparisons and resumable query-to-anchor matching. Raw correspondences are not accepted poses. |
| `prepare_localization.py`, `localization.py`, `localize_batch.py` | Fresh-map 2D–3D correspondence identity, fixed generalized-rig pose estimation, native residual gates and resumable per-query results. |
| `export_localized_poses.py`, `geometry_compare.py`, `audit_localized_poses.py` | Accepted pose export, explicit training eligibility and reference agreement diagnostics. The earlier dense reconstruction is not ground truth. |
| `tools/reconstruction/patches/` | Pinned native pair-list/benchmark extensions and build instructions. Keep patch provenance with the modified executable; retain the stock runtime. |
| `tools/reconstruction/test_*.py` | Focused identity, geometry, invalid-input and state-resume regressions. Real PyCOLMAP cases need the benchmark environment. |

Read `tools/reconstruction/README.md` for the intended run order and evaluation limits. Dated folders coexist because experiments were deliberately preserved; a directory named `clean`, `final` or `review` is not itself an acceptance decision.

### Active local data and what a new machine cannot reconstruct from Git alone

The new Stick source exists at `C:/Users/bombe/Downloads/CAM_001/CAM_20261103152824_0001_D.OSV`, inspected size **2,304,431,387 bytes**. This is a different capture from the 31 October Held video archived as A056. The Stick source and current `.local/osmo-stick-20261103` outputs are not listed in the old `assets-manifest.json`; no current Drive backup of them is established by that manifest.

| Local location | What it contains / why it matters |
|---|---|
| `.local/osmo-stick-20261103/dense/analysis/frame-selection.json` | Exact 3,428 synchronized timestamp pairs and original split assignment. |
| `dense/images/`, `dense/masks/` | Native lens images and the exact masks used for features/training conversion. Preserve their hashes and provenance; reconstructed frame numbers alone do not recover all manual mask decisions. |
| `dense/mask-main/`, `reviewed-mirror-masks/`, `analysis/*mask*.json` | Raw detector/tracker masks, per-job ordinal-to-source mapping, manually traced mirror masks and composition/QA receipts. Current mask failures are documented separately. |
| `dense/sfm-native/features`, `dense/sfm-native/sparse`, `dense/sparse` | Cached original ALIKED rows, native calibration/rig reconstruction and the normalized/reference output. Feature identity is required to reuse caches safely. |
| `dense-pinhole-1200/` | Full fixed-reference training conversion and `seed-sparse-train.ply`. Many experiment images/masks are hardlinks to this data. |
| `optimization-v1/anchor-*` | Isolated flat, bottom-up and repair maps; graph requests, calibration/feature identities, logs and coverage audits. Failed candidates are evidence, not accepted replacements. |
| `optimization-v1/fresh-query-*`, `localization-*`, `localized-*-export/` | Raw matching records, immutable request/correspondence manifests, per-query acceptance results and legacy COLMAP pose exports with strict whitelists. |
| `optimization-v1/appearance-fixed-reference/`, `appearance-training/` | The first sparse appearance comparison and its checkpoint, retained even though the appearance comparison failed. |
| `optimization-v1/appearance-coverage-v2-*/`, `appearance-training-v2/` | Reviewed coverage-aware input, explicit exclusions, second controlled training run and packed preview. |
| `optimization-v1/appearance-heldout-*`, `baseline6000-*`, `shared-preview-qa/` | Fixed-view source/render comparisons, compression/renderer evidence and viewer behavior receipts. Preserve the actual screenshots as well as JSON metrics. |
| `optimization-v1/mask-failure-root-cause/` | Read-only source-mask audit: exact native composition and downstream projection replay, neighboring failure evidence, no corrected masks. |

The old cleanup receipts describe older snapshots. They do not authorize rerunning cleanup against these new ignored files. Hardlinked files also mean logical path-size totals are not physical disk savings; deleting one alias may free no payload, and editing a shared inode can change several datasets.

### Drive inventory and exact archive meaning

The user-specified destination is [the parent Drive folder](https://drive.google.com/drive/folders/1zX-JPXYY1Zeoiw-WecHVYTf2xUAh4PFj). The recorded backup lives inside its child [reconstruction archive](https://drive.google.com/drive/folders/1VnJGQIDFISPC_v4uFLROvZF_JcDiPj7I), not in an unrelated repository or root directory.

| Drive location | Recorded contents |
|---|---|
| [Models](https://drive.google.com/drive/folders/1117iv-ym4ZcceOiqSd8aR7qJYjdCr8FS) | 54 unique older 3D artifacts; raw/packed variants and rejected experiments are intentionally distinguishable. |
| [Source](https://drive.google.com/drive/folders/1c-qmQKk4Gnh6ZPKrvv4QVqDIcHuBJgQ7) | A055 LRF and A056 OSV for the **Held** capture. |
| [Documents and audit](https://drive.google.com/drive/folders/1gCq9H_xPhAzDwN3Q7JnWj1mtImpua8ib) | Historical PDFs and first-pass inventory reports. |
| [Developer recovery resources](https://drive.google.com/drive/folders/1JKHs_AMs6C7fhZOGtlzbyR3mhke6sblL) | Earlier developer handoff/cleanup receipts, viewer reference archive and pinned runtime archive. |

`assets-manifest.json` records 56 verified unique assets, totaling **9,834,491,960 bytes**: 54 models plus two source files. “Verified” means local full-content SHA-256/MD5 plus Drive readback of exact filename, byte count and parent. The connector did not expose a remote checksum, and no remote checksum was invented. The manifest explicitly does **not** claim backup of full optimizer checkpoints, extracted RGB or all external datasets.

Important identities:

| ID | Asset / recorded size | SHA-256 / location |
|---|---|---|
| A003 | iPhone Lite/Fast GLB, 21,144,604 bytes | `2b811d124120e70dcecc25d06e5dc397e2a28f310403a21fdfa1e290c41c9d2b`; [Drive file](https://drive.google.com/file/d/1j0u2yQqvrz6veBd_0y2iMOhm1guRGccO/view). |
| A013 | Earlier Held SOG, 45,177,102 bytes | `cbb33c91b5b481460b2c75e2125f3efa1458e6634abc3da1ce051a0989fd315c`; historical baseline. Its old manifest status saying “current public” is stale. |
| A018 | Held SOG used by current main viewer, 44,904,208 bytes | `db0e94c2fab729fa218a34064971a948448a856e02a06c56e6b2b5daf09f29f1`; [Drive file](https://drive.google.com/file/d/1PMA-MsUFFBIxCsAoxtfPXFxjtwFbqT-i/view). Viewer delivery approval did not convert its failed photographic-quality decision into acceptance. |
| A034 | Held 50k raw PLY, 485,601,727 bytes | `a8b127e7d8b4a9b1b9679958ff9fe1a36117258a69ecf8325dc831ebf4761eeb`; retained reference for the packed Held artifact. |
| A055 | `CAM_20261031005909_0004_D.LRF`, 97,905,073 bytes | `ec50a19f6a3b412134a18c75c2b4109c94e11a646893a83d1670da396c5f663c`; preview proxy. |
| A056 | `CAM_20261031005909_0004_D.OSV`, 1,162,988,987 bytes | `c88ff8b64ed453e6bb4da61bafaad51bbe1b477c97d7efc66360f053d52aeaa0`; [original Held video](https://drive.google.com/file/d/10Uv7lLHshPakMFCaRyNaPJP6rA_dFrIW/view). |

iPhone Full (A001) and its obsolete trial (A002) were retired locally at the user's request. Their historical Drive archives remain recorded; they are not current models to restore or republish by default. Keep iPhone Lite. The archive filename “Fast” and current UI label “Lite” refer to A003's same protected bytes.

Restore support is indexed separately:

- `docs/viewer-resources.json`: 5,809,917-byte reference-photo archive, SHA-256 `030fe667d9627fc4b97a812c2bb6c1a74abe09bf6eee4f86cdd874b45dd34e79`; [Drive archive](https://drive.google.com/file/d/1gDz-2TAD_6KDGnEfozxzJ5He9wQyA0Dj/view).
- `docs/runtime-assets.json`: Windows Vulkan Spirula 2026.10.30 archive, 75,446,110 bytes, SHA-256 `dfaf1376ab78acf4bfbaaeb7a3f12b7c06ab30bf1d9eee6082100dbc1e7b71dd`; [Drive archive](https://drive.google.com/file/d/1-4yyj3SWXnl2dlGXuceXPnF_BjVDpolY/view).
- `docs/repo-audit-2026-11-01/drive-upload-journal.jsonl`, `backup-summary.json`, `drive-destination.json` and `.local/developer-handoff-drive-receipts.json` preserve upload destinations/readbacks. Historical inventories and `exists:true` values are snapshot evidence, not fresh filesystem checks.

### Restoring source dependencies and older archived assets

1. Obtain the local handover commit or a Git bundle containing it. Obtain the current ignored Stick workspace separately if the new experiments or resumable training are needed.
2. Download only the named Drive assets/resources required for the intended task. `tools/restore_assets.py` is an offline, hash-verifying placement tool; it neither authenticates to Google nor downloads automatically. Its default canonical IDs are A003, A006, A013, A018 and A034. It refuses differing existing bytes and retired destinations.
3. Supply `--downloads`, and where needed `--reference-archive` and `--runtime-archive`, to `python -B tools/restore_assets.py`; run its `--check` mode to verify the resulting asset closure. The tool also accepts `--from-workspace` for an existing compatible workspace and explicit `--ids`.
4. Install the shared Node dependencies with `npm ci` in `work/mobile-20261029`; its lockfile supplies the shared viewer/esbuild/three/Spark dependencies. The older converter has its own lockfile under `work/osmo-clean-20261031/review/converter`; install it only when that conversion path is needed.
5. Keep the pinned Python environments separate. `requirements/geometry-py314.txt`, `surface-py312.txt`, `audit-py312.txt`, `hosting-py312.txt` and `docs/python-environments.json` document the older compatible sets. Do not combine CPython 3.12 and 3.14 native extension directories through a global `PYTHONPATH`.
6. The current local matcher/localizer runtime is `.local/reconstruction-bench-env/Scripts/python.exe`, with PyCOLMAP 4.2.1 and pinned LightGlue alongside the existing Torch installation. This local environment is ignored; experiment receipts pin the relevant runtime/weights/code identities. Its existence is not proof that a clean machine has those packages installed.
7. Validate the relevant scope: `npm test` for the main viewer regression entry point; `python -m unittest discover -s tools/reconstruction -t .` in the benchmark environment for the new reconstruction tools; `tools/run_handoff_checks.py` for the older asset/build/deployment-fixture closure. Historical test counts are dated receipts, not a substitute for rerunning after changes.

The retained tracked PDFs are `Osmo_Quality_Controls_and_Pipeline_Review_2026-10-31.pdf`, `Osmo_Architect_Mandate_Execution_and_Acceptance_2026-11-01.pdf`, and `Rumah_Repository_Map_and_Cleanup_Audit_2026-11-01.pdf` under `output/pdf/`. They describe earlier states; this handover and current evidence take precedence when facts changed.

### Training recovery boundary

The original long Stick job remains deliberately stopped. The exact Windows task `Rumah-Osmo-Stick-Recovery-20261103` was inspected and is **Disabled**. `resume-instructions.txt`, `analysis/user-stop-20261103.json`, and `stopped/20261103-user-gaming/` preserve the stop/recovery evidence.

The last fully saved original checkpoint is:

```text
.local/osmo-stick-20261103/training/stick-dense-1200-rgb-recovery1/step-000006000.ckpt/
    splat.ply   278,794,939 bytes
    state.tar   2,157,667,840 bytes
```

The progress observed before the stop was step 7,201, but that is **not** a fully saved resumable checkpoint. The checkpoint record identifies full optimizer state at step 6,000. Preserve its original `config.json`, `scene_transform.json`, source input contract and `recovery1-train-request.json`.

For an explicitly authorized future resume, `--resume` takes the checkpoint **directory**, not `splat.ply`. Use a new output/log/status directory and verify that the trainer reports restored step 6,000. Do not merely re-enable the old scheduled task: its action is the old cold-start recovery launcher. A PLY/SPZ website model alone cannot restore optimizer state.

Both controlled appearance-run status files currently record `checkpoint_complete` at 6,000. Their runner exits can be `1` because the supervising script terminates the child after validating the saved checkpoint; evaluate the checkpoint completeness record and log rather than assuming the process exit code alone means failed training. These experimental checkpoints are distinct from the paused original run and must not silently replace its resume state.

### Current server and public routes

Read-only server inspection confirmed:

| Item | Current state |
|---|---|
| Public site | [rumah.shizuku.rest](https://rumah.shizuku.rest/), no application password. |
| Dedicated server | Proxmox LXC **710**, `rumah`; historical provisioning: unprivileged Debian 13, two vCPUs, 2 GiB RAM, 16 GiB root disk. |
| Services | `nginx` and `cloudflared` both active at this inspection. |
| Main root | `/var/www/rumah/current` resolves to `/var/www/rumah/releases/20261103-osmo-viewer-v4`. |
| Main chooser | iPhone Lite and Omso Held, plus an **Osmo Stick Preview link** to the separate preview page. The link is not an automatic model download. |
| Main index SHA-256 | `1a532d01efe703c8b6e44a46d7f546c7775451a1dc2e0bb0938e2234f8ee55c6`, verified directly on server. |
| Current Stick preview URL | [coverage-v2 step-6000 preview](https://rumah.shizuku.rest/preview/osmo-stick-coverage-v2-step6000/). |
| Preview route target | `/var/www/rumah/current/preview/osmo-stick-coverage-v2-step6000` → `/var/www/rumah/previews/osmo-stick-coverage-v2-step6000-shared-controls`. |
| Current Stick payload | `model.spz`, **30,232,945 bytes**, 1,699,990 splats, SH2; SHA-256 `6e00d23feec74b82de6a3aa4de168e78bf068c9fba1228a02dde94a3e695938c`, verified directly on server. |
| First paused-run preview | [original step-6000 preview](https://rumah.shizuku.rest/preview/osmo-stick-step6000/), retained separately; 30,450,843-byte SPZ, SHA-256 `e5866cc7310cc49a75b41d9395502dd61a7bbf3f17d9f562b69fe8323946609a`. |

The current preview uses the shared navigation implementation rather than the first minimal preview controller. Its `room.json` declares provisional bounds and **`cutawaySupported:false`**: the fitted shell failed coverage and was not enabled. A source path inside metadata is provenance, not a supported public filesystem endpoint. Do not describe the current Stick preview as a validated dollhouse or quality-approved replacement.

The public shared-controls receipt is `.local/osmo-stick-20261103/shared-preview-qa/2026-11-03T17-17-39.958Z/evidence.json`. Both desktop Chrome and touch/mobile emulation passed the recorded loading/control checks. There were zero model requests before choice; natural first draw was approximately 11.0 seconds desktop and 13.7 seconds mobile-emulated on this Windows/RTX 5080 machine. The browser was closed after testing. These are not Fold 7, iPhone 17, Safari or physical-device results, and not fidelity acceptance. The receipt notes an unrelated missing favicon. A fresh non-browser urllib request during this handover received HTTP 403 from the public edge; direct container origin access and server asset identities succeeded. Do not interpret that automated-client response alone as an application password or failed model rendering.

Relevant local deployment evidence:

- `.local/osmo-stick-20261103/osmo-stick-coverage-v2-step6000-deploy.sh`: added the separate v2 preview and replaced only the main chooser HTML, after checking the old live release/index hashes.
- `.local/osmo-stick-20261103/deploy-shared-preview.sh`: built a new shared-controls directory, retained the model bytes via hardlink and atomically swapped the preview symlink.
- `.local/osmo-stick-20261103/shared-controls-site/`: generated current preview site.
- `.local/osmo-stick-20261103/optimization-v1/preview-coverage-v2-step6000/`: model package, metadata, SHA sums and packing verification. Private `model-manifest.json` and logs are not part of the intended public bundle.
- `docs/release-2026-11-03/`: older main-release approvals/receipts, including retired Full removal and all-or-nothing simple-shape behavior. Their dates and exact hashes matter.

### Rollback and deployment operations

Do not determine the complete live state from the release directory name alone. The v4 directory's chooser was updated in place to add the preview link, and the Stick route has its own atomic symlink. There are three distinct rollback scopes:

1. **Preview controls only:** change the preview symlink, under the existing release lock and only after checking its expected current target, from `/var/www/rumah/previews/osmo-stick-coverage-v2-step6000-shared-controls` to retained `/var/www/rumah/previews/osmo-stick-coverage-v2-step6000`. This restores the earlier minimal v2 viewer with the same packed model, not the original full-data model.
2. **Remove the preview entry from the main chooser:** the preserved HTML is `/var/www/rumah/previews/osmo-stick-coverage-v2-step6000-chooser-backup.html`; verified SHA-256 `b32effa68938b5122d995e4a437435e262deb77429de54983b9992871b007c62`. Validate the current chooser SHA first and copy this backup to a new temporary file before an atomic replacement. Hiding the chooser link does not delete or disable the direct preview URL. No backup deletion is needed.
3. **Whole main-site release:** use the matching generated guarded rollback script/manifest, or the same lock/check/temporary-symlink/atomic-rename pattern from `rollback-native.template.sh`, with an explicitly selected retained release. The immediately older main release `20261103-osmo-viewer-v3` exists; v1/v2 and older historical releases also remain. Switching `/var/www/rumah/current` affects the main site and relative preview routes together. It is different from changing only a preview target.

All mutations should acquire `/var/lib/vz/rumah-deploy/native-release.lock`, check the expected current link or content hash, and refuse to overwrite a concurrent change. The original native deployment template also detaches replacement hardlinks before writing new files, preventing accidental modification of retained releases. Recheck asset hashes, small HTML/JSON, service state, bounded model ranges and the explicit download gate after any authorized change. No rollback was executed for this handover.

The reusable remote entry point is `work/hosting/remote.py`. It accepts one of `--command`, `--script` or `--put`, with a bounded `--limit`; it obtains access through the normal SSH setup or `RUMAH_SSH_CONFIG`. This workstation's access settings are in ignored `.local/hosting-access.json`. Credentials, tunnel tokens, private keys and their contents are deliberately absent from this handover and must remain outside Git/public bundles. Obtain operator-managed access separately on a new workstation. Read-only health checks do not need a rebuild.

The main deployment packager `prepare-deploy.py` must be run with the actual current `--previous` path and a current exact-asset approval, not its stale historical default. Existing approval files bind specific model/camera/build/evidence hashes. They cannot authorize a changed trained model or assert visual quality that failed. Build/audit first; deployment is a separate explicit action.

Historical hosting records say Frufru's nginx service in LXC 700 was stopped/disabled while that container and its shared tunnel were kept running for another route. That is a **historical receipt, not a new Frufru status check**. Do not stop the entire shared container to reproduce the old web-service shutdown. Historical LXC backups and the original 27 October deployment records are under `/var/lib/vz/rumah-deploy/` and `/var/lib/vz/dump/` on the Proxmox host; a dated backup is not automatically a backup of today's preview or local training state.

### Essential handover gaps

1. Transfer the local handover commit to the successor. The remote main checked during handover does not contain this snapshot.
2. Back up the new 2.304 GB Stick source, required input/mask/calibration/feature manifests and selected resumable checkpoints separately. The old 56-asset Drive inventory does not establish this coverage.
3. Preserve the exact current preview build and approvals alongside model hashes. A `.spz` file alone is neither a complete viewer release nor a resumable training backup.
4. Keep model quality, mask quality, geometry continuity, browser loading and physical-phone testing as distinct acceptance decisions. The current preview is useful review access, not evidence that all those gates passed.

## Osmo Stick reconstruction experiments and recovery

This section records the reconstruction and visual-evaluation work verified on 4 November 2026. It is an engineering handoff, not acceptance of the model's quality. The website/deployment section of the final handoff is authoritative for the latest viewer changes and deployment verification.

### State and decisions to preserve

- The latest evaluated appearance candidate is **Coverage V2, step 6,000**, with **1,699,990 Gaussians**. It improves substantially over the very sparse appearance experiment in the bathrooms, but remains worse than the dense baseline overall. It has **not passed visual quality acceptance**.
- The user changed the request from continuing to 15,000 steps to stopping at the next checkpoint. V2 stopped at 6,000. The queued 15,000 continuation/evaluation was cancelled. Files with `15000` in their names are preparation or cancelled work, not proof of a trained or evaluated 15,000-step model.
- The 32,000-step value remains the original optimization schedule in configuration. It is **not** the completed step count, and changing this schedule for a resume would change the experiment.
- The reduced alignment experiments and the fixed-reference appearance experiments are different branches of the investigation. V2 uses the original dense reference poses and seed. It does **not** use the new reduced maps, which still have failed room-coverage/continuity checks.
- Smaller training sets, more registered cameras, lower loss, larger models, completed processes and valid SPZ files are not independent evidence of better appearance. Preserve the failed results and the native-resolution comparison sheets.
- No new training should be inferred from this handoff. Recheck current process identity and the user's current instruction before launching anything expensive. Historical PIDs in the records are evidence, not safe targets for a future kill command.

### Path conventions and environment

All abbreviated paths below are relative to the repository root:

```text
C:/Users/bombe/Documents/Codex/2026-10-27/files-pasted-by-the-user-system

RUN = .local/osmo-stick-20261103
EXP = .local/osmo-stick-20261103/optimization-v1
```

`RUN` and `EXP` are local artifacts, generally excluded from Git. A source checkout alone cannot reproduce this exact state without the media, calibration, caches, models and evidence described below. Do not assume they have been backed up merely because the code is on GitHub.

The existing CPU imaging interpreter is `C:/Python314/python.exe`. The existing reconstruction benchmark environment is `.local/reconstruction-bench-env/Scripts/python.exe`, including PyCOLMAP 4.2.1. The original training executable is `work/osmo-clean-20261031/runtime/spirula-2026.10.30/spirula.exe`. Modified native SfM builds, source provenance and patches are separate; do not overwrite the original executable with a benchmark build.

For bounded CPU scripts, the study used `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1` and OpenCV one-thread execution, except for explicitly recorded process-level worker counts. GPU tasks were coordinated serially. Some CPU tasks deliberately overlapped other work; their wall times are labelled non-isolated and must not be presented as clean benchmarks.

### Capture and baseline pipeline

The current Stick source is DJI Osmo 360 footage, despite older conversation references to Insta360:

```text
C:/Users/bombe/Downloads/CAM_001/CAM_20261103152824_0001_D.OSV
```

The dense input contains all **3,428 paired timestamps**, two native **3,840 × 3,840** fisheye images per timestamp, at **30,000/1,001 fps** (approximately 114.38 seconds). The initial 399-pair shortcut was superseded by this dense extraction. The authoritative index is `RUN/dense/analysis/frame-selection.json`; source images are `RUN/dense/images/cam0|cam1/frame_XXXXXX_train|eval.jpg`, with matching PNG keep masks under `RUN/dense/masks/`.

Both lenses at one timestamp own the same train/eval split. The actual rows and filenames hold out `source_frame % 30 == 29`: **3,314 train pairs and 114 eval pairs**. **Known stale metadata:** `split_note` still says “Every twelfth selected timestamp offset six.” This prose is wrong for the dense dataset. Use the explicit row/suffix ownership, never recompute the split from that note. This handoff did not change the source manifest.

The baseline data path is:

```text
OSV native paired decoding
  → dense native RGB + optical/operator/mirror keep masks
  → calibrated native-fisheye SfM and rig alignment
  → explicit normalization to +Y up
  → five calibrated 1,200² pinhole faces per registered native image
  → original sparse training seed
  → Spirula MIP Gaussian training
  → saved PLY + full state checkpoint
  → CPU SPZ packing
  → browser viewer
```

Relevant original artifacts and scripts:

| Path | Role / important constraint |
|---|---|
| `RUN/prepare_dense.py`, `assign_split.py`, `dense_mask_pipeline.py`, `compose_dense_masks.py`, `trace_dense_mirrors.py` | Original preparation and masking scripts. Read their saved requests/audits before reuse; this is not a request to rerun them. |
| `RUN/dense/sfm-native/sparse/0/` | Original native calibrated binary SfM model. `images.bin` contains 6,462 registered native images. Its intrinsics, not a factory guess, are used in source-ray comparisons. |
| `RUN/dense/geometry/normalization.json` | Exact rotation, scale and translation to the baseline's +Y-up frame. Needed to relate original native poses to trained poses. |
| `RUN/dense/sparse/0/` | Normalized model consumed by the baseline pinhole conversion. |
| `RUN/dense-pinhole-1200/` | Original 32,310 virtual faces: 31,240 training and 1,070 eval, from 6,462 native images. |
| `RUN/dense-pinhole-1200/explicit-pinhole-audit.json` | Per-face provenance and numerical ray checks; original seed count 3,507,037. |
| `RUN/dense-pinhole-1200/seed-sparse-train.ply` | Shared external seed for all three appearance comparisons. SHA256 `94a5c9720994af23e166dec373d90af142c67eab6d2805cc4bacd163ad9844f8`. |
| `RUN/training/stick-dense-1200-rgb-recovery1/step-000006000.ckpt/` | Evaluated dense baseline. Preserve both `splat.ply` and `state.tar`, plus its parent config and scene transform. |

Masks use **255 = keep, 0 = exclude**. RGB is sampled by bilinear interpolation; masks by nearest-neighbor in the pinhole conversion. The diagnostic source projector explicitly converts COLMAP pixel-center coordinates to OpenCV sampling coordinates by subtracting 0.5. This is a convention-specific conversion, not a universal correction to apply to every calibration file. The source projection was independently checked against OpenCV fisheye projection, and pose/ray round trips were checked numerically.

### Frame selection: what the implementation does and does not establish

The tracked entry point is `tools/reconstruction/README.md`. Important components are:

| Module | Function |
|---|---|
| `capture.py` | Loads synchronized timestamps and exact source image/mask/split ownership. |
| `quality.py` | Per-lens, mask-aware quality measurements: edge support and transition widths, texture distribution, noise estimate, local comparable references, spatial-cell checks, and tracked-edge corroboration for a blur proposal. |
| `scan_quality.py`, `classify_quality.py` | Persistent measurement scan and subsequent classification. Metrics can be reused without rescanning images when only decision rules change. |
| `motion.py` | Masked two-lens optical flow, calibrated fisheye bearings, rotation compensation and parallax proxy. It does not measure surveyed translation. |
| `selection.py` | Alignment anchors selected using quality, motion, surviving tracks, rotation and maximum-gap/room checks. |
| `training_views.py` | Appearance selection independent of alignment anchors, based on masked spatial content, newly visible regions, optional direction bins, sharper replacements and maximum-gap protection. |
| `coverage_appearance.py` | Later coverage-controlled appearance selection and exact per-view human review overrides. |
| `stage_training_ablation.py` | Reuses fixed reference poses, RGB/masks, external seed and eval set, to isolate appearance selection from new geometry. |

The pair policy is conservative: confirmed blur in **either** lens excludes that pair as an alignment anchor. A sharp opposite lens can remain an independent appearance candidate once a valid rig pose is available; a third view does not erase the first lens's blur. Unknown/low-texture images remain review cases rather than being relabelled blurry. Confirmed blur cannot be overridden by a coverage-count target.

An early global edge-width suspicion at frame 2981 did not survive same-content inspection. Large measured edge widths can come from soft shadows or different surfaces, while real grout/furniture edges remain clear. This is why a scalar Laplacian or global edge-width threshold was not accepted as a blur oracle. The experimental sharp-reference ceiling and thresholds were supported by clear controls and synthetic positives, but **capture-wide blur recall and real-positive accuracy were not established**. `calibration_verified` in the experimental configuration must not be paraphrased as full model validation.

The full CPU measurement scan completed all 3,428 pairs in **269.23 seconds with four workers**, no GPU. The coverage-review selector took **262.19 seconds**, retained **580 alignment pairs**, and had **252 selected pairs requiring quality review**. Its eight named region-count checks passed and it left no selector-level temporal holes, but `acceptance_passed` remained false. These are selection checks, not successful reconstruction of all rooms.

Evidence:

- `EXP/quality-pilot/`: initial 96-pair stratified audit, native examples and focused frame-2981 comparison.
- `EXP/quality-full/status.json` and `frames/`: complete persisted measurements and source identity.
- `EXP/selection-coverage-review/{selection.json,quality-decisions.json,training-views.json}`.
- `EXP/selection-coverage-review-visual/`: room overviews and nine native crop sheets covering 18 pairs/36 lens views. `root-inspection.json` records the bounded human review. It does not waive quality review for every unknown view.

### New-geometry branch and strict downstream integration

The reduced geometry branch is separate from the later appearance training. Core code includes `pair_graph.py`, `descriptor_retrieval.py`, `stage_anchor_dataset.py`, `match_cache.py`, `targeted_repair.py`, `merge_match_cache.py`, `fresh_query_matching.py`, `prepare_localization.py`, `localization.py`, `localize_batch.py`, `export_localized_poses.py`, and `geometry_compare.py`.

Preserve original feature-row identity through matching/localization. A cached verified correspondence does not imply that its feature belongs to a triangulated 3D track in the current map. The localization adapter matches exact image names, validates original feature coordinates, rejects ambiguous point identities, and takes 3D geometry and refined calibration from the fresh map. Native feature compaction must remain disabled for that path. Reused verified matches are not freshly timed matching.

Fixed-map localization uses a virtual-face proposal followed by native-fisheye consensus and robust pose refinement. A loose virtual proposal initially admitted points beyond the native threshold; this was corrected by reclassifying at the unchanged native threshold before refinement. The preserved `localization-cache-assisted-pilot` is the failed old pilot; `localization-cache-assisted-native-pilot` records the corrected one. Do not cite the failed pilot as the current solver's result or relax the gates merely to increase accepted counts.

The strict gates recorded in the 22-query repair diagnostic were: at least 24 inliers, ratio at least 0.25, at least six inliers per lens, at least four occupied cells per lens on a 4×4 grid, coordinate span at least 0.15, native median error at most 2 px, native p95 at most 4 px, angular p95 at most 1°. They are experimental gates, not a certificate of global metric accuracy.

Important artifacts/results:

| Artifact | Result / interpretation |
|---|---|
| `EXP/anchor-bottomup-review/` | Reduced-map experiment. Use its own request, logs, geometry comparison and timing for exact parameters; it is not an approved replacement for the original dense reference. |
| `EXP/localized-bottomup-export/` | Strict export: original anchors plus accepted query poses. Contains `sparse/0/{cameras.bin,images.bin,points3D.bin}`, `training-whitelist.json`, `eval-whitelist.json`, `pose-manifest.json`. |
| `EXP/fresh-bottomup-pinhole-1200/` | CPU integration test materialized 699 explicitly whitelisted native inputs into 3,495 faces: 2,595 train and 900 eval; 38,929 seed points. 1,403 unlisted posed images were excluded. It took 66.74 s with two workers. `trainingReady=false`; no model was trained from this integration dataset. |
| `EXP/warper-integration/real-integration-audit.json` | Integration verification. Conversion success is not scene-geometry acceptance. |
| `EXP/anchor-repair675-review/` | Targeted repaired-map experiment. First-bath registration still left a gap from frame 364 to 458. |
| `EXP/missing-anchor-support-repair8892-v2/pnp-diagnostic-summary.json` | 22 missing anchors using the repair's own verified 8,892-edge cache: **0 accepted, 22 rejected, 0 errors**; 3.65 s, one-worker CPU, non-isolated. All failed median residual ≤2 px; 16 also failed the ratio. Native median range 2.092–2.759 px. Existing track support was substantial in several cases, so “no tracks” alone cannot explain the gap. No rejected/interpolated pose was promoted. |
| `EXP/localized-repair675-export/` | Separate accepted-pose export; not used by V2 appearance training. It still lacks adequate first-bath coverage. |
| `EXP/anchor-gapunion-review/outcome.json` | Later delta-union explicitly rejected: first- and second-bath registration/continuity regressed relative to repair675. A larger main registered count was insufficient. |

The tracked `work/osmo-clean-20261031/build_explicit_pinhole.py` now accepts **both** `--train-whitelist` and `--eval-whitelist`, plus explicit `--images-dir`, `--masks-dir`, `--selection`. It verifies names and splits, reports whitelist/input hashes, excludes unlisted anchors, preserves the supplied fresh frame, and never substitutes old poses. Appended localized image observations have point IDs `-1`; they provide no fabricated seed tracks. Training seed colors/observations must come from eligible training images and distinct training timestamps.

The actual integration invocation is recorded in `RUN/run-fresh-pinhole-integration.py` and `EXP/warper-integration/real-integration-status.json`. For a future approved export, use a **new** output directory:

```powershell
& .local/reconstruction-bench-env/Scripts/python.exe `
  work/osmo-clean-20261031/build_explicit_pinhole.py `
  --source NEW_EXPORTED_MODEL --output NEW_PINHOLE_DIRECTORY `
  --subset all --size 1200 --workers 2 `
  --images-dir .local/osmo-stick-20261103/dense/images `
  --masks-dir .local/osmo-stick-20261103/dense/masks `
  --selection .local/osmo-stick-20261103/dense/analysis/frame-selection.json `
  --train-whitelist NEW_EXPORTED_MODEL/training-whitelist.json `
  --eval-whitelist NEW_EXPORTED_MODEL/eval-whitelist.json
```

Those uppercase paths are placeholders, not runnable existing inputs. A fresh export's axes are undeclared unless an explicit recorded normalization is applied; do not reuse the old model's transform or shell implicitly. Focused regressions are in `tools/reconstruction/test_build_explicit_pinhole.py`; the broader CPU suite is `python -m unittest discover -s tools/reconstruction -t .`. Tests needing PyCOLMAP can skip in an environment without it, so use the benchmark interpreter when validating the actual pose solver.

### What the blur diagnostics established

The following comparisons used the **same positions, headings and 1,600 × 1,000 viewport**. Source photos were projected from original native fisheye pixels with original calibrated intrinsics and masks. No image-fitted shift/warp, color fit, sharpening, denoising or deblurring was applied to make comparisons look closer.

1. **Source / raw PLY / SPZ in Spark**, main room, first bathroom and bedroom: `EXP/baseline6000-compression/`. Raw and packed models share the major doubled/streaked edges and soft objects. SPZ quantization was not the principal blur source in those three views. These were training-camera positions, not held-out acceptance.
2. **Source / actual stored 1,200² training faces / raw render**: `EXP/baseline6000-training-input/`. Actual training pixels preserve the fine features missing from the render. Source-versus-reprojected-training PSNR was 38.55 dB (main), 39.62 dB (first bath), 43.44 dB (bedroom). This weakens a simple “the 1,200 px warp destroyed the detail” explanation for these examples; it does not prove every image/ray is perfect.
3. **Exact raw saved PLY in native Spirula renderer versus Spark**: `EXP/baseline6000-native-renderer/`. Native rendering also lacks the important detail. Native-versus-Spark PSNR was 31.66 dB (main), 30.10 dB (bath), 26.11 dB (bedroom). A separate appearance/rasterization difference exists, but browser-only changes cannot restore detail that is missing in the native render.

Renderer caveats: native export does not apply per-training-image PPISP/bilateral-grid corrections; native low-pass covariance was 0.1 px² versus Spark's 0.05 px²; literal background RGB was matched, but color handling may differ. These differences were not all isolated experimentally. Source sensor grain and exposure affect pixel metrics. Do not assert that MIP export, Spark, poses, masks or optimizer settings is the single proven cause.

Reusable diagnostic scripts are `RUN/prepare-compression-diagnostic.py`, `capture-compression-diagnostic.mjs`, `compare-preview-assets.py`, `compare-training-input.py`, `prepare-native-render-diagnostic.py`, `native-render-ctl.py`, `compare-native-renderer.py`, and `finish-native-renderer-evidence.py`. Their frozen JSON projects and render evidence are the authoritative camera/model/settings records.

### Appearance experiments: three fixed-reference arms

All three used the original normalized poses and the same external sparse seed. This isolates the training image selection while preserving reference geometry. It does not demonstrate that the reference geometry is correct.

| Arm | Dataset | Native training views / virtual training faces | Saved step / splats |
|---|---|---:|---:|
| Dense baseline | `RUN/dense-pinhole-1200` | 6,248 / 31,240 | 6,000 / 1,699,963 |
| Sparse appearance | `EXP/appearance-fixed-reference` | 570 / 2,850 | 6,000 / 1,699,997 |
| Coverage V2 | `EXP/appearance-coverage-v2-fixed-reference` | 2,678 / 13,390 | 6,000 / 1,699,990 |

Every arm retained the **same 1,070 eval faces**. V2 kept 42.8617% of native reference training views. Its `staging-verification.json` checks all 14,460 staged pose records byte-equal to the reference, unchanged calibration and seed, and 28,920 hardlinked RGB/mask files. **Do not edit these hardlinked images/masks in place:** that can mutate the original reference and other staged datasets. Mask experiments need separate files and new frozen manifests.

V2 selected 21 initially unknown native views only after scoped human inspection bound to image/mask hashes. Seven confirmed mask failures were excluded. This is exact per-view approval, not approval of whole intervals or an entire lens. `appearance-coverage-v2-reviewed-final/training-views.json`, `appearance-coverage-v2-fixed-reference/ablation.json`, and `staging-verification.json` form the selection/staging audit chain. Some earlier selection fields remain intentionally conservative (`training_ready=false`); the controlled experiment was authorized and staged later, without changing the publication acceptance state.

The V2 training command is preserved as an argument array in `EXP/appearance-training-v2/status.json`. Important settings shared with the baseline include MIP primitives, SH degree 2, cap 1,700,000, high quality, original 32,000-iteration schedule, explicit pinhole input, no progressive image resolution or splat budget, mask loading, no depth/normal supervision, PPISP and bilateral grid enabled, mild distraction robustness, strong floater suppression, world-size cap 0.12, and no pose recentering/rescaling. The only allowed config differences recorded by evaluation were dataset/output paths, eval-image saving, and checkpoint save interval. The detailed config is preferable to reconstructing a command from prose.

V2's status says `checkpoint_complete`, elapsed **1,298.89 s**, historical trainer PID 2160, exit code 1. The nonzero exit was recorded after controlled checkpoint termination; completeness was separately verified from stable PLY/state files and readable complete checkpoint TAR. Do not treat exit code alone as either success or failure. Resuming requires the optimizer state, not just the PLY. There has been one run per selection; stochastic repeatability is not established.

### Held-out comparison: exact protocol and measured results

The frozen plan uses both lenses at five eval timestamps: **hall 269, first bathroom 449, second bathroom 1649, bedroom 2249, main room 2999**. There are ten exact camera views and twenty native 500×500 detail crops. Each camera uses its exact reference center and a horizontal native-axis heading, +Y up, 65° vertical FOV, 1,600×1,000 pixels. Crops were selected from source images and frozen before candidate renders. No post-render image registration is used.

These are **same-video photometric interpolation holdouts**, not independent geometry holdouts. The original SfM already estimated these poses. A future blocked-time evaluation would require both training arms to exclude the same blocks and must be labelled separately.

Equal-weight region/lens means against directly projected native source pixels:

| Arm | MAE, 8-bit (lower better) | PSNR dB | RGB SSIM |
|---|---:|---:|---:|
| Dense baseline 6,000 | 14.2737 | 23.2215 | 0.732601 |
| Sparse 6,000 | 16.5005 | 21.2835 | 0.712360 |
| Coverage V2 6,000 | 15.1102 | 22.3784 | 0.722573 |

Against the actual stored eval faces projected to the same rays:

| Arm | MAE, 8-bit | PSNR dB | RGB SSIM |
|---|---:|---:|---:|
| Dense baseline 6,000 | 13.9512 | 23.6235 | 0.771637 |
| Sparse 6,000 | 16.2333 | 21.4945 | 0.750419 |
| Coverage V2 6,000 | 14.8068 | 22.6988 | 0.761192 |

Per-region source PSNR makes the regression/recovery visible:

| Region | Dense baseline | Sparse | Coverage V2 |
|---|---:|---:|---:|
| Hall | 15.3108 | 15.9595 | 15.5779 |
| First bathroom | 28.4045 | 23.1179 | 25.6592 |
| Second bathroom | 27.1208 | 23.6579 | 26.3692 |
| Bedroom | 23.5860 | 23.1494 | 23.4839 |
| Main room | 21.6855 | 20.5329 | 20.8019 |

All twenty detail sheets were personally inspected. V2 recovers much of the sparse model's bathroom failure, but grout still ghosts/doubles, hose corrugations remain absent, main-room labels/drawer edges/bottle ribs remain soft or streaked, and the bedroom is near baseline rather than a source-detail breakthrough. **Hall cam0 has a major scene/layout/occlusion mismatch in every arm**, which remains unresolved and should not be dismissed as ordinary blur.

Authoritative evidence:

```text
EXP/appearance-heldout-comparison/
  plan.json, crops-frozen.json
  targets/, baseline-render/frames/, candidate-render/frames/, comparison.json

EXP/appearance-heldout-comparison-v2/
  plan.json
  candidate-validation.json
  candidate-project.json
  candidate-render/render-session.json
  candidate-render/frames/frame_00001.png ... frame_00010.png
  comparison.json
  three-version-comparison.json
  three-version-crops/                    # 20 four-column native detail sheets
  visual-review.json                      # per-crop observations + hashes
  readiness.json                         # explicitly not quality accepted
```

The original plan SHA256 is `d72e813f80630270c0cf6aab79bd786267f850f3bd7756333729b56df1665008`; V2 plan SHA256 `e0388b6bc4d29353fe9ecdd0fe8faffdb69e99dac9ac41573a17b2c327e41a7a`; frozen crop SHA256 `24ec8f760b33600721df793041b50a16e7410583a9b4af59bf3eab5ef3997f4e`. V2 reuses the previously verified baseline PNGs rather than introducing a second baseline render.

CPU-only validation/recalculation entry points, with existing artifacts present:

```powershell
& C:/Python314/python.exe .local/osmo-stick-20261103/validate-heldout-v2-input.py candidate
& C:/Python314/python.exe .local/osmo-stick-20261103/compare-heldout-v2.py
& C:/Python314/python.exe .local/osmo-stick-20261103/compare-three-heldout-versions.py
```

Read each script first: the comparison scripts rewrite derived reports/sheets. To reproduce renders, allocate a fresh output set and adapt the frozen project deliberately; `run-heldout-v2-render.py candidate` refuses to overwrite existing PNGs and checks checkpoint completion/trainer exit. It opens the native renderer with exactly one idle model and a frozen project, triggers frame export through documented application automation, verifies ten complete PNGs, and closes its owned process. Rendering is a GPU task and must be coordinated; the historical completed renderer was PID 34720. Do not start a trainer to obtain comparison frames.

### Confirmed mask failures and remaining uncertainty

The seven explicit V2 exclusions were:

| Native view | Observed failure |
|---|---|
| cam1 / 380 | Retained operator hand/arm |
| cam1 / 394 and 416 | Retained lower-rim operator body/hand/head |
| cam0 / 1650 | Retained foot/trousers near lower rim |
| cam1 / 1580 | Mirror glass extends beyond the excluded polygon |
| cam1 / 1697 and 1699 | Upper mirror/reflected doorway/light area remains outside excluded polygon |

`EXP/appearance-coverage-v2-visual/independent-review.json` contains the independent native crop review; `EXP/mask-failure-root-cause/audit.json` traces the pipeline. The four operator cases had empty raw segmentation exclusions; image identity, ordinal mapping, final mask composition and pinhole reprojection matched exactly. This points to missing upstream detection/segmentation output rather than a demonstrated resize/coordinate bug. The exact internal detector-versus-tracker cause is not known.

Mirror contours were approximate manual traces on 400 px native-lens displays, interpolated between anchors. Native rasterization matched the trace; the actual dense path applied no extra dilation. The inspected contours under-covered true glass. Full correct boundaries were not reviewed, so no replacement polygons or masks were invented. Neighbor cohorts show empty raw masks in 23/76 cam1 frames 360–435 and 13/32 cam0 frames 1635–1666; empty output prevalence is **not proof that every such frame visibly contains an operator**.

Masks were not edited and their original hashes remain unchanged. Sharpness approval never implies mask correctness. The audit establishes real input contamination, but it does not quantify how much this caused the map gaps or appearance blur.

### Packaged V2 preview and camera fallback

The exact V2 PLY is:

```text
EXP/appearance-training-v2/selected/step-000006000.ckpt/splat.ply
278,799,367 bytes
SHA256 c23bd22e92b5f064ff64005ddf3a29fdfd52e50f531fd633a281a7dc7a6e1ea7
```

The packaged asset is:

```text
EXP/preview-coverage-v2-step6000/model.spz
30,232,945 bytes (30.2 MB decimal)
SHA256 6e00d23feec74b82de6a3aa4de168e78bf068c9fba1228a02dde94a3e695938c
SPZ v3, SH2, MIP flag, all 1,699,990 splats retained
```

`RUN/prepare-coverage-v2-preview-spz.py` uses the existing PlayCanvas `splat-transform` tool on CPU (`-g cpu --max-workers 0 --spz-version 3`). A temporary PLY copy receives only `comment SplatRenderMode: mip`; the original PLY payload remains unchanged. The temporary exact leaf was removed after packing. It verifies the SPZ header's count, degree and MIP flag. This header validation alone does not establish rendered/mobile quality.

`RUN/assemble-coverage-v2-preview.py` created a gated standalone preview with `index.html`, `metadata.json`, `viewer.js`, `model.spz`, hash/provenance files, a Preview/6,000-step badge and bathroom-softness disclaimer. The parent subsequently owns controls replacement and the live website, so do not rerun assembly over their deployment package. The original standalone used OrbitControls only: no WASD/free walking/mobile D-pad. The control deficiency was proven from source; it was not evidence that the model itself lacked camera translation support.

For production-viewer navigation, the original shell exporter `RUN/export-trained-cameras.py` failed its own footprint gate: **66.2% of original camera centers within 0.25 scene units of the fitted footprint, versus 90% required**. This was not bypassed. `RUN/export-v2-controls-fallback.py` therefore exported exact original calibrated camera positions/headings with provisional framing and masked source photos:

```text
EXP/preview-v2-controls-cameras/
  cameras.json
  cameras.provenance.json
  cameras-photos/          # five JPEGs plus five validity masks
  photo-contact.jpg
```

This fallback preserves original normalized units, +Y up, five original presets, start camera and source-photo calibration. It uses a robust opaque-PLY sample plus all 6,462 original registered camera centers for bounds/framing, with **10,254 framing points**. These bounds are for navigation framing, not a validated occupied shell. `occupiedShell=null` and `cutawaySupported=false`. The production cutaway installer must be guarded; do not manufacture a footprint or enable fitted cutaway from this fallback.

All five source photos were visually checked: correct room/orientation, with the second bathroom's existing mask producing a black excluded region (67.82% valid pixels); the other four are fully valid in this crop. Source-photo URLs are relative to the camera file's deployment directory. The camera JSON SHA256 is `afa13b65554e494b7ce9a2bb4ec1850e37bc6f26636738b070a5a115bc4eab27`.

Other viewer integration constraints identified for the parent: camera data requires `presets` and `photos` arrays, calibrated preset fields, bounds and framing points; the old Osmo Stick-specific 29,999,999-byte limit is below this exact SPZ's size; browser sharpening/LoD settings differ from the original plain preview and must be reported separately from the native evaluation. Physical Fold 7/iPhone 17 performance is not certified by the native renders or desktop screenshots.

### Suggested next experiments, in order

1. **Preserve and audit the current state before another training run.** Keep exact baseline/V2 checkpoints, frozen comparison data and source masks. Finish current viewer controls validation separately; good controls are necessary but cannot remove missing model detail.
2. **Resolve input-mask failures on a bounded interval with complete native boundary review.** Create a new versioned mask dataset rather than editing hardlinks. Verify operator and mirror exclusion in both lenses, including intermediate frames, then compare identical input rays and coverage. An automatic full-circle mask is not a mask-quality pass.
3. **Investigate first-bath rig/calibration/geometry consistency and the hall cam0 mismatch.** Use multi-view static edges and unchanged native residual gates. Distinguish ambiguous/repeated-tile matches, reflection contamination, calibration error and map inconsistency. Do not fill rejected pose gaps with interpolation and call them recovered geometry.
4. **Use an isolated appearance ablation after those checks.** Keep the same heldout plan, seed and poses while changing one justified training factor at a time (for example an appearance correction or regularization setting). Preserve the original 32,000-step learning-rate schedule for a true resume. A longer run may help an underconverged 6,000-step model, but this has not been demonstrated and cannot be promised to fix masks or poses.
5. **Validate both native and browser output, translated views and dollhouse behavior.** Compare the exact packed asset at the same cameras, then novel translations and room transitions. A usable dollhouse needs a defensible surface/cutaway representation; the failed shell-fit gate must stay visible in the evidence.

The evidence does not justify “use all frames,” “use fewer frames,” “increase file size,” or “change the web renderer” as a complete standalone solution. The dense baseline is better than both reduced appearance selections at this checkpoint; V2 shows that restoring room/direction coverage matters. The remaining failure needs controlled input/geometry/training separation.

### Artifact recovery and cleanup rules

Keep these before deleting caches or local experiments:

- Original OSV, exact extraction/selection/calibration provenance, native RGB, original masks plus manual contour/correction records, and native SfM source model.
- Normalization JSON, baseline pinhole audit and sparse seed, configs/scene transforms, and the baseline/sparse/V2 checkpoint directories. `state.tar` is required for a full optimizer resume; a PLY or SPZ is insufficient.
- Frozen eval plan/crop definitions, target/mask PNGs, all thirty native model comparison frames (ten per arm), per-crop visual reviews, metrics, and image/model hashes.
- Exact source/feature/cache identities for any geometry branch intended for further localization. Keep the preserved native image table and feature indices; deleting them can make verified matches unusable even if the 3D model remains.
- The local diagnostic scripts in `RUN/`, which are not necessarily tracked. Promote or archive them deliberately if the maintainer needs reproducibility outside this workstation.

Recovery scenarios:

| What is missing | Minimum recovery path |
|---|---|
| Website/SPZ only | Restore the exact packaged SPZ by hash, or repack the preserved exact V2 PLY with MIP/SH2/count checks. Revalidate the actual viewer; do not automatically rerun training. |
| V2 render PNGs | Use the preserved V2 checkpoint PLY and frozen native project in a new output directory; compare to the preserved targets/crops. No optimizer resume is needed. |
| Full optimizer state | Restore `state.tar`, PLY, config and scene transform together. If the state is absent, acknowledge that a PLY initialization is a different run, not an exact continuation. |
| Pinhole images | Recreate from the exact source RGB/masks and corresponding model/normalization with the explicit warper; verify per-face poses, masks, split and seed identities. Old poses must never silently replace a fresh export. |
| Source masks | Restore exact masks and their trace/correction provenance. A newly inferred mask is a changed experiment; record a new dataset/version. |
| Reduced-map caches | A saved map can still render, but fresh-query localization needs exact feature rows/matches and calibration provenance. Recompute deliberately and record the cost if they cannot be restored. |

Never recursively delete or move a computed Windows path without verifying its resolved target lies inside the intended project directory. More specifically, do not treat `EXP` as disposable wholesale: it contains the only local exact models, audits and failure evidence for several experiments. Directory presence, stale `running` text or a historical PID does not establish active work; inspect authoritative current process identity and terminal status before resuming, stopping or cleaning anything.

## Validation and cleanup

The handover reran **62 viewer tests** with `npm test` and **136 reconstruction tests** with:

```powershell
.local/reconstruction-bench-env/Scripts/python.exe -B -m unittest discover -s tools/reconstruction -t .
git diff --check
```

Physical Fold 7 and iPhone 17 testing remains open. The live preview receipt proves desktop Chrome and mobile emulation movement, release, drag, zoom and download gating. The current preview's first frame and exact model bytes are covered by the receipts referenced above.

Removed **145 files, 89,902,709.0 logical bytes**: regenerable Python bytecode, compiled SfM object intermediates, the stale SFTP batch, and the two cancelled 15k launch helpers. The exact file receipt is `.local/handover-cleanup.json`. Source, binaries, libraries, pinned build inputs, models, checkpoints, run logs, verification, and rollback assets were retained. The remaining object build will recompile those files when needed. The verified binaries remain usable.

The handover source is committed locally. Transfer that commit or a Git bundle for source continuity. Transfer the necessary ignored data and production backups through an authorized archive separately. Git and Graphify do not substitute for that backup.

## Graphify map

The Graphify skill ran an AST extraction on **109 active code files**, producing **1,170 nodes, 3,201 edges and 71 communities**. The map covers the current reconstruction tools, deployment/recovery helpers, shared viewer and selected geometry modules. It excludes generated bundles, historical corpora, media, ignored run data and credentials. The precise file list is in [scope.json](graphify-out/scope.json). No semantic model calls were used, so extraction token cost was **0 input / 0 output**. The endpoint audit found zero missing/dangling endpoints, zero duplicate edges and one self-loop.

- Open [graph.html](graphify-out/graph.html) for navigation.
- Use [graph.json](graphify-out/graph.json) for machine queries.
- Example: `graphify query "How do pair graph, match cache and localization connect?" --budget 1000` from the repo root.
- On the original workstation the scoped build command was `uv tool run --from graphifyy python .local/build-handover-graph.py`. The full root corpus is larger than this scoped scan. Refresh using the documented scope rather than accidentally indexing private local assets.

The most connected project symbols include `read_index` (42 edges), `prepare_requests` (33), `build_pair_graph` (30), `loadAsset` (30), and `select_training_views` (27). Start by tracing verified image pair identities through the match cache and localization adapter into the training whitelist. Inferred edges are leads for source inspection. In particular, a similarly named function linked across modules is not proof of a runtime call.
