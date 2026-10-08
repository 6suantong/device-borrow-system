# -*- coding: utf-8 -*-
"""
V3 运行日志分析脚本：从原始运行证据建立问题证据链。

用法：
    python v3_log_analysis.py <V3_运行日志材料包目录>

输入（GBK 编码 CSV + UTF-8 访问日志）：
    V3_业务事件日志.csv   申请/审批/领取/归还/超期等业务事件
    V3_设备状态日志.csv   设备状态变化（来源/关联申请/操作人）
    V3_系统访问日志.log   API 访问、响应状态与耗时
    V3_用户反馈.csv       成员/管理员/负责人反馈原话

输出：事件与状态转换分布、失败明细、异常归还暴露窗口、超期任务执行记录、
接口耗时分位等统计，用于报告 3.1 证据表与 3.3 指标基线。
"""
import csv
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime

EVENT_COLS = ['timestamp', 'event_id', 'request_id', 'user_id', 'actor_role',
              'actor_id', 'action', 'device_id', 'result', 'detail']
STATE_COLS = ['timestamp', 'device_id', 'old_state', 'new_state', 'source',
              'request_id', 'operator_id', 'note']
ACCESS_RE = re.compile(
    r'^(\S+) (\S+) (\S+) (\S+) (\S+) (\d+) (\d+)ms trace=(\S+)')


def read_csv_gbk(path):
    with open(path, encoding='gb18030', errors='replace') as f:
        rows = list(csv.reader(f))
    return [dict(zip(EVENT_COLS if 'action' in rows[0] else STATE_COLS, r))
            for r in rows[1:]]


def main(base):
    events = [dict(e, dt=datetime.fromisoformat(e['timestamp']))
              for e in read_csv_gbk(f"{base}\\V3_业务事件日志.csv")]
    states = read_csv_gbk(f"{base}\\V3_设备状态日志.csv")

    print("== 规模 ==")
    reqs = defaultdict(dict)
    for e in events:
        reqs[e['request_id']][e['action']] = e
    print("事件 %d 条 / 状态转换 %d 条 / 申请 %d 份 / 设备 %d 台" % (
        len(events), len(states), len(reqs),
        len(set(e['device_id'] for e in events))))

    print("\n== action 分布 ==")
    for a, c in Counter(e['action'] for e in events).most_common():
        print("  %-40s %d" % (a, c))

    print("\n== EV-01 批准失败（占用冲突）==")
    fails = [e for e in events if e['result'] == 'FAIL']
    approved = Counter(e['action'] for e in events)['APPLICATION_APPROVED']
    print("APPROVAL_FAILED_DEVICE_UNAVAILABLE=%d / 批准尝试=%d → 冲突率 %.0f%%"
          % (len(fails), len(fails) + approved,
             100 * len(fails) / (len(fails) + approved)))
    manual_sync = [s for s in states if s['source'] == 'MANUAL_SYNC']
    print("MANUAL_SYNC 人工同步=%d 条（与失败次数互证）" % len(manual_sync))

    print("\n== EV-02 异常归还暴露窗口 ==")
    for s in states:
        if s['source'] == 'RETURN_FORM' and 'abnormal' in s['note']:
            for s2 in states:
                if (s2['device_id'] == s['device_id']
                        and s2['source'] == 'ADMIN_CORRECTION'
                        and s2['timestamp'] > s['timestamp']):
                    h = (datetime.fromisoformat(s2['timestamp'])
                         - datetime.fromisoformat(s['timestamp'])).total_seconds() / 3600
                    print("  %s %s 暴露 %.1f 小时" % (s['request_id'], s['device_id'], h))
                    break

    print("\n== EV-04 批准后滞留 ==")
    n = 0
    for rid, acts in reqs.items():
        if ('APPLICATION_APPROVED' in acts
                and not {'PICKUP_CONFIRMED', 'APPLICATION_WITHDRAWN',
                         'APPLICATION_REJECTED'} & set(acts)):
            n += 1
            print("  %s dev=%s 批准@%s" % (rid, acts['APPLICATION_APPROVED']['device_id'],
                                           acts['APPLICATION_APPROVED']['timestamp'][:19]))
    print("  滞留申请数:", n)

    print("\n== EV-03/EV-05/EV-06 访问日志 ==")
    acc = []
    with open(f"{base}\\V3_系统访问日志.log", encoding='utf-8', errors='replace') as f:
        for line in f:
            m = ACCESS_RE.match(line.strip())
            if m:
                acc.append(dict(ts=m.group(1), user=m.group(3),
                                path=m.group(5), status=int(m.group(6)),
                                ms=int(m.group(7))))
    print("请求 %d 条；状态码分布 %s" % (len(acc), dict(Counter(a['status'] for a in acc))))
    submit = [a for a in acc if a['path'] == '/api/applications' and a['status'] >= 400]
    print("提交接口失败 %d 次（504 超时）" % len(submit))
    by_path = defaultdict(list)
    for a in acc:
        by_path[a['path'].split('?')[0]].append(a['ms'])
    for p, ms in sorted(by_path.items(), key=lambda kv: -statistics.median(kv[1]))[:5]:
        print("  %-35s n=%3d 中位=%5.0fms 最大=%5dms"
              % (p, len(ms), statistics.median(ms), max(ms)))
    print("\noverdue-scan 执行记录：")
    for a in acc:
        if 'overdue-scan' in a['path']:
            flag = '  <<<< 失败' if a['status'] != 200 else ''
            print("  %s %d %dms%s" % (a['ts'], a['status'], a['ms'], flag))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
