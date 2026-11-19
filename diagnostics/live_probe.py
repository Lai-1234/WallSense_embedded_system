"""Run the local viewer with timed observation; retain all evidence separately."""
import argparse
import csv
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=float, default=30)
parser.add_argument('--interval', type=int, default=100)
parser.add_argument('--no-draw', action='store_true')
parser.add_argument('--chunk-lines', action='store_true')
parser.add_argument('--observe-read', action='store_true')
parser.add_argument('--label', default='original_live')
parser.add_argument('--source', type=Path, default=ROOT/'esp-csi/examples/get-started/tools/csi_data_read_parse.py')
args = parser.parse_args()
prefix = OUT / f'{datetime.now():%Y%m%d_%H%M%S_%f}_{args.label}'
terminal = prefix.with_suffix('.terminal.txt').open('x', encoding='utf-8', buffering=1)
sys.stdout = sys.stderr = terminal
print('SOURCE', args.source, hashlib.sha256(args.source.read_bytes()).hexdigest(), flush=True)
spec = importlib.util.spec_from_file_location('wallsense_viewer', args.source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
serial_type = module.serial.Serial
raw = prefix.with_suffix('.raw').open('xb')
stats = dict(serial_bytes=0, serial_lines=0, max_pending=0, max_readline_gap=0,
             plot_updates=0, plot_exceptions=0, phase_changed_updates=0)
instances = []
start = [None]
last_read = [None]
files = []


class ObservedSerial(serial_type):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        instances.append(self)
        start[0] = time.perf_counter()
        self.line_buffer = bytearray()

    def read(self, *a, **kw):
        if not args.observe_read:
            return super().read(*a, **kw)
        now = time.perf_counter()
        if last_read[0] is not None:
            stats['max_readline_gap'] = max(stats['max_readline_gap'], now-last_read[0])
        last_read[0] = now
        stats['max_pending'] = max(stats['max_pending'], self.in_waiting)
        chunk = super().read(*a, **kw)
        raw.write(chunk)
        stats['serial_bytes'] += len(chunk)
        stats['serial_lines'] += chunk.count(b'\n')
        return chunk

    def readline(self, *a, **kw):
        now = time.perf_counter()
        if last_read[0] is not None:
            stats['max_readline_gap'] = max(stats['max_readline_gap'], now-last_read[0])
        last_read[0] = now
        stats['max_pending'] = max(stats['max_pending'], self.in_waiting)
        if args.chunk_lines:
            while b'\n' not in self.line_buffer:
                self.line_buffer.extend(self.read(min(max(self.in_waiting, 1), 65536)))
            end = self.line_buffer.index(b'\n') + 1
            line = bytes(self.line_buffer[:end])
            del self.line_buffer[:end]
        else:
            line = super().readline(*a, **kw)
        raw.write(line)
        stats['serial_bytes'] += len(line)
        stats['serial_lines'] += 1
        return line


if not args.observe_read:
    ObservedSerial.read = serial_type.read
module.serial.Serial = ObservedSerial


def opened(*a, **kw):
    f = open(*a, **kw)
    files.append(f)
    return f


module.open = opened
app = module.QApplication([])
window = module.csi_data_graphical_window()
window.setWindowTitle(f'WallSense diagnostic: {args.label}')
original_update = window.update_data
previous_phase = [None]


def update():
    try:
        original_update()
        stats['plot_updates'] += 1
        phase = window.curve.getData()[1]
        if phase is not None:
            stats['phase_points'] = len(phase)
            if previous_phase[0] is not None and not module.np.array_equal(previous_phase[0], phase):
                stats['phase_changed_updates'] += 1
            previous_phase[0] = phase.copy()
        stats['iq_points'] = len(window.iq_scatter.getData()[0])
    except Exception:
        stats['plot_exceptions'] += 1
        traceback.print_exc()


window.timer.timeout.disconnect()
window.timer.timeout.connect(update)
window.timer.setInterval(args.interval)
if args.no_draw:
    window.timer.stop()
thread = module.SubThread('COM7', str(prefix.with_suffix('.csv')), str(prefix.with_suffix('.log.txt')))
window.reader = thread
thread.data_ready.connect(window.update_curve_colors)
thread.start()
window.show()


def request_close():
    print('REQUEST_WINDOW_CLOSE', time.perf_counter()-start[0] if start[0] else None, flush=True)
    module.QtCore.QMetaObject.invokeMethod(window, 'close', module.QtCore.Qt.QueuedConnection)


watchdog = threading.Timer(args.seconds, request_close)
watchdog.daemon = True
watchdog.start()
app.exec()
end = time.perf_counter()
stats.update(duration=end-start[0] if start[0] else None, requested_seconds=args.seconds,
             interval=args.interval, no_draw=args.no_draw,
             serial_open_after_window_close=any(s.is_open for s in instances),
             thread_running_after_window_close=thread.isRunning(),
             output_prefix=str(prefix))
for f in files:
    if not f.closed:
        f.flush()
raw.flush()
prefix.with_suffix('.meta.json').write_text(json.dumps(stats, indent=2), encoding='utf-8')
print('FINAL', json.dumps(stats), flush=True)
# The original viewer has no cooperative stop. Terminate only this diagnostic
# process after recording that fact; this releases the OS handle and preserves files.
# A fixed viewer should already have stopped its worker in closeEvent.
os._exit(0)
