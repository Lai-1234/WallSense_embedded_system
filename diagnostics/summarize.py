import contextlib
import csv
import io
import json
from pathlib import Path
import re
import wallsense_diag as diag

OUT = Path(__file__).parent
runs = []
for label in ('raw_baseline_COM7', 'original_live', 'original_no_draw',
              'chunk_reader_original_plot', 'fixed_live_verified'):
    meta_path = sorted(OUT.glob('*_' + label + '.meta.json'))[-1]
    meta = json.loads(meta_path.read_text())
    raw = meta_path.with_suffix('').with_suffix('.raw')
    with contextlib.redirect_stdout(io.StringIO()):
        analysis = diag.analyze(raw, meta['duration'])
    csv_path = raw.with_suffix('.csv')
    csv_info = None
    if csv_path.exists():
        with csv_path.open(newline='', encoding='utf-8') as f:
            rows = list(csv.reader(f))
        data = [row for row in rows[1:] if row]
        reasons = {}
        for row in data:
            stream = io.StringIO()
            csv.writer(stream).writerow(row)
            reason, _, _ = diag.record(stream.getvalue().strip())
            reasons[reason] = reasons.get(reason, 0)+1
        csv_info = dict(header_fields=len(rows[0]), rows=len(data),
                        blank_rows=sum(not row for row in rows[1:]), validation=reasons)
    item = dict(label=label, metadata=meta, analysis=analysis, csv=csv_info)
    runs.append(item)
    print(json.dumps(dict(label=label, seconds=round(meta['duration'], 3), bytes=len(raw.read_bytes()),
                          valid=analysis['counts'].get('valid', 0),
                          malformed=sum(v for k,v in analysis['counts'].items() if k != 'valid'),
                          valid_per_second=round(analysis['valid_per_second'], 2),
                          max_pending=meta.get('max_pending'), sequence=analysis['sequence'],
                          csv=csv_info), ensure_ascii=False))

normal_path = sorted(OUT.glob('*_normal_entrypoint.csv'))[-1]
with normal_path.open(newline='', encoding='utf-8') as f:
    rows = list(csv.reader(f))
normal = dict(file=str(normal_path), rows=len(rows)-1, blank_rows=sum(not row for row in rows),
              header_fields=len(rows[0]), fields=sorted(set(map(len, rows))),
              value_lengths=sorted(set(len(json.loads(row[-1])) for row in rows[1:])))
print('NORMAL_ENTRYPOINT', json.dumps(normal))
result = dict(runs=runs, normal_entrypoint=normal)
(OUT/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

log = diag.TOOLS/'resume_01_log.txt'
details = []
for text in log.read_text(encoding='utf-8').splitlines():
    if not text.startswith('CSI_DATA'):
        continue
    reason, detail, _ = diag.record(text)
    fields = next(csv.reader([text]))
    excerpt = None
    for pattern in (r'.{0,25}6,,0.{0,25}', r'.{0,25}36-29.{0,25}'):
        match = re.search(pattern, text)
        if match:
            excerpt = match.group()
    details.append(dict(seq=fields[1], reason=reason, detail=detail, excerpt=excerpt))
print('HISTORY_ERRORS', json.dumps(details, indent=2))
(OUT/'historical_errors.json').write_text(json.dumps(details, indent=2), encoding='utf-8')
