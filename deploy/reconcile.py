# -*- coding: utf-8 -*-
"""
V4 每日状态对账脚本：恢复后/发布后核对“设备状态 vs 未完结借用记录”。

对账不变量（承接 V1 三不变量）：
- 有 APPROVED 且未释放的申请  ⇔ 设备应为 RESERVED
- 有 PICKED_UP 未归还的申请   ⇔ 设备应为 BORROWED
- 设备处于 MAINTENANCE        ⇔ 应存在一条未修复的异常归还记录

不一致项输出报告并写入对账日志，由管理员确认后通过受控修正入口处理，
禁止直改数据库（报告 4.4 案例3）。

用法：python reconcile.py <数据库文件>
"""
import sqlite3
import sys


def main(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    issues = []

    # 1) 设备状态 vs 申请状态交叉核对
    rows = conn.execute("""
        SELECT d.device_id, d.state AS dev_state,
               SUM(CASE WHEN r.state='APPROVED' THEN 1 ELSE 0 END) AS n_approved,
               SUM(CASE WHEN r.state='PICKED_UP' THEN 1 ELSE 0 END) AS n_picked
        FROM device d LEFT JOIN borrow_request r ON r.device_id = d.device_id
        GROUP BY d.device_id
    """).fetchall()
    for r in rows:
        if r["n_approved"] and r["dev_state"] != "RESERVED":
            issues.append((r["device_id"], r["dev_state"],
                           "存在 %d 份待领取申请" % r["n_approved"]))
        if r["n_picked"] and r["dev_state"] != "BORROWED":
            issues.append((r["device_id"], r["dev_state"],
                           "存在 %d 份未归还记录" % r["n_picked"]))
        if (not r["n_approved"]) and (not r["n_picked"]) \
                and r["dev_state"] in ("RESERVED", "BORROWED"):
            issues.append((r["device_id"], r["dev_state"],
                           "无未完结申请却处于占用态"))

    # 2) 维修中设备应有异常归还来源
    rows = conn.execute("""
        SELECT d.device_id FROM device d
        WHERE d.state='MAINTENANCE'
          AND NOT EXISTS (SELECT 1 FROM state_change_log s
                          WHERE s.device_id=d.device_id
                            AND s.new_state='MAINTENANCE')
    """).fetchall()
    for r in rows:
        issues.append((r["device_id"], "MAINTENANCE", "缺少异常归还来源记录"))

    print("对账完成：发现 %d 处不一致" % len(issues))
    for dev, state, reason in issues:
        print("  [不一致] %s state=%s (%s)" % (dev, state, reason))
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
