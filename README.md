# WallSense embedded system checkpoint

This repository preserves the local WallSense work based on Espressif `esp-csi`
commit `8633d67152db2808f141cc1595970aa9cf406045`, using ESP-IDF 5.5.6.
The complete upstream repository, virtual environment and build outputs are not
vendored here. The existing local Espressif checkout and its remote are unchanged.

## Resume

Read [Person B's checkpoint](docs/person-b-checkpoint-2026-11-19.md).
The next task is **offline analysis of the two stationary baselines in trial 001**.
Do not interpret this exploratory trial as a verified walking detector.

## Preserved source changes

- `esp-csi/examples/get-started/tools/csi_data_read_parse.py`: the verified chunked
  serial collector, validation/logging, C6 CSV header and graceful shutdown fix.
- `esp-csi/examples/get-started/csi_send/main/app_main.c`: the original local TX
  onboard antenna selection using GPIO3 LOW and GPIO14 LOW.
- `patches/esp-csi-8633d671-wallsense.patch`: both changes relative to the upstream
  base. Apply only to a matching clean upstream checkout when reconstructing work;
  do not apply blindly over the existing modified local checkout.
- `diagnostics/`: trial controller, offline analysis, validation utilities and the
  stationary retest reports. No hardware trial is started by opening these files.

## Datasets and exact-byte preservation

- Trial 001: `datasets/walking_trial_001/walking_20261119_233028_983555.zip`
- Stationary investigation/retest, original captures, helpers and both TX editor
  conflict source copies: `datasets/stationary_retest/diagnostics-2026-11-19.zip`

ZIP members retain their original workspace-relative paths, filenames and bytes.
Extract into an empty recovery directory, or review existing paths before merging.
The trial ZIP contains all 24 files from
`diagnostics/trials/walking_001_20261119_233028_983555/`, including the original
manifest, route correction, raw bytes, CSI CSV, logs, read/parse timestamps,
phase events/times, quality/analysis results, plots and report.

Each ZIP has an adjacent `.inventory.json` with every member's size and SHA-256.
`datasets/walking_trial_001/backup_audit.json` records the manifest/file audit,
original raw/CSV hashes and source hashes. Archives are ordinary Git blobs;
no Git LFS pointers or external upload service are required for their sizes.

The original manifest retains the planned crossing route. Its additional actual
route fields and `route_note.json` document that the computer restricted the user
to a one-sided approach-and-retreat route. Board spacing and height remain unknown.

The two TX source copies under `diagnostics/save-conflict-20261119_235158/` in the
stationary archive preserve both the stale editor buffer and the newer disk file.
The disk file is the canonical source snapshot because it includes the complete
antenna initialization. The older buffer differs only in include placement and
the missing antenna block.
