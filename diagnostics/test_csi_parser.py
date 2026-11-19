"""Targeted framing, validation, preservation and replay checks for WallSense."""
import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'esp-csi/examples/get-started/tools/csi_data_read_parse.py'
spec = importlib.util.spec_from_file_location('viewer', SOURCE)
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def line(seq=1, data=None, length=256):
    stream = io.StringIO(newline='')
    fields = ['CSI_DATA', str(seq), '1a:00:00:00:00:00', '-62', '11', '-98',
              '18', '46', '11', '123456', '47', '2', str(length), '0',
              json.dumps([0]*256) if data is None else data]
    csv.writer(stream).writerow(fields)
    return stream.getvalue().encode()


def parse(lines):
    output, log = io.StringIO(newline=''), io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()):
        viewer._parse_serial_lines(lines, csv.writer(output), log)
    return list(csv.reader(io.StringIO(output.getvalue()))), log.getvalue()


class Checks(unittest.TestCase):
    def test_arbitrary_chunk_boundaries_and_timeout(self):
        payload = line(1) + b'I (12) csi_recv: gain log\r\n' + line(2) + b'CSI_DATA,partial'
        for size in (1, 7, 128, 4096):
            stop = threading.Event()
            chunks = [payload[i:i+size] for i in range(0, len(payload), size)]
            chunks.insert(2, b'')  # a read timeout is not a record boundary

            class Port:
                in_waiting = 65536
                def read(self, n):
                    if chunks:
                        return chunks.pop(0)
                    stop.set()
                    return b''

            received = list(viewer.serial_lines(Port(), stop))
            self.assertEqual(b''.join(received), payload)
            rows, log = parse(received)
            self.assertEqual(len(rows), 3)  # header plus two complete data records
            self.assertEqual(rows[0], viewer.DATA_COLUMNS_NAMES_C5C6)
            self.assertTrue(all(len(row) == 15 for row in rows))
            self.assertIn('partial line at capture boundary', log)
            self.assertIn('gain log', log)

    def test_malformed_records_are_logged_not_repaired(self):
        bad = [line(2, '[6,,0]'), line(3, '[36-29]'), line(4, '[1,2]'),
               b'CSI_DATA,broken\n', line(5, 'null'), line(6, '[true]'),
               line(7, '[1,2]', length='not-a-number'),
               line(8).replace(b'CSI_DATA', b'CSI_DATACSI_DATA', 1)]
        rows, log = parse([line(1), *bad, line(9)])
        self.assertEqual([row[1] for row in rows[1:]], ['1', '9'])
        for raw in bad:
            self.assertIn(raw.decode().rstrip('\r\n'), log)
        self.assertIn('data is incomplete', log)
        self.assertIn('csi_data_len is not equal', log)
        self.assertIn('element number is not equal', log)
        self.assertIn('invalid CSI metadata', log)
        self.assertIn('invalid CSI array values', log)

    def test_exact_baseline_replay(self):
        raw = next(Path(__file__).parent.glob('*raw_baseline_COM7.raw')).read_bytes()
        lines = raw.splitlines(keepends=True)[1:]  # initial capture fragment
        rows, log = parse(lines)
        self.assertEqual(len(rows)-1, 2696)
        self.assertTrue(all(len(row) == 15 for row in rows))
        self.assertTrue(all(len(json.loads(row[-1])) == int(row[-3]) == 256 for row in rows[1:]))
        for marker in ('data is incomplete', 'csi_data_len is not equal', 'element number is not equal'):
            self.assertNotIn(marker, log)


if __name__ == '__main__':
    unittest.main(verbosity=2)
