# Lite-only delivery — 2026-11-03

Release: 20261103-osmo-viewer-v2. The website offers exactly iPhone Lite (A003, 21,144,604 bytes) and Osmo (A018, 44,904,208 bytes). Legacy Full query links select Lite and still require Open. Full download URLs must return 404 in the current release.

Nine local Full/trial paths were deleted after containment and full-hash checks: five Full GLB hardlinks, three gzip hardlinks and one obsolete non-Lite mobile trial. Logical path bytes removed: 3,182,089,995; estimated physical release: 834,503,145 bytes; measured volume free increase: 834,084,864 bytes. Lite and all four retained Osmo canonical hashes were verified before and after. Source footage, reports, external datasets and Drive backups are preserved. See ../iphone-full-removal.json.

The restore tool refuses retired A001/A002 IDs. The active build, chooser, manifest, deployment package and tests require only Lite+Osmo. Historical source/audit documents are retained as dated records; the old clean viewer is no longer part of the active build checks. Deployment removes Full from the new server release; historical rollback releases are retained separately.

The existing Osmo model is unchanged. Photographic sharpness remains unaccepted, with no new training or physical Fold 7/iPhone 17 validation claimed. The desktop Chrome controls, Lite phone-size loading and Osmo desktop/wide-touch rendering are checked separately.

Deployment completed: 21 anonymous public delivery checks passed, including 404 for both removed Full transport URLs. The user's existing Chrome tab was refreshed at the bare root URL and visibly shows exactly iPhone Lite and Osmo, with Open disabled until selection. No cache problem was established: the previous tab already showed the updated Osmo when opened.

All 16 control/UI checks also passed against the public release in hardware Chrome. Public browser receipt: ../../../work/osmo-parity-20261101/review/controls-public-verification-20261103-v2.json. The screenshot 00-model-chooser.png in evidence-public-20261103-v2 shows the live two-card chooser before Open.
