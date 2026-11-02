# DavidN8 integration — 2026-11-03

PR #1 and PR #2 were approved and merged, preserving both histories. Merge commits: a600cc614ec548ae75c0a5e1941ec77fa6885eb2 and 9b4e7f550dc96c7e67486cd35756bc8b9374bff1.

Release `20261103-osmo-viewer-v1` implements the new cutaway, framing, controls, fitted layout and display sharpening. It uses the existing A018 model (44,904,208 bytes), not newly trained geometry. The corrected image/depth sampling is merged for the next reconstruction run. Physical Fold 7 / iPhone 17 tests and photographic sharpness acceptance remain unverified/unaccepted.

Integration fixes: inferred walls/furniture are labeled on desktop and phones, with a visible photographic-view action; reference masks are regenerated and scoring follows declared metadata; browser checks accept a configurable base URL and dated evidence destinations; the combined check accepts a separate report destination to preserve the historical audit.

Deployment authorization is separate from reconstruction acceptance. `viewer-update-approval.json` binds the exact model, public assets, inherited iPhone files, cameras, packing report, current viewer checks and the user's explicit deployment instruction. The original failed reconstruction approval is preserved. The new path rejects changed models and any claim that sharpness has passed. The atomic runner retains the current release for rollback.

Validation: 58 Node regression tests; four CPU geometry suites; restore identity checks; both viewer builds, deployment fixtures, file closure and bounded local HTTP checks; 16 hardware-Chrome control/UI checks; desktop, narrow-touch and wide-touch quota checks; 5 QA-mask tests; 5 mocked SSH tests; and 14 viewer-authorization tests. Touch emulation is desktop Chrome, not physical phone testing. The combined handoff receipt records 13 command groups. Screenshots remain local under `work/osmo-parity-20261101/review/evidence-20261103/`, with hashes in the verification/approval records.

The previous production release is `20261031-osmo-clean-v1`. Deployment and anonymous public delivery are verified separately after atomic promotion.
