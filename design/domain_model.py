# -*- coding: utf-8 -*-
"""
设备借用管理系统 —— 领域模型与核心用例（设计级原型，当前版本：V1）

目标：
- 用可执行的伪代码表达 V1 业务规则（BR-01 ~ BR-07），特别是
  BR-02 占用唯一性与 BR-04 批准即预留的关键约束；
- 说明状态机是“唯一写入口”：任何设备状态变化必须经过本模块校验并留痕。

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
    approver_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

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

    # -- 用例 1：提交申请（BR-03）--------------------------------------------
    def submit(self, dev_id: str, applicant_id: str, purpose: str,
               expected_return: datetime) -> BorrowRequest:
        dev = self.devices.get(dev_id)
        if dev is None:
            raise RuleViolation("设备不存在")
        req = BorrowRequest("R%04d" % next(self._ids), dev_id, applicant_id,
                            purpose, expected_return)
        self.requests[req.request_id] = req
        self._log_event(req.request_id, "APPLICATION_SUBMITTED", applicant_id)
        if not dev.is_important:                     # 普通设备：快速通道
            self.reserve_for(req, operator="SYSTEM_FAST_LANE")
        return req

    # -- 用例 2：批准申请（BR-02 + BR-04，核心不变量所在）---------------------
    def approve(self, request_id: str, approver_id: str):
        req = self.requests[request_id]
        dev = self.devices[req.device_id]
        if dev.is_important:
            if req.state != "SUBMITTED":
                raise RuleViolation("申请不在待审批状态")
            if req.applicant_id == approver_id:      # （V2 将正式化回避规则）
                raise RuleViolation("不能审批自己的申请")
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
        self._log_event(request_id, "APPLICATION_APPROVED", approver_id)
        return req

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

    # -- 用例 4：超时释放（BR-05，定时任务调用）-------------------------------
    def auto_release_expired(self, now: datetime):
        for req in self.requests.values():
            if req.state == "APPROVED" and now > req.pickup_deadline:
                dev = self.devices[req.device_id]
                if dev.state == "RESERVED":
                    self._transition(dev, "RELEASE", "AUTO_RELEASE",
                                     req.request_id, "SYSTEM")
                req.state = "RELEASED"
                self._log_event(req.request_id, "AUTO_RELEASED", "SYSTEM")


# ---------------------------------------------------------------------------
# 内置自检：覆盖 V1 验证场景 TC-02 / TC-03 / TC-05 / TC-06
# ---------------------------------------------------------------------------
def _selftest():
    lab = Lab()
    lab.devices = {
        "CAM01": Device("CAM01", "CAM"),        # 重要设备
        "SENSOR02": Device("SENSOR02", "SENSOR"),  # 普通设备
    }

    # TC-02：重要设备批准后立即预留
    r1 = lab.submit("CAM01", "U026", "比赛拍摄", datetime(2026, 9, 10))
    lab.approve(r1.request_id, "A03")
    assert lab.devices["CAM01"].state == "RESERVED"

    # TC-03：并发占用唯一性——批准第二笔必须失败
    r2 = lab.submit("CAM01", "U030", "课程作业", datetime(2026, 9, 11))
    try:
        lab.approve(r2.request_id, "A02")
        raise AssertionError("应当批准失败")
    except RuleViolation:
        pass

    # 普通设备快速通道：提交即预留
    r3 = lab.submit("SENSOR02", "U007", "练习", datetime(2026, 9, 8))
    assert lab.devices["SENSOR02"].state == "RESERVED" and r3.state == "APPROVED"

    # 领取 + 异常归还（TC-05）
    lab.pickup(r1.request_id, "A03")
    lab.give_back(r1.request_id, abnormal=True, note="case damaged", operator="A02")
    assert lab.devices["CAM01"].state == "MAINTENANCE"

    # TC-06：超时释放
    lab.auto_release_expired(datetime.now() + timedelta(hours=49))
    assert lab.requests[r3.request_id].state == "RELEASED"

    print("V1 领域模型自检通过：TC-02 / TC-03 / 快速通道 / TC-05 / TC-06 全部符合预期")


if __name__ == "__main__":
    _selftest()
