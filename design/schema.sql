-- =============================================================================
-- 设备借用管理系统 数据库设计（Schema）
-- 当前版本：V4 —— 部署运维与优化（最终版本）
-- V4 增补：WAL 模式与备份策略（deploy/）、每日对账（deploy/reconcile.py）、
--         版本化迁移与发布/回退条件（deploy/deploy.md）
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
    priority         TEXT NOT NULL DEFAULT 'PRACTICE'
                     CHECK (priority IN ('CONTEST','COURSE','PRACTICE')), -- V2 BR-03
    pickup_deadline  TEXT,                      -- V2 BR-05：批准时写入 = decided_at + 48h
    withdrawn_at     TEXT,                      -- V2：撤回时间
    reject_reason_code TEXT CHECK (reject_reason_code IN
                     ('SLOT_CONFLICT','DEVICE_STATE','ELIGIBILITY','OTHER')), -- V2 BR-10
    reject_note      TEXT,
    is_overdue       INTEGER NOT NULL DEFAULT 0,-- BR-07 超期标记
    approver_id      TEXT REFERENCES user(user_id),
    reject_reason    TEXT,                      -- 拒绝补充说明（V1 为自由文本）
    created_at       TEXT NOT NULL,
    decided_at       TEXT,
    picked_up_at     TEXT,
    returned_at      TEXT
);

-- V2 BR-11：申请 ↔ 实际使用人（小组共用场景）
CREATE TABLE request_co_user (
    request_id   TEXT NOT NULL REFERENCES borrow_request(request_id),
    user_id      TEXT NOT NULL REFERENCES user(user_id),
    PRIMARY KEY (request_id, user_id)
);

-- V2：审批责任记录（谁批准/拒绝、为什么）——材料A“说清是谁作出的决定”
CREATE TABLE approval_record (
    approval_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   TEXT NOT NULL REFERENCES borrow_request(request_id),
    approver_id  TEXT NOT NULL REFERENCES user(user_id),
    action       TEXT NOT NULL CHECK (action IN ('APPROVE','REJECT')),
    reason_code  TEXT,
    reason       TEXT,
    created_at   TEXT NOT NULL
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

-- notification 表 V2 启用：领取提醒（T-24h）/ 超时释放 / 审批结果通知
-- V3 IMP-3：超期三级通知（前24h/超期时/超期后每日）+ 任务失败告警
CREATE TABLE notification (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES user(user_id),
    type            TEXT NOT NULL,              -- PICKUP_REMINDER / OVERDUE / RESULT ...
    payload         TEXT,
    sent_at         TEXT,
    read_at         TEXT
);

-- =============================================================================
-- V3 IMP-6：管理端列表性能优化（V3 运行数据：P95 2428ms → 目标 <800ms）
-- 状态部分索引：待办列表只扫 PENDING，状态查询走覆盖索引
-- =============================================================================
CREATE INDEX idx_request_state_created ON borrow_request(state, created_at);
CREATE INDEX idx_request_device ON borrow_request(device_id);
CREATE INDEX idx_state_log_device_time ON state_change_log(device_id, created_at);
CREATE INDEX idx_event_request ON event_log(request_id);
CREATE INDEX idx_notification_unread ON notification(user_id, read_at);

-- =============================================================================
-- 版本变更记录
-- V1：初始建表（user/device/borrow_request/state_change_log/event_log/notification 预留）
-- V2：borrow_request 增加 priority/pickup_deadline/withdrawn_at/reject_reason_code/
--     reject_note；新增 request_co_user（使用人）与 approval_record（审批责任）；
--     notification 启用；BR-06 异常归还与状态转换强制同事务（应用层约束）
-- V3：新增 5 个查询索引（IMP-6 列表性能）；应用层改为条件更新实现占用原子性
--     （IMP-1）；归还事务内强制校验（IMP-2）；新增“维修完成”受控转换（IMP-2）；
--     定时任务调度 1次/天→1次/小时，失败重试3次+告警（IMP-3）
-- V4：启用 WAL 模式与每日在线备份（deploy/docker-compose.yml）；新增每日
--     对账脚本 deploy/reconcile.py（状态一致性观测）；发布采用版本化迁移
--     与镜像 tag 回退机制（deploy/deploy.md）
-- =============================================================================
