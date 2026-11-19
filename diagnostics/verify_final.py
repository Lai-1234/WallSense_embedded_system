import csv
import hashlib
import io
import json
from pathlib import Path
import serial
import wallsense_diag as diag

ROOT = Path(__file__).resolve().parents[1]
checks = {
    ROOT/'esp-csi/examples/get-started/csi_send/main/app_main.c':
        '7355e54fce0577ccd033755eb02e6b262af1db3f5e11c6d1e89b48364a2dcf0f',
    diag.TOOLS/'resume_01.csv':
        'aa24988ba48bcf0f170e1ed2cf1f9f85811843a5e45c73196c90be50a409f898',
    diag.TOOLS/'resume_01_log.txt':
        '3c66efd88bf1aa01a5c3b6b07e7bea0eaa14be7ae5b7ef923dc3096dcb14023c',
}
for p, expected in checks.items():
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    assert actual == expected, (p, actual)
    print('UNCHANGED', p)

summary = json.loads((Path(__file__).parent/'summary.json').read_text())
csv_path = Path(summary['normal_entrypoint']['file'])
with csv_path.open(newline='', encoding='utf-8') as f:
    rows = list(csv.reader(f))
for fields in rows[1:]:
    text = io.StringIO()
    csv.writer(text).writerow(fields)
    assert diag.record(text.getvalue().strip())[0] == 'valid'
print('NORMAL_CSV_VALID_RECORDS', len(rows)-1)
for pattern in ('*fixed_live_verified.terminal.txt', '*normal_entrypoint.terminal.txt'):
    terminal = sorted(Path(__file__).parent.glob(pattern))[-1]
    raw = terminal.read_bytes()
    content = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8')
    assert 'Traceback' not in content, terminal
    print('NO_APPLICATION_TRACEBACK', terminal.name)

with serial.Serial('COM7', 921600, timeout=0.1) as port:
    assert port.is_open
    print('COM7_REOPEN_AFTER_NORMAL_EXIT', port.is_open)
assert not port.is_open
print('COM7_CLOSED', not port.is_open)
(Path(__file__).parent/'final_verification.json').write_text(json.dumps(dict(
    original_files_unchanged=True, normal_csv_valid_records=len(rows)-1,
    normal_exit_code=0, com7_reopened=True, com7_closed=True,
    application_traceback=False), indent=2), encoding='utf-8')
