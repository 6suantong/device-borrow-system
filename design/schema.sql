-- =============================================================================
-- 设备借用管理系统 数据库设计（Schema）
-- 当前版本：V1 —— 从需求到工程意图（最小可运行系统方案）
-- 对应业务规则：BR-01 状态机 / BR-02 占用唯一性 / BR-03 分类流程 /
--              BR-04 批准即预留 / BR-05 领取与超时释放 / BR-06 归还检验 /
--              BR-07 全程留痕
-- 说明：本文件随四轮迭代演进，每次变更在下方追加“版本变更记录”。
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. 用户与设备主数据
-- ---------------------------------------------------------------------------
CREATE TABLE user (
    user_id      TEXT PRIMARY KEY,              -- 学号/工号，如 U001、A01、L01
    name         TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('MEMBER','ADMIN','LEADER')),
    contact      TEXT
);

CREATE TABLE device (
    device_id    TEXT PRIMARY KEY,              -- 如 CAM01、BOARD07、SENSOR02
    name         TEXT NOT NULL,
    category     TEXT NOT NULL CHECK (category IN ('CAM','BOARD','SENSOR','TOOL')),
    is_important INTEGER NOT NULL DEFAULT 0,    -- BR-03：重要设备=1（CAM/BOARD）
    state        TEXT NOT NULL DEFAULT 'AVAILABLE'
                 CHECK (state IN ('AVAILABLE','RESERVED','BORROWED','MAINTENANCE')),
    location     TEXT
);

-- ---------------------------------------------------------------------------
-- 2. 借用申请（业务主线单据）
-- ---------------------------------------------------------------------------
CREATE TABLE borrow_request (
    request_id       TEXT PRIMARY KEY,          -- R0001...
    device_id        TEXT NOT NULL REFERENCES device(device_id),
    applicant_id     TEXT NOT NULL REFERENCES user(user_id),
    purpose          TEXT NOT NULL,             -- 用途说明
    start_time       TEXT NOT NULL,             -- ISO8601
    expected_return  TEXT NOT NULL,             -- 预计归还时间（BR-07 超期判定依据）
    state            TEXT NOT NULL DEFAULT 'SUBMITTED'
                     CHECK (state IN ('SUBMITTED','UNDER_REVIEW','APPROVED','PICKED_UP',
                                      'RETURNED','REJECTED','WITHDRAWN','RELEASED')),
    is_overdue       INTEGER NOT NULL DEFAULT 0,-- BR-07 超期标记
    approver_id      TEXT REFERENCES user(user_id),
    reject_reason    TEXT,                      -- 拒绝时填写（V1 为自由文本）
    created_at       TEXT NOT NULL,
    decided_at       TEXT,
    picked_up_at     TEXT,
    returned_at      TEXT
);

-- ---------------------------------------------------------------------------
-- 3. 双日志：状态变更留痕 + 业务事件留痕（BR-07）
-- ---------------------------------------------------------------------------
CREATE TABLE state_change_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL REFERENCES device(device_id),
    old_state    TEXT NOT NULL,
    new_state    TEXT NOT NULL,
    source       TEXT NOT NULL,                 -- APPLICATION_APPROVED / PICKUP_CONFIRMED / RETURN_FORM / AUTO_RELEASE / ADMIN_CORRECTION
    request_id   TEXT REFERENCES borrow_request(request_id),
    operator_id  TEXT,                          -- 管理员或 SYSTEM
    note         TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE event_log (
    event_id     TEXT PRIMARY KEY,              -- E00001...
    request_id   TEXT REFERENCES borrow_request(request_id),
    action       TEXT NOT NULL,                 -- APPLICATION_SUBMITTED / REVIEW_STARTED / APPLICATION_APPROVED ...
    actor_id     TEXT,                          -- 操作人，SYSTEM 表示定时任务
    result       TEXT NOT NULL DEFAULT 'OK',    -- OK / FAIL
    detail       TEXT,
    created_at   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 4. 通知表（V1 仅预留结构，提醒能力后续版本启用）
-- ---------------------------------------------------------------------------
CREATE TABLE notification (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES user(user_id),
    type            TEXT NOT NULL,              -- PICKUP_REMINDER / OVERDUE / RESULT ...
    payload         TEXT,
    sent_at         TEXT,
    read_at         TEXT
);

-- =============================================================================
-- 版本变更记录
-- V1：初始建表（user/device/borrow_request/state_change_log/event_log/notification 预留）
-- =============================================================================
