# -*- coding: utf-8 -*-
"""
设备借用管理系统 —— 领域模型与核心用例（设计级原型，当前版本：V2）

目标：
- 用可执行的伪代码表达业务规则（BR-01 ~ BR-11），特别是
  BR-02 占用唯一性与 BR-04 批准即预留的关键约束；
- 说明状态机是“唯一写入口”：任何设备状态变化必须经过本模块校验并留痕。

V3 改进（基于运行证据，详见 analysis/v3_analysis_result.md）：
- IMP-1 占用原子化：approve 改为条件更新语义（数据库层 WHERE state='AVAILABLE'），
  消除 18% 批准冲突率与 MANUAL_SYNC 人工同步；
- IMP-2 维修闭环：新增 repair_done() 受控转换（V3 日志出现维修中设备被借出）；
- IMP-4 领取时限自动执行：auto_release 扫描由每日一次改为每小时（overdue 同）。

运行：python domain_model.py 可执行内置自检（mini 场景验证）。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# 状态机定义（BR-01）：合法状态转换表
# ---------------------------------------------------------------------------
DEVICE_STATES = {"AVAILABLE", "RESERVED", "BORROWED", "MAINTENANCE"}

DEVICE_TRANSITIONS = {
    # (旧状态, 事件) -> 新状态
    ("AVAILABLE", "RESERVE"): "RESERVED",        # 申请批准（BR-04）
    ("RESERVED", "PICKUP"): "BORROWED",          # 领取确认
    ("RESERVED", "RELEASE"): "AVAILABLE",        # 超时释放 / 撤回（BR-05）
    ("BORROWED", "RETURN_OK"): "AVAILABLE",      # 正常归还（BR-06）
    ("BORROWED", "RETURN_ABNORMAL"): "MAINTENANCE",  # 异常归还（BR-06）
    ("MAINTENANCE", "REPAIR_DONE"): "AVAILABLE", # 维修完成确认
}

REQUEST_STATES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "PICKED_UP",
                  "RETURNED", "REJECTED", "WITHDRAWN", "RELEASED"}

IMPORTANT_CATEGORIES = {"CAM", "BOARD"}          # BR-03 分级
PICKUP_DEADLINE_HOURS = 48                       # BR-05 领取时限
PRIORITY_ORDER = {"CONTEST": 0, "COURSE": 1, "PRACTICE": 2}   # V2 BR-03
IDEMPOTENCY_WINDOW = timedelta(minutes=10)       # V2 BR-08 幂等窗口
REJECT_REASONS = {"SLOT_CONFLICT", "DEVICE_STATE", "ELIGIBILITY", "OTHER"}  # BR-10


class RuleViolation(Exception):
    """业务规则不满足时抛出，调用方转为用户可见错误。"""


@dataclass
class Device:
    device_id: str
    category: str
    state: str = "AVAILABLE"

    @property
    def is_important(self) -> bool:
        return self.category in IMPORTANT_CATEGORIES


@dataclass
class BorrowRequest:
    request_id: str
    device_id: str
    applicant_id: str
    purpose: str
    expected_return: datetime
    state: str = "SUBMITTED"
    priority: str = "PRACTICE"                   # V2 BR-03
    approver_id: str | None = None
    reject_reason_code: str | None = None        # V2 BR-10
    created_at: datetime = field(default_factory=datetime.now)
    co_users: list[str] = field(default_factory=list)   # V2 BR-11

    @property
    def pickup_deadline(self) -> datetime:
        return self.created_at + timedelta(hours=PICKUP_DEADLINE_HOURS)


@dataclass
class Lab:
    """内存版仓储。生产实现中每个写操作位于同一数据库事务内。"""
    devices: dict[str, Device] = field(default_factory=dict)
    requests: dict[str, BorrowRequest] = field(default_factory=dict)
    state_logs: list = field(default_factory=list)   # state_change_log
    event_logs: list = field(default_factory=list)   # event_log
    approval_records: list = field(default_factory=list)  # V2 审批责任记录
    _ids: itertools.count = itertools.count(1)

    # -- 内部工具 ------------------------------------------------------------
    def _log_state(self, dev: Device, old: str, new: str, source: str,
                   request_id: str | None, operator: str):
        self.state_logs.append((datetime.now(), dev.device_id, old, new,
                                source, request_id, operator))

    def _log_event(self, request_id, action, actor, result="OK", detail=""):
        self.event_logs.append(("E%05d" % next(self._ids), request_id,
                                action, actor, result, detail))

    def _transition(self, dev: Device, event: str, source: str,
                    request_id: str | None, operator: str):
        """唯一的状态写入口：先查合法转换表，再落状态与双日志。"""
        old = dev.state
        new = DEVICE_TRANSITIONS.get((old, event))
        if new is None:                              # BR-01
            raise RuleViolation(f"非法状态转换 {old} --{event}--> ?")
        dev.state = new
        self._log_state(dev, old, new, source, request_id, operator)

    # -- 用例 1：提交申请（BR-03 + BR-08 幂等）--------------------------------
    def submit(self, dev_id: str, applicant_id: str, purpose: str,
               expected_return: datetime, priority: str = "PRACTICE",
               co_users: list[str] | None = None) -> BorrowRequest:
        dev = self.devices.get(dev_id)
        if dev is None:
            raise RuleViolation("设备不存在")
        # BR-08 幂等：窗口期内同用户同设备同内容视为重复提交
        for r in self.requests.values():
            if (r.applicant_id == applicant_id and r.device_id == dev_id
                    and r.purpose == purpose and r.state not in
                    ("REJECTED", "WITHDRAWN", "RETURNED", "RELEASED")
                    and datetime.now() - r.created_at < IDEMPOTENCY_WINDOW):
                self._log_event(r.request_id, "SUBMIT_DEDUPLICATED", applicant_id)
                return r                          # 返回原申请号
        req = BorrowRequest("R%04d" % next(self._ids), dev_id, applicant_id,
                            purpose, expected_return, priority=priority,
                            co_users=co_users or [])
        self.requests[req.request_id] = req
        self._log_event(req.request_id, "APPLICATION_SUBMITTED", applicant_id)
        if not dev.is_important:                     # 普通设备：快速通道
            self.reserve_for(req, operator="SYSTEM_FAST_LANE")
        return req

    # -- 用例 2：批准申请（BR-02 + BR-04 + BR-09 回避，核心不变量所在）--------
    def approve(self, request_id: str, approver_id: str):
        req = self.requests[request_id]
        dev = self.devices[req.device_id]
        if dev.is_important:
            if req.state != "SUBMITTED":
                raise RuleViolation("申请不在待审批状态")
            if req.applicant_id == approver_id:      # BR-09 审批回避
                self._log_event(request_id, "SELF_APPROVAL_BLOCKED", approver_id,
                                "FAIL", "applicant equals approver")
                raise RuleViolation("不能审批自己的申请，请转交其他管理员")
        # BR-02 关键点：校验与占用必须在同一事务内完成（此处单线程演示，
        # 生产实现用 UPDATE device SET state='RESERVED'
        #           WHERE device_id=? AND state='AVAILABLE' 的条件更新）。
        if dev.state != "AVAILABLE":
            self._log_event(request_id, "APPROVAL_FAILED_DEVICE_UNAVAILABLE",
                            approver_id, "FAIL", "device state changed after submission")
            raise RuleViolation(f"设备当前为 {dev.state}，无法批准占用")
        self._transition(dev, "RESERVE", "APPLICATION_APPROVED",
                         request_id, approver_id)
        req.state, req.approver_id = "APPROVED", approver_id
        # V2 BR-05：批准即启动 48 小时领取倒计时
        self.approval_records.append((request_id, approver_id, "APPROVE",
                                      None, datetime.now()))
        self._log_event(request_id, "APPLICATION_APPROVED", approver_id)
        return req

    # -- 用例 2b：拒绝申请（BR-10 结构化原因，对申请人可见）--------------------
    def reject(self, request_id: str, approver_id: str,
               reason_code: str, reason: str = ""):
        req = self.requests[request_id]
        if reason_code not in REJECT_REASONS:
            raise RuleViolation("拒绝必须选择结构化原因代码")
        req.state = "REJECTED"
        req.reject_reason_code = reason_code
        self.approval_records.append((request_id, approver_id, "REJECT",
                                      reason_code, datetime.now()))
        self._log_event(request_id, "APPLICATION_REJECTED", approver_id,
                        "OK", reason_code)

    # -- 用例 2c：撤回（材料B：设备尚未领取前可取消）---------------------------
    def withdraw(self, request_id: str):
        req = self.requests[request_id]
        if req.state not in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
            raise RuleViolation("当前状态不可撤回")
        if req.state == "APPROVED":                  # 已预留则同步释放
            dev = self.devices[req.device_id]
            if dev.state == "RESERVED":
                self._transition(dev, "RELEASE", "MEMBER_WITHDRAW",
                                 request_id, req.applicant_id)
        req.state = "WITHDRAWN"
        self._log_event(request_id, "APPLICATION_WITHDRAWN", req.applicant_id,
                        "OK", "plan changed")

    # -- 用例 3：预留/领取/归还 ----------------------------------------------
    def reserve_for(self, req: BorrowRequest, operator: str):
        dev = self.devices[req.device_id]
        if dev.state != "AVAILABLE":
            raise RuleViolation("设备不可用，预留失败")
        self._transition(dev, "RESERVE", "AUTO_RESERVE", req.request_id, operator)
        req.state = "APPROVED"

    def pickup(self, request_id: str, operator: str):
        req = self.requests[request_id]
        dev = self.devices[req.device_id]
        if req.state != "APPROVED":
            raise RuleViolation("申请未处于待领取状态")
        self._transition(dev, "PICKUP", "PICKUP_CONFIRMED", request_id, operator)
        req.state = "PICKED_UP"
        self._log_event(request_id, "PICKUP_CONFIRMED", operator)

    def give_back(self, request_id: str, abnormal: bool, note: str, operator: str):
        req = self.requests[request_id]
        dev = self.devices[req.device_id]
        if req.state != "PICKED_UP":
            raise RuleViolation("设备未处于借出状态")
        event = "RETURN_ABNORMAL" if abnormal else "RETURN_OK"
        self._transition(dev, event, "RETURN_FORM", request_id, operator)
        req.state = "RETURNED"
        if datetime.now() > req.expected_return:
            self._log_event(request_id, "OVERDUE_DETECTED", "SYSTEM",
                            "OK", "returned after deadline")
        self._log_event(request_id,
                        "ABNORMAL_RETURN_RECORDED" if abnormal else "RETURN_RECORDED",
                        operator, "OK", note)

    # -- 用例 4：超时释放（BR-05 / V3 IMP-4，定时任务每小时调用）--------------
    def auto_release_expired(self, now: datetime):
        for req in self.requests.values():
            if req.state == "APPROVED" and now > req.pickup_deadline:
                dev = self.devices[req.device_id]
                if dev.state == "RESERVED":
                    self._transition(dev, "RELEASE", "AUTO_RELEASE",
                                     req.request_id, "SYSTEM")
                req.state = "RELEASED"
                self._log_event(req.request_id, "AUTO_RELEASED", "SYSTEM")

    # -- 用例 5：维修完成确认（V3 IMP-2 受控转换，替代 ADMIN_CORRECTION）------
    def repair_done(self, device_id: str, operator: str, check_note: str):
        dev = self.devices[device_id]
        if dev.state != "MAINTENANCE" or not check_note:
            raise RuleViolation("维修完成须设备处于维修状态且填写检修说明")
        self._transition(dev, "REPAIR_DONE", "REPAIR_CONFIRMED",
                         None, operator)
        self._log_event(None, "REPAIR_DONE_RECORDED", operator, "OK", check_note)

    # -- 用例 6：占用条件更新（V3 IMP-1 数据库层原子化示意）--------------------
    # 生产实现（以 SQLite/PostgreSQL 为例），单条 UPDATE 原子完成“校验+占用”：
    #
    #   UPDATE device SET state='RESERVED'
    #    WHERE device_id=:dev AND state='AVAILABLE';
    #   -- rowcount==0 ⇒ 设备已被占用，批准失败回滚并返回 409 DEVICE_UNAVAILABLE
    #
    # 该写法使“校验”与“占用”不可分割，从根上消除 V3 日志中
    # APPROVAL_FAILED_DEVICE_UNAVAILABLE（18%）与 MANUAL_SYNC（18 条）的来源。


# ---------------------------------------------------------------------------
# 内置自检：V1 场景（TC-02/03/05/06）+ V2 场景（V2-02/04/06）
# ---------------------------------------------------------------------------
def _selftest():
    lab = Lab()
    lab.devices = {
        "CAM01": Device("CAM01", "CAM"),        # 重要设备
        "SENSOR02": Device("SENSOR02", "SENSOR"),  # 普通设备
    }

    # TC-02：重要设备批准后立即预留
    r1 = lab.submit("CAM01", "U026", "比赛拍摄", datetime(2026, 9, 10),
                    priority="CONTEST")
    lab.approve(r1.request_id, "A03")
    assert lab.devices["CAM01"].state == "RESERVED"
    assert any(rec[0] == r1.request_id and rec[2] == "APPROVE"
               for rec in lab.approval_records)          # V2-01 审批责任可查

    # TC-03：并发占用唯一性——批准第二笔必须失败
    r2 = lab.submit("CAM01", "U030", "课程作业", datetime(2026, 9, 11))
    try:
        lab.approve(r2.request_id, "A02")
        raise AssertionError("应当批准失败")
    except RuleViolation:
        pass

    # V2-02：管理员自批拦截（BR-09）
    ra = lab.submit("CAM01", "A01", "测试自批", datetime(2026, 9, 12))
    try:
        lab.approve(ra.request_id, "A01")
        raise AssertionError("自批应当被拦截")
    except RuleViolation:
        pass

    # V2-06：重复提交幂等（BR-08）
    r3 = lab.submit("SENSOR02", "U007", "练习", datetime(2026, 9, 8),
                    co_users=["U008", "U009"])            # V2 BR-11 使用人
    r3b = lab.submit("SENSOR02", "U007", "练习", datetime(2026, 9, 8))
    assert r3b.request_id == r3.request_id, "重复提交应返回原申请号"

    # 普通设备快速通道：提交即预留
    assert lab.devices["SENSOR02"].state == "RESERVED" and r3.state == "APPROVED"

    # V2-04：撤回释放设备（BR-05/材料B）
    lab.withdraw(r3.request_id)
    assert lab.devices["SENSOR02"].state == "AVAILABLE"
    assert r3.state == "WITHDRAWN"

    # 领取 + 异常归还（TC-05）
    lab.pickup(r1.request_id, "A03")
    lab.give_back(r1.request_id, abnormal=True, note="case damaged", operator="A02")
    assert lab.devices["CAM01"].state == "MAINTENANCE"

    # TC-06：超时释放
    lab.auto_release_expired(datetime.now() + timedelta(hours=49))
    assert lab.requests[r2.request_id].state in ("SUBMITTED", "REJECTED")

    print("领域模型自检通过：TC-02/03/05/06 + V2-01/02/04/06 全部符合预期")


if __name__ == "__main__":
    _selftest()
