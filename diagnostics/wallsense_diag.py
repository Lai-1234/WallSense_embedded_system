"""Lossless serial capture and offline C6 CSI diagnostics (no Qt)."""
import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'esp-csi/examples/get-started/tools'
OUT = Path(__file__).resolve().parent


def record(line):
    try:
        text = line.decode('utf-8') if isinstance(line, bytes) else line
        fields = next(csv.reader([text], strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        return 'csv_or_encoding', str(exc), None
    if len(fields) != 15:
        return 'field_count', str(len(fields)), None
    if fields[0] != 'CSI_DATA':
        return 'prefix', fields[0], None
    try:
        seq, declared = int(fields[1]), int(fields[12])
    except ValueError as exc:
        return 'metadata', str(exc), None
    try:
        values = json.loads(fields[14])
    except json.JSONDecodeError as exc:
        return 'json', str(exc), None
    if not isinstance(values, list) or any(type(v) is not int for v in values):
        return 'array_type', '', None
    if len(values) != declared:
        return 'array_length', f'declared={declared}, actual={len(values)}', None
    if declared % 2:
        return 'odd_iq_length', str(declared), None
    return 'valid', str(declared), seq


def gaps(seqs):
    jumps = []
    backwards = []
    duplicate = 0
    for a, b in zip(seqs, seqs[1:]):
        delta = (b - a) & 0xffffffff
        if delta == 0:
            duplicate += 1
        elif delta < 0x80000000:
            if delta > 1:
                jumps.append((a, b, delta - 1))
        else:
            backwards.append((a, b))
    return dict(gap_events=len(jumps), absent_sequence_ids=sum(x[2] for x in jumps),
                largest_gaps=sorted(jumps, key=lambda x: x[2], reverse=True)[:10],
                backwards_or_reset=backwards[:10], duplicates=duplicate)


def analyze(p, duration=None, boundaries=True):
    raw = p.read_bytes()
    parts = raw.split(b'\n')
    first = parts.pop(0) if boundaries and parts else b''
    tail = parts.pop() if parts else b''
    counts = collections.Counter()
    lengths = collections.Counter()
    examples = collections.defaultdict(list)
    patterns = collections.Counter()
    seqs = []
    non_csi = collections.Counter()
    csi_bytes = 0
    for line in parts:
        line = line.rstrip(b'\r')
        if b'CSI_DATA' not in line:
            non_csi['gain_log' if b'compensate_gain' in line else 'other'] += 1
            continue
        csi_bytes += len(line) + 1
        reason, detail, seq = record(line)
        counts[reason] += 1
        if reason == 'valid':
            seqs.append(seq)
            lengths[detail] += 1
        else:
            if len(examples[reason]) < 2:
                examples[reason].append(dict(detail=detail, raw=line.decode('utf-8', 'backslashreplace')))
            if line.count(b'CSI_DATA') > 1:
                patterns['multiple_CSI_DATA_prefixes'] += 1
            if b',,' in line.split(b'[', 1)[-1]:
                patterns['empty_array_element'] += 1
            if re.search(rb'\d-\d', line.split(b'[', 1)[-1]):
                patterns['missing_comma_before_negative'] += 1
            if re.search(rb'(?:I|W|E|D) \(\d+\)|compensate_gain', line):
                patterns['firmware_log_inside_record'] += 1
    result = dict(file=str(p), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                  duration=duration, counts=dict(counts), valid_lengths=dict(lengths),
                  non_csi=dict(non_csi), csi_bytes=csi_bytes,
                  valid_per_second=counts['valid']/duration if duration else None,
                  malformed_patterns=dict(patterns), sequence=gaps(seqs),
                  excluded_first_line_bytes=len(first), excluded_final_fragment_bytes=len(tail),
                  first_excerpt=repr(first[:100]), final_excerpt=repr(tail[:100]), examples=dict(examples))
    dest = OUT / (p.name + '.analysis.json')
    dest.write_text(json.dumps(result, indent=2), encoding='utf-8')
    brief = dict(result)
    brief['examples'] = {k: [dict(detail=x['detail'], raw=x['raw'][:160]) for x in v]
                         for k, v in examples.items()}
    print(json.dumps(brief, indent=2))
    return result


def capture(port, seconds, label, baud, default_controls=False):
    import serial
    OUT.mkdir(exist_ok=True)
    p = OUT / f'{datetime.now():%Y%m%d_%H%M%S_%f}_{label}_{port}.raw'
    ser = serial.Serial(port=None, baudrate=baud, timeout=0.05)
    ser.dtr = default_controls
    ser.rts = default_controls
    ser.port = port
    ser.open()
    total = 0
    max_pending = 0
    start = time.perf_counter()
    try:
        with p.open('xb') as f:
            while time.perf_counter()-start < seconds:
                pending = ser.in_waiting
                max_pending = max(max_pending, pending)
                chunk = ser.read(min(max(pending, 1), 65536))
                f.write(chunk)
                total += len(chunk)
    finally:
        elapsed = time.perf_counter()-start
        ser.close()
    meta = dict(port=port, baud=baud, duration=elapsed, bytes=total, max_pending=max_pending,
                dtr=default_controls, rts=default_controls)
    p.with_suffix('.meta.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print('CAPTURE', json.dumps(dict(file=str(p), **meta)))
    analyze(p, elapsed)


def history():
    csv_path = TOOLS/'resume_01.csv'
    log_path = TOOLS/'resume_01_log.txt'
    for p in (csv_path, log_path):
        print('HISTORY', p.name, 'bytes', p.stat().st_size,
              'sha256', hashlib.sha256(p.read_bytes()).hexdigest())
    with csv_path.open(newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    counts = collections.Counter()
    seqs = []
    lens = collections.Counter()
    blank_rows = 0
    for fields in rows[1:]:
        if not fields:
            blank_rows += 1
            continue
        stream = io.StringIO()
        csv.writer(stream).writerow(fields)
        reason, detail, seq = record(stream.getvalue().strip())
        counts[reason] += 1
        lens[(len(fields), detail)] += 1
        if seq is not None:
            seqs.append(seq)
    print(json.dumps(dict(csv_header_fields=len(rows[0]), data_rows=len(rows)-1-blank_rows,
                          blank_rows=blank_rows,
                          validation=dict(counts), layouts={str(k):v for k,v in lens.items()},
                          sequence=gaps(seqs)), indent=2))
    analyze(log_path, boundaries=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('history')
    cap = sub.add_parser('capture')
    cap.add_argument('port')
    cap.add_argument('--seconds', type=float, default=30)
    cap.add_argument('--label', default='baseline')
    cap.add_argument('--baud', type=int, default=921600)
    cap.add_argument('--default-controls', action='store_true',
                     help='Use DTR/RTS True, matching the original and current viewers')
    ana = sub.add_parser('analyze')
    ana.add_argument('file', type=Path)
    ana.add_argument('--duration', type=float)
    args = parser.parse_args()
    if args.action == 'history':
        history()
    elif args.action == 'capture':
        capture(args.port, args.seconds, args.label, args.baud, args.default_controls)
    else:
        analyze(args.file, args.duration)
