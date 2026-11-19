# WallSense: Person B checkpoint — 2026-11-19

This checkpoint records where Person B paused on 2026-11-19 (Asia/Kuala_Lumpur).
WallSense uses XIAO ESP32-C6 boards and Wi-Fi CSI for human activity detection.
The next session should investigate malformed CSI records before treating capture
or detection as reliable. All experiments below are pending.

## Verified progress

- Both XIAO ESP32-C6 boards were built and flashed using ESP-IDF 5.5.6.
  TX uses COM6 and RX uses COM7. RX continuously outputs `CSI_DATA`.
- TX was configured to select the onboard ceramic antenna: GPIO3 LOW enables
  the RF switch, followed by a 100 ms delay, and GPIO14 LOW selects the onboard
  antenna before NVS and Wi-Fi initialization.
- RX RSSI readings were approximately -87 dBm before the adjustment and -64 dBm
  afterward. The boards were also repositioned, so the antenna's contribution
  was not measured independently.
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

In the second message, one record declared 256 values and the parser found 216.
The proportion of malformed records, where the data became malformed, and the
root cause are still unknown. PyQt plotting load is one hypothesis to test.
Reliable CSV capture, activity scoring, and through-wall detection remain
unverified.

## Where to resume next session

These experiments are pending; do not interpret them as completed results.

1. Before restarting the parser, preserve the existing `csi_data_log.txt` and
   `csi_data.csv`, if present. Inspect the raw line immediately after each error
   marker for truncation, two `CSI_DATA` records joined on one line, or diagnostic
   text embedded in the array.
2. Keep board positions and TX frequency fixed. Capture 30 seconds using the
   original `self.timer.start(100)` setting. Then change only the plot refresh
   interval to `self.timer.start(500)` and capture another 30 seconds. Use separate
   CSV and log filenames for each run. Compare valid-record counts and
   malformed-record counts.
3. If malformed records remain frequent, check the local TX value of
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
