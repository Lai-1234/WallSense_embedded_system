"""Replay saved bytes through the untouched parser, without radio or Qt drawing."""
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import time

source = Path(__file__).with_name('parser_before.py')
raw_path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('original_viewer', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
lines = iter(raw_path.read_bytes().splitlines(keepends=True))
next(lines, None)  # same excluded initial boundary fragment as offline analysis
output = io.StringIO(newline='')
log = io.StringIO()


class ReplaySerial:
    def __init__(self, **kw):
        pass

    def isOpen(self):
        return True

    def readline(self):
        try:
            line = next(lines)
        except StopIteration:
            raise EOFError('replay ended')
        if not line.endswith(b'\n'):
            raise EOFError('partial final line excluded')
        return line

    def close(self):
        pass


module.serial.Serial = ReplaySerial
start = time.perf_counter()
try:
    module.csi_data_read_parse('REPLAY', csv.writer(output), log, callback=lambda colors: None)
except EOFError:
    pass
rows = [row for row in csv.reader(io.StringIO(output.getvalue())) if row]
result = dict(source=str(source), raw=str(raw_path), valid_rows=len(rows),
              replay_seconds=time.perf_counter()-start,
              field_counts=sorted(set(map(len, rows))),
              errors={s:log.getvalue().count(s) for s in
                      ('element number is not equal', 'csi_data_len is not equal', 'data is incomplete')})
raw_path.with_suffix('.replay.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
