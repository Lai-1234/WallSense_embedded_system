import csv
import hashlib
import json
from pathlib import Path

folder=Path(__file__).resolve().parent/'trials/walking_001_20261119_233028_983555'
manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
prefix=folder/manifest['file_prefix']
analysis=json.loads(prefix.with_suffix('.analysis.json').read_text(encoding='utf-8'))
assert analysis['csv_valid'] and analysis['csv_raw_exact_match']
assert all(not q['format_errors'] and q['unknown_serial_lines']==0 for q in analysis['quality'])
assert [q['usable_windows'] for q in analysis['quality']]==[30,30,10,30]
assert analysis['actual_route_note']==manifest['actual_route_note'] and '?' not in manifest['actual_route_note']
report=prefix.with_suffix('.report.md').read_text(encoding='utf-8')
assert manifest['actual_route_note'] in report and '????????' not in report
with prefix.with_suffix('.phase_times.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=list(analysis['phases'][0]));writer.writeheader();writer.writerows(analysis['phases'])
hashes={}
for suffix in ('.raw','.csi.csv','.log.txt','.read_times.csv','.accepted_times.csv','.phase_events.jsonl'):
    p=prefix.with_suffix(suffix)
    hashes[p.name]=dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
prefix.with_suffix('.acquisition_sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print('ACQUISITION_ARTIFACTS_VERIFIED',analysis['csv_rows'],'CSV rows',sum(q['valid_records'] for q in analysis['quality']),'phase records')
print('READ_TO_PARSE_DELAY_SECONDS',analysis['parse_delay_s'])
