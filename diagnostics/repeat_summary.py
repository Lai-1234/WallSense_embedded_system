"""Summarize the repeat prompted by the user's motion/occlusion clarification."""
import contextlib
import csv
from datetime import datetime
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import statistics
import wallsense_diag as diag

OUT = Path(__file__).resolve().parent
results = []
for label in ('repeat_raw_COM7', 'repeat_original', 'repeat_fixed'):
    meta_path = sorted(OUT.glob('*_' + label + '.meta.json'))[-1]
    meta = json.loads(meta_path.read_text())
    raw_path = meta_path.with_suffix('').with_suffix('.raw')
    with contextlib.redirect_stdout(io.StringIO()):
        analysis = diag.analyze(raw_path, meta['duration'])
    complete = raw_path.read_bytes().split(b'\n')[1:-1]
    fields = []
    for line in complete:
        if b'CSI_DATA' in line and diag.record(line.rstrip(b'\r'))[0] == 'valid':
            fields.append(next(csv.reader([line.decode().rstrip('\r')], strict=True)))
    timestamps = [int(row[9]) for row in fields]
    rssis = [int(row[3]) for row in fields]
    extras = dict(rssi_min=min(rssis) if rssis else None,
                  rssi_median=statistics.median(rssis) if rssis else None,
                  rssi_max=max(rssis) if rssis else None,
                  rx_first_timestamp=timestamps[0] if timestamps else None,
                  rx_last_timestamp=timestamps[-1] if timestamps else None,
                  rx_timestamp_span_seconds=((timestamps[-1]-timestamps[0]) & 0xffffffff)/1e6
                    if timestamps else None)
    csv_path = raw_path.with_suffix('.csv')
    csv_info = None
    if csv_path.exists():
        with csv_path.open(newline='', encoding='utf-8') as f:
            rows = list(csv.reader(f))
        nonempty = [row for row in rows[1:] if row]
        invalid = 0
        for row in nonempty:
            text = io.StringIO()
            csv.writer(text).writerow(row)
            invalid += diag.record(text.getvalue().strip())[0] != 'valid'
        csv_info = dict(header_fields=len(rows[0]), data_rows=len(nonempty),
                        invalid=invalid, blank_rows=sum(not row for row in rows[1:]),
                        field_counts=sorted(set(map(len, nonempty))),
                        array_lengths=sorted(set(len(json.loads(row[-1])) for row in nonempty)))
    terminal_path = raw_path.with_suffix('.terminal.txt')
    terminal = terminal_path.read_text(encoding='utf-8') if terminal_path.exists() else ''
    result = dict(label=label, metadata=meta, analysis=analysis, csv=csv_info,
                   terminal_traceback='Traceback' in terminal, **extras)
    results.append(result)
    print(json.dumps(dict(label=label, duration=meta['duration'], bytes=analysis['bytes'],
                          counts=analysis['counts'], valid_per_second=analysis['valid_per_second'],
                          max_pending=meta['max_pending'], sequence=analysis['sequence'],
                          csv=csv_info, **extras), indent=2))

root = OUT.parent
source = root/'esp-csi/examples/get-started/tools/csi_data_read_parse.py'
tx = root/'esp-csi/examples/get-started/csi_send/main/app_main.c'
assert hashlib.sha256(source.read_bytes()).hexdigest() == '9456a557c499b47787cf6b2078fd3e7437cab568c9b031c2c3efd32bebe20b69'
assert hashlib.sha256(tx.read_bytes()).hexdigest() == '7355e54fce0577ccd033755eb02e6b262af1db3f5e11c6d1e89b48364a2dcf0f'

# Replay this round's exact raw baseline through the fixed parser without serial
# or drawing. All source imports and array processing happen after live tests.
spec = importlib.util.spec_from_file_location('repeat_viewer', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raw_baseline = Path(results[0]['analysis']['file'])
lines = raw_baseline.read_bytes().splitlines(keepends=True)[1:]
csv_output, replay_log = io.StringIO(newline=''), io.StringIO()
with contextlib.redirect_stdout(io.StringIO()):
    module._parse_serial_lines(lines, csv.writer(csv_output), replay_log)
rows = list(csv.reader(io.StringIO(csv_output.getvalue())))
replay = dict(valid_rows=len(rows)-1, header_fields=len(rows[0]),
              errors={m: replay_log.getvalue().count(m) for m in
                      ('element number is not equal', 'csi_data_len is not equal', 'data is incomplete')})
assert replay['valid_rows'] == results[0]['analysis']['counts'].get('valid', 0)
print('FIXED_EXACT_REPLAY', json.dumps(replay))

import serial
with serial.Serial('COM7', 921600, timeout=0.1) as port:
    reopened = port.is_open
assert reopened and not port.is_open
print('COM7_REOPENED_AND_CLOSED', True)
prefix = OUT / f'{datetime.now():%Y%m%d_%H%M%S_%f}_repeat_results'
summary = dict(user_clarification='User moved between boards and occluded devices during the preceding session.',
                conditions='Requested stationary boards and no movement/occlusion for this repeat; physical compliance not independently observed.',
                results=results, fixed_exact_replay=replay, port_reopened_and_closed=True,
                source_unchanged=True, tx_unchanged=True)
prefix.with_suffix('.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
table = ['| 测试 | 秒 | 读取字节 | 有效 CSI | 损坏 CSI | 有效条/秒 | 最大待读字节 | 序号间断/缺失序号 |',
         '|---|---:|---:|---:|---:|---:|---:|---:|']
for title, result in zip(('原始字节', '旧程序快照', '当前修复版'), results):
    a, m = result['analysis'], result['metadata']
    bad = sum(v for k,v in a['counts'].items() if k != 'valid')
    table.append(f"| {title} | {m['duration']:.3f} | {a['bytes']:,} | {a['counts'].get('valid',0):,} | {bad} | {a['valid_per_second']:.2f} | {m['max_pending']:,} | {a['sequence']['gap_events']} / {a['sequence']['absent_sequence_ids']} |")
fixed = results[-1]
text = f'''# WallSense 复测 — 2026-11-19

用户补充：上一轮期间曾在两块 ESP32 之间摆动并遮挡设备。因此上一轮不满足
静止、无遮挡的受控条件，接收数量和序号缺口不能用于单独归因主机或无线变化。
本轮已请用户保持两块板子固定、不摆动、不遮挡；代理不能独立观察物理操作。

未修改项目源码，未烧录、降低 TX 频率、暂存、提交或推送。当前仍为 COM7、
921600 baud，TX 名义设置 100 Hz，GUI 定时设置 100 ms。原始采集 DTR/RTS
与 GUI 默认值一致。各阶段约 30 秒、顺序执行，每阶段只有一个串口读取者。
旧版通过修改前快照运行，没有回退或覆盖当前源码。

{chr(10).join(table)}

完整记录损坏与序号缺口分开统计。首行边界和末尾片段不计为中间损坏；
序号缺口只表示这些已收到记录之间缺少序号，不能直接认定 Wi-Fi 丢包。
各段不是同一批无线包，不能直接把不同缺口数归因软件改进。

修复版 CSV 检查：{fixed['csv']['data_rows']} 条、{fixed['csv']['header_fields']} 列表头，
数据字段数 {fixed['csv']['field_counts']}，数组长度 {fixed['csv']['array_lengths']}，
无效 CSV 记录 {fixed['csv']['invalid']}，空行 {fixed['csv']['blank_rows']}。
绘图更新 {fixed['metadata']['plot_updates']} 次，相位变化
{fixed['metadata']['phase_changed_updates']} 次；绘图异常
{fixed['metadata']['plot_exceptions']} 次。
关闭后串口打开状态为 {fixed['metadata']['serial_open_after_window_close']}，
线程运行状态为 {fixed['metadata']['thread_running_after_window_close']}；随后重开并关闭 COM7 成功。
精确原始字节离线重放也得到 {replay['valid_rows']} 条有效记录。

完整统计、RSSI 范围、RX 时间戳跨度、边界片段、原始文件路径及哈希见同名 JSON。
每轮 raw、CSV、log、terminal、meta 均为独立时间戳文件，未覆盖上一轮证据。
项目解析器及 TX 源码哈希均与本轮开始前一致。
'''
prefix.with_suffix('.md').write_text(text, encoding='utf-8')
print('REPORT', prefix.with_suffix('.md'))
