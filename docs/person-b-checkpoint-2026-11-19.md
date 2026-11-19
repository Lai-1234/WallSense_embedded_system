# WallSense: Person B checkpoint — 2026-11-19

This checkpoint records where Person B paused on 2026-11-19 (Asia/Kuala_Lumpur).
WallSense uses XIAO ESP32-C6 boards and Wi-Fi CSI for human activity detection.
The next session should investigate malformed CSI records before treating capture
or detection as reliable. All experiments below are pending.

## Verified progress

- Both XIAO ESP32-C6 boards were built and flashed using ESP-IDF 5.5.6.
  TX used COM6 and RX used COM7. RX continuously printed `CSI_DATA` records.
  These observations describe the pause point; the boards may now be disconnected.
- TX was configured to select the onboard ceramic antenna: GPIO3 LOW enables
  the RF switch, followed by a 100 ms delay, and GPIO14 LOW selects the onboard
  antenna before NVS and Wi-Fi initialization.
- RX RSSI readings were approximately -87 dBm before the adjustment and -64 dBm
  afterward. Board placement also changed, so the improvement cannot be
  attributed to the antenna change alone.
- Running `csi_data_read_parse.py -p COM7` from
  `esp-csi/examples/get-started/tools` printed `open success`.
  The live phase and I/Q plots updated.

## Issue at the pause point

The live plots updated, but the Python parser rejected some CSI records.
The terminal messages were:

```text
element number is not equal 175 25
csi_data_len is not equal 256 216
data is incomplete
```

In the second message, one record declared 256 values and the parser recovered 216.
The proportion of malformed records, where the data became malformed, and the
root cause are still unknown. PyQt plotting load is one hypothesis to test.
Reliable CSV capture, activity scoring, and through-wall detection remain
unverified.

## Where to resume next session

These experiments are pending; do not interpret them as completed results.

1. **Pending:** Before restarting the parser, preserve the existing `csi_data_log.txt` and
   `csi_data.csv`, if present. Inspect the raw line immediately after each error
   marker for truncation, two `CSI_DATA` records joined on one line, or interleaved
   firmware logs, including diagnostic text embedded in the array.
2. **Pending:** Keep board placement and TX frequency fixed. Capture 30 seconds
   at the original 100 ms plot refresh interval, `self.timer.start(100)`.
   Then change only `self.timer.start(100)` to `self.timer.start(500)` and capture
   another 30 seconds. Use separate CSV and log filenames for each run.
   Compare valid and rejected record counts.
3. **Pending:** If malformed records remain frequent, check the local TX setting
   `CONFIG_SEND_FREQUENCY`. If it is 100 Hz, test 20 Hz as a separate experiment.
   Record any required firmware changes and flashing during the next session.

## Checkpoint scope and source location

This is a documentation-only checkpoint. No experiments, firmware builds,
flashing, or debugging were performed as part of recording it.

The existing Espressif checkout is at
`C:/Users/laisi/embedded_system/esp-csi`, with its upstream remote unchanged.
The local TX antenna changes in
`examples/get-started/csi_send/main/app_main.c` remain in that checkout and are
not included in this documentation commit. Preserve those source changes and
any staged work when resuming.

## Shutdown checkpoint after walking trial 001 — 2026-11-19

The verified collector fix and stationary retest had existed only locally before
this backup. This checkpoint preserves the fixed collector, TX antenna source,
their upstream patch, diagnostics utilities, reports and archived evidence.
The Espressif checkout remains separate and its existing changes are retained.

Trial prefix: `walking_20261119_233028_983555`.
Dataset: `datasets/walking_trial_001/walking_20261119_233028_983555.zip`.
Its inventory and `backup_audit.json` account for all 24 original trial files;
archive members retain original filenames, relative paths and bytes.

The actual route was **one-sided approach and retreat**, because the computer
prevented a complete crossing between the boards. The user moved away, approached
the line near the two boards, then turned back. The planned crossing route remains
in the original manifest, while its actual-route fields and `route_note.json`
record the correction. The boards were fixed, no metal object was directly
between them, and a nearby table's metal corner stayed fixed. Board spacing,
height and walking distance were not measured.

The continuous capture contains **9,763 valid C6 CSV records** including preparation
and capture tails. All four measured protocol intervals had zero format errors.
CSV rows and complete valid raw records match exactly. The 10-second return/settle
interval is labelled transition and excluded from the three-phase comparison.

| Phase | Valid records | Records/s | Missing sequence IDs within valid records | Variability |
|---|---:|---:|---:|---:|
| Stationary before | 2,513 | 83.73 | 215 | 24.9779% |
| Walking | 2,724 | 90.72 | 7 | 17.9048% |
| Return/settle transition | 911 | 90.84 | 0 | Excluded |
| Stationary after | 2,725 | 90.80 | 1 | 15.4048% |

Variability uses the same preselected 80 complex-array indices, non-overlapping
one-second windows, temporal amplitude CV per index, median across indices,
then median across the 30 complete windows in each measured phase. No detection
threshold was fitted. Walking was not higher than both stationary phases, so the
walking response was **inconclusive**, even though variability fell afterward.
Sequence gaps do not independently establish Wi-Fi packet loss.

**Next step: offline analysis of the two stationary baselines.** Compare the
already saved raw/timed records, RSSI distributions, AGC/FFT gains and early/late
windows. The stationary RSSI medians differed substantially (-82 versus -68 dBm),
and gain states changed. Establish why the two stationary baselines differ before
using this result to choose activity scoring or planning another physical trial.
Do not tune a threshold on this single exploratory trial.

The successful stationary retest is preserved in
`diagnostics/20261119_225130_863855_repeat_results.md` and its JSON, with the complete
underlying diagnostic evidence in `datasets/stationary_retest/diagnostics-2026-11-19.zip`.
That repeat reproduced one 256/352 array-length mismatch and a roughly 2.10 MB
backlog in the old collector, while the fixed collector recorded 2,739 valid
records in 30.234 seconds with no format errors or sequence gaps. The specific
driver-overflow mechanism remains an inference; raw/CSV records and old failures
are retained for review.

A stale VS Code TX buffer conflicted with the newer disk version. Both source
versions were saved in the diagnostic archive before resolving the editor state;
the disk version includes the antenna block and is the canonical backup.

This backup task performs no hardware experiment, firmware build, flashing,
frequency/antenna change or threshold fitting. Collector shutdown status and an
exclusive COM7 handle check confirmed release without reading serial data.
