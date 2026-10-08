# API 契约（设计文档）

> 当前版本：V1。随迭代演进，变更在文末“版本变更记录”标注。
> 约定：`Content-Type: application/json`；时间统一 ISO8601；错误响应统一
> `{"error": {"code": "...", "message": "..."}}`。

## 1. 设备（成员/管理员）

| 方法 | 路径 | 说明 | 成功 |
|------|------|------|------|
| GET | `/api/devices` | 设备列表，`?state=AVAILABLE` 可过滤 | 200 |
| GET | `/api/devices/{device_id}` | 设备详情（含最近状态变化） | 200 |

## 2. 申请（成员）

| 方法 | 路径 | 说明 | 成功 |
|------|------|------|------|
| GET | `/api/applications` | 我的申请（含状态时间线） | 200 |
| GET | `/api/applications/{request_id}` | 申请详情 | 200 |
| POST | `/api/applications` | 提交申请。重要设备进入待审批；普通设备立即预留（快速通道） | 201 |
| POST | `/api/applications/{request_id}/withdraw` | 撤回（仅领取前；已预留设备同步释放） | 200 |

POST /api/applications 请求体：
```json
{
  "device_id": "CAM01",
  "purpose": "比赛拍摄",
  "start_time": "2026-09-10T09:00:00",
  "expected_return": "2026-09-12T18:00:00"
}
```

## 3. 审批与借还（管理员）

| 方法 | 路径 | 说明 | 成功 |
|------|------|------|------|
| GET | `/api/admin/applications?status=PENDING` | 待办列表 | 200 |
| POST | `/api/admin/applications/{request_id}/approve` | 批准（批准即预留） | 200 |
| POST | `/api/admin/applications/{request_id}/reject` | 拒绝，须填 `reason` | 200 |
| POST | `/api/admin/requests/{request_id}/pickup` | 领取确认 | 200 |
| POST | `/api/admin/requests/{request_id}/return` | 归还；`{"abnormal": true, "note": "..."}` | 200 |
| POST | `/api/admin/devices/{device_id}/repair-done` | 维修完成确认 | 200 |

## 4. 关键错误码

| HTTP | code | 场景 |
|------|------|------|
| 409 | DEVICE_UNAVAILABLE | 批准/预留时设备已非可借（BR-02） |
| 422 | INVALID_STATE_TRANSITION | 违反状态机（BR-01） |
| 403 | SELF_APPROVAL_FORBIDDEN | 审批回避（后续版本启用） |
| 200 | （幂等合并） | 重复提交返回原申请号（后续版本启用） |

## 5. 内部任务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /internal/jobs/overdue-scan | 超期扫描（定时） |
| POST | /internal/jobs/release-expired | 超时未领取释放（定时） |

## 版本变更记录
- V1：初始契约——设备查询、申请提交/撤回、审批与借还、内部任务。
