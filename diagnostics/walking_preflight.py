"""Short instrumentation check, explicitly not the human walking trial."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import time
import walking_trial as trial

folder = trial.prepare()
manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
manifest.update(trial='Instrumentation self-test, not a walking trial',status='instrumentation_selftest',
                clock=dict(mono_ns=time.perf_counter_ns(),unix_ns=time.time_ns()))
trial.write_json(folder/'manifest.json',manifest)
child = subprocess.Popen([sys.executable,'-u',str(Path(trial.__file__).resolve()),'--collect',str(folder)],
                         creationflags=subprocess.CREATE_NO_WINDOW)
deadline = time.monotonic()+30
try:
    while not (folder/'collector_ready.json').exists():
        if child.poll() is not None or time.monotonic()>deadline:
            raise RuntimeError('Instrumented collector failed to become ready')
        time.sleep(0.1)
    time.sleep(3)
finally:
    (folder/'STOP').write_text('self-test complete',encoding='utf-8')
    child.wait(timeout=20)
prefix=folder/manifest['file_prefix']
stats=json.loads(prefix.with_suffix('.collector_stats.json').read_text())
assert stats['valid_rows']>0 and not stats['serial_open_after_close'] and not stats['worker_running_after_close']
with prefix.with_suffix('.csi.csv').open(newline='',encoding='utf-8') as f:
    rows=list(csv.reader(f))
with prefix.with_suffix('.accepted_times.csv').open(newline='',encoding='utf-8') as f:
    times=list(csv.reader(f))
assert len(rows)==len(times)==stats['valid_rows']+1
assert len(rows[0])==15 and all(len(r)==15 and len(json.loads(r[-1]))==256 for r in rows[1:])
assert prefix.with_suffix('.raw').stat().st_size==stats['bytes']
print('INSTRUMENTATION_SELFTEST_PASSED',json.dumps(stats),flush=True)
voice = subprocess.run(['powershell.exe','-NoProfile','-File',str(Path(trial.__file__).with_name('walking_voice.ps1'))],
    input='提示音自检，正式试验尚未开始。\n',encoding='utf-8',capture_output=True,timeout=15,
    creationflags=subprocess.CREATE_NO_WINDOW)
print('SPEECH_SELFTEST_EXIT',voice.returncode,flush=True)
(folder/'speech_selftest.txt').write_text(voice.stdout+'\n'+voice.stderr,encoding='utf-8')
trial.write_json(folder/'selftest_result.json',dict(instrumentation_passed=True,speech_exit=voice.returncode))
