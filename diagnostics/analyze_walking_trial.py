"""Offline trial QA followed by the predeclared fixed-index variability metric."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import math
from pathlib import Path
import re

import numpy as np
import wallsense_diag as diag

TZ = timezone(timedelta(hours=8))
LABELS = {'stationary_before':'静止 1','walking':'走动','transition':'过渡（不比较）','stationary_after':'静止 2'}


def amplitude_variability(values, indices):
    """Temporal sample CV per index, then median across the same fixed indices."""
    if len(values) < 2:
        return None
    values = np.asarray(values, dtype=np.float64)
    amplitude = np.hypot(values[:, 1::2], values[:, ::2])[:, indices]
    means = amplitude.mean(axis=0)
    if np.any(means <= 0) or not np.isfinite(amplitude).all():
        return None
    return float(np.median(amplitude.std(axis=0, ddof=1)/means)*100)


def iso(mono_ns, clock):
    unix_ns = clock['unix_ns']+int(mono_ns)-clock['mono_ns']
    return datetime.fromtimestamp(unix_ns/1e9,TZ).isoformat(timespec='milliseconds')


def analyze(folder):
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'complete', 'Trial did not complete; no normal trial comparison'
    prefix = folder/manifest['file_prefix']
    events = [json.loads(s) for s in prefix.with_suffix('.phase_events.jsonl').read_text(encoding='utf-8').splitlines()]
    starts = [e for e in events if e['event']=='phase_start']
    assert [e['phase'] for e in starts] == ['stationary_before','walking','transition','stationary_after']
    end = next(e for e in events if e['event']=='measurement_end')
    phases = [dict(name=e['phase'],start_ns=e['mono_ns'],end_ns=(starts[i+1]['mono_ns'] if i+1<len(starts) else end['mono_ns']),
                   actual_start_local=e['local_time']) for i,e in enumerate(starts)]
    t0 = phases[0]['start_ns']
    for p in phases:
        p.update(duration_s=(p['end_ns']-p['start_ns'])/1e9,actual_end_local=iso(p['end_ns'],manifest['clock']))
    with prefix.with_suffix('.phase_times.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(phases[0]));writer.writeheader();writer.writerows(phases)
    def phase_at(t):
        for p in phases:
            if p['start_ns']<=t<p['end_ns']:
                return p['name']
        return 'preroll' if t<t0 else 'postroll'

    with prefix.with_suffix('.read_times.csv').open(newline='',encoding='utf-8') as f:
        chunks = list(csv.DictReader(f))
    chunk_ends = np.array([int(r['byte_end']) for r in chunks],dtype=np.int64)
    chunk_times = np.array([int(r['read_end_mono_ns']) for r in chunks],dtype=np.int64)
    raw = prefix.with_suffix('.raw').read_bytes()
    assert chunk_ends[-1]==len(raw)
    assert np.all(np.diff(chunk_ends)>0) and np.all(np.diff(chunk_times)>=0)
    records,errors,unknown = [],[],[]
    offset = 0
    pieces = raw.split(b'\n')
    boundary = dict(initial_line_bytes=len(pieces[0]),final_fragment_bytes=len(pieces[-1]))
    for i,part in enumerate(pieces[:-1]):
        line = part.rstrip(b'\r')
        line_end = offset+len(part)+1
        chunk_i = int(np.searchsorted(chunk_ends,line_end,side='left'))
        host_ns = int(chunk_times[chunk_i])
        phase = phase_at(host_ns)
        base = dict(host_mono_ns=host_ns,host_local=iso(host_ns,manifest['clock']),
                    trial_s=(host_ns-t0)/1e9,phase=phase,byte_start=offset,byte_end=line_end)
        if b'CSI_DATA' in line:
            reason,detail,seq = diag.record(line)
            if reason=='valid':
                fields = next(csv.reader([line.decode('utf-8')],strict=True))
                if int(fields[-3]) != 256:
                    reason,detail='unexpected_C6_length',fields[-3]
                else:
                    records.append(dict(base,seq=seq,fields=fields,values=json.loads(fields[-1])))
            if reason!='valid':
                # The first unknown line is a stream-opening boundary, never an interior error.
                errors.append(dict(base,reason='initial_boundary' if i==0 else reason,
                                   detail=detail,raw=line.decode('utf-8','backslashreplace')))
        elif line and i>0:
            text = line.decode('utf-8','backslashreplace')
            normal = re.match(r'^(?:\x1b\[[0-9;]*m)?[IWEVD] \(',text) or text.startswith(('type,','ESP-ROM:','Build:','rst:','Saved PC:'))
            if not normal:
                unknown.append(dict(base,raw=text))
        offset = line_end

    with prefix.with_suffix('.csi.csv').open(newline='',encoding='utf-8') as f:
        csv_rows = list(csv.reader(f))
    source_csv_valid = len(csv_rows[0])==15 and all(len(row)==15 for row in csv_rows[1:])
    csv_errors = Counter()
    for fields in csv_rows[1:]:
        buf = io.StringIO();csv.writer(buf).writerow(fields)
        reason,_,_ = diag.record(buf.getvalue().strip())
        if reason!='valid': csv_errors[reason]+=1
    csv_raw_match = Counter(tuple(r['fields']) for r in records)==Counter(tuple(r) for r in csv_rows[1:])
    # Exact matching also verifies that the collector did not silently drop validated records.
    source_csv_valid = source_csv_valid and not csv_errors and csv_raw_match
    with prefix.with_suffix('.accepted_times.csv').open(newline='',encoding='utf-8') as f:
        accepted = list(csv.DictReader(f))
    raw_times = {(str(r['seq']),r['fields'][9]):r['host_mono_ns'] for r in records}
    delays = [(int(a['parse_write_mono_ns'])-raw_times[(a['seq'],a['rx_timestamp_us'])])/1e9
              for a in accepted if (a['seq'],a['rx_timestamp_us']) in raw_times]

    stats = json.loads(prefix.with_suffix('.collector_stats.json').read_text())
    quality = []
    windows = []
    indices = manifest['metric']['subcarrier_indices_zero_based']
    for p in phases:
        selected = [r for r in records if r['phase']==p['name']]
        reasons = Counter(e['reason'] for e in errors if e['phase']==p['name'] and e['reason']!='initial_boundary')
        q = dict(phase=p['name'],duration_s=p['duration_s'],valid_records=len(selected),
                 valid_per_second=len(selected)/p['duration_s'],format_errors=dict(reasons),
                 unknown_serial_lines=sum(r['phase']==p['name'] for r in unknown),
                 sequence=diag.gaps([r['seq'] for r in selected]),
                 rssi_min=min(int(r['fields'][3]) for r in selected) if selected else None,
                 rssi_median=float(np.median([int(r['fields'][3]) for r in selected])) if selected else None,
                 rssi_max=max(int(r['fields'][3]) for r in selected) if selected else None,
                 fft_gain_values=sorted(set(int(r['fields'][6]) for r in selected)),
                 agc_gain_values=sorted(set(int(r['fields'][7]) for r in selected)))
        phase_windows = []
        for second in range(math.floor(p['duration_s'])):
            lo=p['start_ns']+int(second*1e9);hi=lo+int(1e9)
            samples = [r for r in selected if lo<=r['host_mono_ns']<hi]
            v = amplitude_variability([r['values'] for r in samples],indices)
            w=dict(phase=p['name'],start_mono_ns=lo,end_mono_ns=hi,
                   midpoint_trial_s=((lo+hi)/2-t0)/1e9,valid_records=len(samples),variability_percent=v)
            phase_windows.append(w);windows.append(w)
        usable=[w['variability_percent'] for w in phase_windows if w['variability_percent'] is not None]
        q.update(full_windows=len(phase_windows),usable_windows=len(usable),
                 variability_percent=float(np.median(usable)) if usable else None,
                 variability_iqr_percent=[float(x) for x in np.quantile(usable,[.25,.75])] if usable else None)
        quality.append(q)

    # Write quality before examining the amplitude comparison.
    with prefix.with_suffix('.quality.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f)
        writer.writerow(['phase','duration_s','valid_records','valid_records_per_s','format_errors',
                         'unknown_serial_lines','sequence_gap_events','absent_sequence_ids','usable_1s_windows'])
        for q in quality:
            writer.writerow([q['phase'],q['duration_s'],q['valid_records'],q['valid_per_second'],
                json.dumps(q['format_errors']),q['unknown_serial_lines'],q['sequence']['gap_events'],
                q['sequence']['absent_sequence_ids'],q['usable_windows']])
    for p in phases:
        print('PHASE_QUALITY',json.dumps(next(q for q in quality if q['phase']==p['name'])),flush=True)
    print('CSV_RAW_EXACT_MATCH',csv_raw_match,'CSV_VALID',source_csv_valid,flush=True)
    with prefix.with_suffix('.records_timed.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f)
        writer.writerow(['host_read_mono_ns','host_read_local_time','trial_seconds','phase']+csv_rows[0])
        for r in records: writer.writerow([r['host_mono_ns'],r['host_local'],r['trial_s'],r['phase']]+r['fields'])
    with prefix.with_suffix('.variability.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(windows[0]));writer.writeheader();writer.writerows(windows)

    before,walk,after = [next(q for q in quality if q['phase']==name) for name in
                         ('stationary_before','walking','stationary_after')]
    values=[q['variability_percent'] for q in (before,walk,after)]
    if any(v is None for v in values):
        conclusion='有效时间窗不足，无法作出完整的静止—走动—静止比较。'
        higher=fall=None
    else:
        higher=values[1]>max(values[0],values[2]);fall=values[2]<values[1]
        conclusion=('本次走动段的幅度变异指标高于两段静止，停止后下降。' if higher and fall else
                    '本次走动段没有同时高于两段静止，不能得到清晰的行走响应结论。')
        if not higher and fall:
            conclusion+=' 停止后指标确有下降，但仍不足以满足“走动高于前后静止”的比较。'
    quality_issues = not source_csv_valid or any(q['format_errors'] or q['unknown_serial_lines'] or
                         q['usable_windows']<q['full_windows'] for q in quality)
    if quality_issues: conclusion+=' 本次存在数据质量或缺窗问题，波形解释需保留。'
    baseline_note=(f"前后静止 RSSI 中位数分别为 {before['rssi_median']} 与 {after['rssi_median']} dBm，"
                   '增益取值也发生变化；两段静止基线不一致的原因尚未确定，不能仅归因行走。')
    result=dict(trial_directory=str(folder),phases=phases,quality=quality,metric=manifest['metric'],
        csv_valid=bool(source_csv_valid),csv_raw_exact_match=csv_raw_match,csv_errors=dict(csv_errors),
        complete_raw_valid_records=len(records),csv_rows=len(csv_rows)-1,boundaries=boundary,
        errors=errors,unknown_serial_lines=unknown,collector=stats,
        parse_delay_s=dict(median=float(np.median(delays)),p95=float(np.quantile(delays,.95)),maximum=max(delays)) if delays else None,
        walking_higher_than_both=higher,variability_fell_after_stopping=fall,quality_issues=quality_issues,
        conclusion=conclusion,baseline_note=baseline_note,
        actual_route_note=manifest.get('actual_route_note'),setup=manifest['setup'],
        scope='One exploratory same-room trial. Cue timestamps label requested actions; actual human motion not independently observed.')
    prefix.with_suffix('.analysis.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family']='Microsoft YaHei'
    plt.rcParams['axes.unicode_minus']=False
    fig,(ax,qa)=plt.subplots(2,1,figsize=(13,7.5),sharex=True,gridspec_kw={'height_ratios':[3,1]},layout='constrained')
    colors={'stationary_before':'#dceaf7','walking':'#d3eedf','transition':'#ffe6b5','stationary_after':'#dceaf7'}
    for p in phases:
        lo=(p['start_ns']-t0)/1e9;hi=(p['end_ns']-t0)/1e9
        for axis in (ax,qa): axis.axvspan(lo,hi,color=colors[p['name']],alpha=.7,zorder=0)
        ax.text((lo+hi)/2,1.01,LABELS[p['name']],transform=ax.get_xaxis_transform(),ha='center',fontsize=11)
        relevant=[w for w in windows if w['phase']==p['name']]
        ax.plot([w['midpoint_trial_s'] for w in relevant],
                [w['variability_percent'] if w['variability_percent'] is not None else np.nan for w in relevant],
                color='#183e63',marker='.',linewidth=1.5)
        qa.plot([w['midpoint_trial_s'] for w in relevant],[w['valid_records'] for w in relevant],color='#506575',linewidth=1.2)
    ax.set_title('WallSense 同室行走试验 001｜单侧接近／远离，固定 80 个索引，1 秒窗',pad=33,fontsize=14)
    ax.set_ylabel('CSI 幅度相对变异（%）\n固定索引的时间变异系数中位数')
    qa.set_ylabel('有效记录/窗');qa.set_xlabel('距第一段“保持静止”提示的时间（秒）')
    for axis in (ax,qa): axis.grid(alpha=.25);axis.spines[['top','right']].set_visible(False)
    qa.set_xlim(0,(phases[-1]['end_ns']-t0)/1e9)
    summary='  |  '.join(f'{LABELS[q["phase"]]}：{q["variability_percent"]:.3f}%' if q['variability_percent'] is not None else f'{LABELS[q["phase"]]}：缺数据' for q in (before,walk,after))
    fig.supxlabel(summary+'\n阶段值 = 完整 1 秒窗指标的中位数；过渡段不参与比较。单次探索，不代表检测准确率。',fontsize=10)
    fig.savefig(prefix.with_suffix('.variability.png'),dpi=160)
    fig.savefig(prefix.with_suffix('.variability.svg'))
    plt.close(fig)

    table=['| 阶段 | 实际秒数 | 有效记录 | 条/秒 | 格式错误 | 序号间断/缺失序号 | 幅度变异指标 |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for q in quality:
        metric='不参与比较' if q['phase']=='transition' else (f"{q['variability_percent']:.4f}%" if q['variability_percent'] is not None else '无法计算')
        table.append(f"| {LABELS[q['phase']]} | {q['duration_s']:.3f} | {q['valid_records']} | {q['valid_per_second']:.2f} | {sum(q['format_errors'].values())} | {q['sequence']['gap_events']} / {q['sequence']['absent_sequence_ids']} | {metric} |")
    timing='\n'.join(f"- {LABELS[p['name']]}：{p['actual_start_local']} → {p['actual_end_local']}" for p in phases)
    report=f'''# WallSense 首次同室行走试验 001

{conclusion}

{baseline_note}

## 设备与路线

TX/RX 固定。本次原计划为横穿两板连线中点，用户在录制后说明实际无法穿越：
{manifest.get('actual_route_note', '实际路线尚未补充。')}
因此本轮标记为“单侧接近／远离行走”，不是按原计划验证横穿中点。
原计划仍保留在 manifest 的 setup.route 中，实际说明与用户原话另存 route_note.json。
没有金属物体直接挡在两板之间。
附近桌子有金属角，整次保持原位。板间距离和两板高度未提供，留空。
固件、天线、TX 名义 100 Hz、串口 921600 baud、读取超时 0.1 秒和绘图 100 ms 设置保持不变。
收到用户 READY 后，使用中文语音、大字和提示音；10 秒倒计时后连续执行 30/30/10/30 秒。

## 先检查数据质量

{chr(10).join(table)}

CSV 为 {len(csv_rows)-1} 条数据，表头及每条均为 15 字段，数组为 256 个整数。
CSV 与 raw 完整有效记录逐字段核对一致：{csv_raw_match}。
序号缺口只描述已接收记录的缺口，不能直接认定 Wi-Fi 丢包；跨阶段边界缺口不硬分配给某阶段。
捕获首尾片段单独记录；过渡段不参与三个阶段的变异指标比较。

## 指标与图

预先固定 0 基复数数组索引 8–27、36–55、72–91、100–119，共 80 个，
不是根据本次走动结果筛选。I/Q 顺序与采集器相同，幅度为 sqrt(I²+Q²)，保留固件增益补偿。
各阶段使用完整、不重叠的 1 秒窗。每窗先对每个固定索引计算时间标准差（ddof=1）/均值，
再取 80 个系数的中位数，单位 %。每阶段的可比值是这些 1 秒窗值的中位数。
少于 2 条数据或任意选定索引均值为零的窗口标记缺失，不置零、不换索引、不补帧。
没有拟合检测阈值。

![幅度变异与记录数]({prefix.name}.variability.png)

## 实际阶段时间（Asia/Kuala_Lumpur）

{timing}

CSI、逐块原始读取时间、CSV 写入时间和提示事件均使用同一个 Windows 单调时钟。
用 manifest 中的单调/Unix 时钟锚点换算 UTC 与 +08:00；阶段边界来自实际界面提示事件，
不单靠计划时长推断。每条记录按包含换行符的串口块读取完成时间归段。
这是主机接收时间，不是精确的射频到达时间；人员动作依据提示标记，没有视频独立核实。
读取至 CSV 写入延迟统计见 analysis.json。

## 保存与限制

一次连续采集，含准备倒计时、测量四阶段和极短保存尾段。
原始 CSI CSV、log、raw、read_times、accepted_times、phase_events、quality、records_timed、
variability CSV、PNG/SVG 和分析 JSON 均在本目录，文件名前缀含时间戳。
采集器绘图异常 {stats['plot_exceptions']} 次；关闭后串口打开状态 {stats['serial_open_after_close']}、
线程运行状态 {stats['worker_running_after_close']}。
本次只是一次探索性同室试验；不把数值差异解释成检测准确率，也不推广为穿墙检测结论。
没有烧录、降低采样设置、提交或推送。
'''
    prefix.with_suffix('.report.md').write_text(report,encoding='utf-8')
    print('CONCLUSION',conclusion,flush=True)
    print('REPORT',prefix.with_suffix('.report.md'),flush=True)
    print('PLOT',prefix.with_suffix('.variability.png'),flush=True)
    return result


if __name__=='__main__':
    import sys
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args()
    analyze(args.folder)
