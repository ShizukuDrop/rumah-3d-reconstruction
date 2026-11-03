# Spirula explicit pair graph extension

`spirula-v2026.10.30-pairs-file.patch` applies to
[`harry7557558/spirula-studio`](https://github.com/harry7557558/spirula-studio)
tag `v2026.10.30`, commit `6ad73ef295f5a789aeabc7e3f827c1565b5f9db4`.
It is a small local extension, not an upstream release. Preserve the original
installed executable and run the patched standalone executable explicitly.

## Interface and correctness

`spirula-sfm match FEATURES --pairs-file GRAPH.json -o MATCHES.bin ...`
and `spirula-sfm auto ... --pairs-file GRAPH.json` accept either the
`candidateEdges` output of `pair_graph.py` or a JSON array of name pairs:

```json
[["cam0/frame_000000_train.jpg", "cam0/frame_000010_train.jpg"]]
```

The file is loaded once during configuration, limited to 64 MiB, and hashed.
Names must be relative. Slash normalization, recognized image extensions,
alias ambiguity, self pairs and unknown images are checked. Duplicate pairs
are removed. Resolution uses the full feature-directory ordering: unrelated
image IDs and each feature row remain unchanged. Matching signatures include
the file content hash; changing the graph invalidates previous matching state.
An unset option does not change legacy signatures.

An explicit file replaces automatic, sequential, GPS and rig-mate pair
proposals. It does not change the native matcher, calibration, geometric
verification or mapper. Rig constraints remain separate from actual image
matches. Failed geometric matches can still be rejected normally. Keep
`--no-compact-unused-features` in mapping experiments that need original feature indices for
later localization. A graph is a proposal, not evidence of overlap or a
verified reconstruction.

## Bounded Windows build

Local source, dependencies, logs and binaries are ignored artifacts under
`.local/osmo-stick-20261103/optimization-v1/`. The tracked patch does not include
model weights, build products, source checkout or cached input features.

Prerequisites used: VS 2022 Build Tools, MSVC 14.44.35207, Windows SDK
10.0.26100.0, CMake and Ninja. Load `vcvars64.bat` before configuration/build.
The existing system Vulkan loader supplies exports for a local import library;
no system files or installed binaries are replaced.

The pinned upstream standalone SfM target initially failed to link because it
omitted `AppPaths.cpp`, `CrashLog.cpp`, `RunReport.cpp`, and the Windows
`dbghelp` library. The patch includes those missing dependencies for this target.
This build correction does not change reconstruction algorithms.

Only these dependency archives were downloaded:

| Dependency | Size | SHA-256 |
| --- | ---: | --- |
| [Slang 2026.12.0.1 Windows x86_64](https://github.com/shader-slang/slang/releases/download/v2026.12.0.1/slang-2026.12.0.1-windows-x86_64.zip) | 71,390,651 bytes | `d7ed90e979266ccf438a66465b95f251af5f8bd8c8fc209da16536d57089a804` |
| [Vulkan-Headers 1.4.357](https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.4.357.tar.gz) | 3,376,196 bytes | `7dc0dbcf1d49dd3d7da3761c251c6097dfbaac475321a4a8a99269d3d5abecdc` |

Configure with GUI off, Vulkan backend, SfM and SAM/inference enabled, and
separate tools enabled. Supply `Vulkan_INCLUDE_DIR`, `Vulkan_LIBRARY`, and
`SS_SLANGC` to the local dependencies. Build targets `spirula-sfm`,
`sfm_resume_test`, and `sfm_pair_list_test` with four workers. SAM/inference
support is needed for the ALIKED/LightGlue frontend; building this target does
not run training or invoke the GPU. The full engine and GUI targets are not
needed. Source lints remain enabled.

## Validation and measurement

The CPU-only pair-list test covers normalization, duplicate aliases, original
image IDs, input hashes and rejected unsafe/ambiguous/unknown names. The resume
test also checks graph content invalidation and unchanged extraction/legacy
signatures. A bounded exact-pair integration run is required before a large
graph run. Record selected pair count, source feature hashes, geometric
verification result and binary hash with each experiment.

On 2026-11-03 the Release standalone binary built successfully (19,203,584
bytes). Both `sfm_pair_list_test` and `sfm_resume_test` passed, and CLI help
exposed `--pairs-file`. Exact-pair GPU integration results are recorded with
the local experiment, separately from the source-only checks.

The integration used 24 unchanged feature files and four input rows describing
three unique pairs. It matched exactly those three pairs, retained the complete
24-image table, and produced identical raw feature-index match sets to the
original binary (2,198, 2,478 and 28 matches). The native verification path kept
the two strong pairs and rejected the weak loop. Its approximate single-camera
intrinsics were only a smoke test; the actual anchor experiment uses the exact
two-camera manifest. Evidence is in the ignored
`optimization-v1/pair-list-integration/report.json` artifact.

The separate cached-match subset writer is for reuse experiments only. Its
copy time must never be reported as fresh matching speed. Compare matcher
implementations on identical feature rows and candidate pairs, with the same
calibration/verifier and failed pairs retained. Separate startup/model-load
wall time from warm inference timing, and record GPU/CPU contention.

## Warm matcher benchmark

Apply `spirula-v2026.10.30-matcher-benchmark.patch` after the pair-file patch to
add a separate `sfm_matcher_benchmark` target. It uses the public native matcher
interface and existing compiled libraries; it does not replace `spirula-sfm`.
Arguments are `FEATURES PAIRS OUTPUT WARMUPS REPEATS DEVICE MODEL`. Output
includes feature/model hashes, load and constructor times, per-pair synchronized
wall times, raw match counts, and canonical correspondence hashes. Geometry
verification is excluded. Warm every pair twice before five measured cycles.

The 2026-11-03 uncontended pilot used the same 12 pairs and unchanged cached
ALIKED features in both backends. The 4,096 cap retained 3,189–4,008 actual rows
per image. All 84 native calls matched the original native correspondence hash.

| Backend | Mean warm pair | Median warm pair | Device/model constructor |
| --- | ---: | ---: | ---: |
| Native exported LightGlue | 53.615 ms | 52.874 ms | 0.281 s |
| Upstream fixed LightGlue | 24.967 ms | 24.832 ms | 6.528 s |

The mean ratio was 2.147 on this small representative population. This is a
warm matcher measurement, not a measured full-graph pipeline speedup. Match
counts differ slightly and arithmetic is backend-specific (upstream used
FlashAttention with `mp=False`); geometric quality evidence remains separate.
Local artifacts are in `optimization-study/matcher-pilot/backend-timing/`.
