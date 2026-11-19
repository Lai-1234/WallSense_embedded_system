"""WallSense trial controller; imports the verified collector without editing it."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'esp-csi/examples/get-started/tools/csi_data_read_parse.py'
EXPECTED_SOURCE = '9456a557c499b47787cf6b2078fd3e7437cab568c9b031c2c3efd32bebe20b69'
EXPECTED_TX = '7355e54fce0577ccd033755eb02e6b262af1db3f5e11c6d1e89b48364a2dcf0f'
TZ = timezone(timedelta(hours=8))
PROTOCOL = [('stationary_before', '保持静止', 30), ('walking', '开始走动', 30),
            ('transition', '回到起点', 10), ('stationary_after', '保持静止', 30)]
SUBCARRIERS = list(range(8,28))+list(range(36,56))+list(range(72,92))+list(range(100,120))


def write_json(p, value):
    temp = p.with_name(p.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(p)


def check_sources():
    tx = ROOT/'esp-csi/examples/get-started/csi_send/main/app_main.c'
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED_SOURCE, 'Collector differs from verified version'
    assert hashlib.sha256(tx.read_bytes()).hexdigest() == EXPECTED_TX, 'TX differs from verified version'


def prepare():
    check_sources()
    stamp = datetime.now(TZ).strftime('%Y%m%d_%H%M%S_%f')
    folder = Path(__file__).parent/'trials'/f'walking_001_{stamp}'
    folder.mkdir(parents=True, exist_ok=False)
    prefix = f'walking_{stamp}'
    manifest = dict(trial='WallSense first exploratory same-room walking trial',
        status='prepared_waiting_for_READY', file_prefix=prefix, port='COM7',
        source=str(SOURCE), source_sha256=EXPECTED_SOURCE, tx_sha256=EXPECTED_TX,
        setup=dict(boards_fixed=True, room='same room', route='Back and forth across the midpoint of the TX-RX line at normal pace',
                   direct_metal_obstruction=False, nearby_table_metal_corner='present and will remain fixed',
                   board_spacing_m=None, tx_height_m=None, rx_height_m=None,
                   starting_spot='User-selected original spot; return to the same spot'),
        settings=dict(baud=921600, bytesize=8, parity='N', stopbits=1, read_timeout_s=0.1,
                      tx_config_send_frequency=100, plot_interval_ms=100, firmware_changed=False,
                      tx_antenna='existing GPIO3 LOW / GPIO14 LOW preserved'),
        countdown_seconds=10, protocol=[dict(name=n,cue=c,seconds=s) for n,c,s in PROTOCOL],
        metric=dict(subcarrier_indices_zero_based=SUBCARRIERS, iq_order='Q,I pairs as in the collector',
                    amplitude='sqrt(I^2 + Q^2), firmware gain compensation retained',
                    window_seconds=1.0, overlapping=False,
                    window_metric='median over the fixed 80 indices of sample_std(amplitude,ddof=1)/mean(amplitude), percent',
                    phase_summary='median of complete 1-second window values; transition excluded',
                    zero_mean_rule='whole window unavailable if any selected index has zero mean; no adaptive index removal',
                    minimum_records_per_window=2, threshold_fitting=False))
    write_json(folder/'manifest.json', manifest)
    print(folder, flush=True)
    return folder


def collect(folder):
    check_sources()
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    prefix = folder/manifest['file_prefix']
    terminal = prefix.with_suffix('.collector_terminal.txt').open('x', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = terminal
    spec = importlib.util.spec_from_file_location('verified_wallsense_collector', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stats = dict(valid_rows=0, bytes=0, read_calls=0, max_pending=0, max_read_gap_s=0,
                 plot_updates=0, plot_exceptions=0)
    raw = prefix.with_suffix('.raw').open('xb')
    chunks = prefix.with_suffix('.read_times.csv').open('x', newline='', encoding='utf-8')
    cw = csv.writer(chunks)
    cw.writerow(['byte_start','byte_end','read_start_mono_ns','read_end_mono_ns','pending_before'])
    accepted = prefix.with_suffix('.accepted_times.csv').open('x', newline='', encoding='utf-8')
    aw = csv.writer(accepted)
    aw.writerow(['data_row','seq','rx_timestamp_us','parse_write_mono_ns'])
    instances, last_read = [], [None]
    native_serial = module.serial.Serial

    class TimedSerial(native_serial):
        def __init__(self,*a,**kw):
            super().__init__(*a,**kw)
            instances.append(self)
            stats['port_open_mono_ns'] = time.perf_counter_ns()
            elapsed = (stats['port_open_mono_ns']-manifest['clock']['mono_ns'])/1e9
            assert 0 <= elapsed < 120, 'Cross-process monotonic clock check failed'

        def read(self,*a,**kw):
            before = time.perf_counter_ns()
            if last_read[0] is not None:
                stats['max_read_gap_s'] = max(stats['max_read_gap_s'], (before-last_read[0])/1e9)
            last_read[0] = before
            pending = self.in_waiting
            stats['max_pending'] = max(stats['max_pending'], pending)
            data = super().read(*a,**kw)
            end = time.perf_counter_ns()
            offset = stats['bytes']
            if data:
                raw.write(data)
                stats['bytes'] += len(data)
                cw.writerow([offset,stats['bytes'],before,end,pending])
            stats['read_calls'] += 1
            return data

    module.serial.Serial = TimedSerial

    class TimedWriter:
        def __init__(self,writer):
            self.writer = writer
        def writerow(self,row):
            result = self.writer.writerow(row)
            if row and row[0] == 'CSI_DATA':
                stats['valid_rows'] += 1
                now = time.perf_counter_ns()
                aw.writerow([stats['valid_rows'],row[1],row[9],now])
                if stats['valid_rows'] == 1:
                    write_json(folder/'collector_ready.json', dict(mono_ns=now, seq=row[1], rssi=row[3]))
            return result

    class CSVFacade:
        def writer(self,*a,**kw):
            return TimedWriter(csv.writer(*a,**kw))
        def __getattr__(self,name):
            return getattr(csv,name)

    module.csv = CSVFacade()
    app = module.QApplication([])
    window = module.csi_data_graphical_window()
    window.setWindowTitle('WallSense walking trial — verified CSI collector')
    original_update = window.update_data
    def update():
        try:
            original_update()
            stats['plot_updates'] += 1
        except Exception:
            stats['plot_exceptions'] += 1
            traceback.print_exc()
    window.timer.timeout.disconnect()
    window.timer.timeout.connect(update)
    assert window.timer.interval() == 100
    worker = module.SubThread('COM7',str(prefix.with_suffix('.csi.csv')),str(prefix.with_suffix('.log.txt')))
    window.reader = worker
    worker.data_ready.connect(window.update_curve_colors)
    app.aboutToQuit.connect(worker.stop)
    worker.start()
    window.show()
    poll = module.QtCore.QTimer()
    def check_stop():
        if (folder/'STOP').exists():
            stats['stop_observed_mono_ns'] = time.perf_counter_ns()
            window.close()
        elif not worker.isRunning():
            stats['worker_ended_early'] = True
            window.close()
    poll.timeout.connect(check_stop)
    poll.start(50)
    code = app.exec()
    worker.stop()
    worker.wait()
    stats.update(closed_mono_ns=time.perf_counter_ns(),serial_open_after_close=any(s.is_open for s in instances),
                 worker_running_after_close=worker.isRunning(),exit_code=code)
    raw.close(); chunks.close(); accepted.close()
    write_json(prefix.with_suffix('.collector_stats.json'),stats)
    write_json(folder/'collector_stopped.json',stats)
    print('COLLECTOR_FINAL',json.dumps(stats),flush=True)
    return code


def control(folder):
    from PyQt5 import QtCore, QtGui, QtWidgets
    import winsound
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'prepared_waiting_for_READY', 'This trial directory has already been used'
    check_sources()
    # Actual READY has been received before this command is launched by the agent.
    mono = time.perf_counter_ns()
    manifest.update(status='starting_after_READY',clock=dict(mono_ns=mono,unix_ns=time.time_ns(),
        local_timezone='Asia/Kuala_Lumpur',implementation=time.get_clock_info('perf_counter').implementation),
        ready_received_before_launch=True)
    write_json(folder/'manifest.json',manifest)
    prefix = folder/manifest['file_prefix']
    events = prefix.with_suffix('.phase_events.jsonl').open('x',encoding='utf-8',buffering=1)
    lock = threading.Lock()
    def event(kind,**kw):
        now = time.perf_counter_ns()
        unix = manifest['clock']['unix_ns'] + now-manifest['clock']['mono_ns']
        item = dict(event=kind,mono_ns=now,unix_ns=unix,
                    local_time=datetime.fromtimestamp(unix/1e9,TZ).isoformat(timespec='milliseconds'),**kw)
        with lock:
            events.write(json.dumps(item,ensure_ascii=False)+'\n')
        print(json.dumps(item,ensure_ascii=False),flush=True)
        return now

    speech_script = Path(__file__).with_name('walking_voice.ps1')
    speech_log = prefix.with_suffix('.speech.txt').open('x',encoding='utf-8')
    speech = subprocess.Popen(['powershell.exe','-NoProfile','-File',str(speech_script)],
        stdin=subprocess.PIPE,stdout=speech_log,stderr=subprocess.STDOUT,encoding='utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW)
    def sound(text):
        event('speech_requested',text=text)
        try:
            speech.stdin.write(text+'\n'); speech.stdin.flush()
        except (BrokenPipeError,OSError):
            event('speech_unavailable',text=text)
        def beep():
            try:
                event('beep_start',text=text)
                winsound.Beep(1000,180)
            except RuntimeError:
                event('beep_unavailable',text=text)
        threading.Thread(target=beep,daemon=True).start()

    app = QtWidgets.QApplication([])
    cue = QtWidgets.QWidget()
    cue.setWindowTitle('WallSense 行走试验 — 自动提示')
    cue.setWindowFlags(cue.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
    cue.resize(1000,300); cue.move(250,15)
    layout = QtWidgets.QVBoxLayout(cue)
    title = QtWidgets.QLabel('正在准备采集器')
    title.setAlignment(QtCore.Qt.AlignCenter)
    title.setFont(QtGui.QFont('Microsoft YaHei',44,QtGui.QFont.Bold))
    detail = QtWidgets.QLabel('正式计时尚未开始，请稍候')
    detail.setAlignment(QtCore.Qt.AlignCenter)
    detail.setFont(QtGui.QFont('Microsoft YaHei',22))
    remaining = QtWidgets.QLabel('')
    remaining.setAlignment(QtCore.Qt.AlignCenter)
    remaining.setFont(QtGui.QFont('Microsoft YaHei',30))
    for widget in (title,detail,remaining): layout.addWidget(widget)
    cue.setStyleSheet('background:#15314b;color:white;')
    cue.show(); cue.raise_()
    child = subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--collect',str(folder)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    event('collector_launched',pid=child.pid)
    state = dict(mode='initializing',index=-1,deadline=None,phase_start=None,last_count=None,finished=False)
    start_wait = time.perf_counter_ns()
    def begin_phase(index):
        name,text,seconds = PROTOCOL[index]
        state.update(mode='phase',index=index,last_count=None)
        title.setText(text)
        detail.setText({'stationary_before':'第一段：在起点站稳，不碰键盘或设备',
            'walking':'正常速度来回走动，穿过两板连线中点',
            'transition':'回到原起点站稳；这 10 秒不参与比较',
            'stationary_after':'第三段：在原起点保持静止'}[name])
        cue.setStyleSheet('background:'+{'walking':'#176445','transition':'#855300'}.get(name,'#15314b')+';color:white;')
        remaining.setText(f'{seconds} 秒')
        cue.repaint()
        now = event('phase_start',phase=name,cue=text,planned_duration_s=seconds)
        state['phase_start'] = now
        state['deadline'] = now + int(seconds*1e9)
        sound(text)

    def abort(reason):
        if state['finished']: return
        state.update(mode='aborted',finished=True)
        event('trial_aborted',reason=reason)
        (folder/'STOP').write_text(reason,encoding='utf-8')
        manifest['status'] = 'aborted'
        write_json(folder/'manifest.json',manifest)
        title.setText('测试中止');detail.setText(reason);remaining.setText('不作行走对比结论')
        cue.repaint()

    def tick():
        now = time.perf_counter_ns()
        if state['mode'] == 'initializing':
            if (folder/'collector_ready.json').exists():
                state.update(mode='countdown',last_count=None)
                title.setText('准备：10 秒后开始')
                detail.setText('请放下键盘，前往起点；到位后等待“保持静止”')
                remaining.setText('10')
                cue.repaint()
                start = event('countdown_start',seconds=10)
                state['deadline'] = start + int(10e9)
                sound('十秒后开始，请前往起点')
            elif child.poll() is not None or (now-start_wait)/1e9 > 45:
                abort('采集器没有就绪，请保持不动，等待检查')
        elif state['mode'] == 'countdown':
            if now >= state['deadline']:
                begin_phase(0)
            else:
                value = math.ceil((state['deadline']-now)/1e9)
                if value != state['last_count']:
                    state['last_count'] = value
                    remaining.setText(str(value))
                    event('countdown_tick',remaining=value)
                    if value in (3,2,1): sound(str(value))
        elif state['mode'] == 'phase':
            if child.poll() is not None:
                abort('采集器提前退出，本次数据需标记不完整')
                return
            if now >= state['deadline']:
                index = state['index']+1
                if index < len(PROTOCOL):
                    begin_phase(index)
                else:
                    state.update(mode='saving',deadline=now+int(15e9))
                    event('measurement_end',phase='stationary_after')
                    (folder/'STOP').write_text('protocol completed',encoding='utf-8')
                    title.setText('正在保存');detail.setText('请稍候，正在关闭串口');remaining.setText('')
                    cue.repaint()
            else:
                remaining.setText(f'剩余 {math.ceil((state["deadline"]-now)/1e9)} 秒')
        elif state['mode'] == 'saving':
            if (folder/'collector_stopped.json').exists() and child.poll() is not None:
                stats = json.loads((folder/'collector_stopped.json').read_text())
                if stats['serial_open_after_close'] or stats['worker_running_after_close']:
                    abort('串口未正常关闭')
                    return
                event('trial_complete',collector_exit_code=child.returncode)
                manifest['status'] = 'complete'
                write_json(folder/'manifest.json',manifest)
                title.setText('测试完成');detail.setText('文件已保存，串口已释放；可以回到电脑')
                remaining.setText('完成');cue.repaint();sound('测试完成，可以回到电脑')
                state.update(mode='complete',finished=True)
                QtCore.QTimer.singleShot(4000,app.quit)
            elif now >= state['deadline']:
                abort('等待采集器关闭超时；保留全部文件检查')
        if state['mode'] == 'aborted' and child.poll() is not None:
            QtCore.QTimer.singleShot(4000,app.quit)
    timer = QtCore.QTimer();timer.timeout.connect(tick);timer.start(20)
    def about_quit():
        if not state['finished']: abort('提示窗口被提前关闭')
    app.aboutToQuit.connect(about_quit)
    app.exec()
    if child.poll() is None:
        (folder/'STOP').write_text('controller exiting',encoding='utf-8')
        child.wait(timeout=20)
    if speech.stdin:
        speech.stdin.close()
    try: speech.wait(timeout=5)
    except subprocess.TimeoutExpired: speech.terminate();speech.wait(timeout=5)
    speech_log.close();events.close()
    print('TRIAL_DIRECTORY',folder,flush=True)
    return 0 if manifest['status'] == 'complete' else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--run',type=Path)
    group.add_argument('--collect',type=Path)
    args = parser.parse_args()
    if args.prepare: prepare()
    elif args.run: sys.exit(control(args.run))
    else: sys.exit(collect(args.collect))
