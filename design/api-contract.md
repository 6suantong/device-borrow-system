# API 契约（设计文档）

> 当前版本：V2。随迭代演进，变更在文末“版本变更记录”标注。
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
| POST | `/api/applications` | 提交申请。重要设备进入待审批；普通设备立即预留（快速通道）。弱网重复提交10分钟窗口内返回原申请号（BR-08） | 201 |
| POST | `/api/applications/{request_id}/withdraw` | 撤回（仅领取前；已预留设备同步释放） | 200 |

POST /api/applications 请求体：
```json
{
  "device_id": "CAM01",
  "purpose": "比赛拍摄",
  "priority": "CONTEST",
  "co_users": ["U008", "U009"],
  "start_time": "2026-09-10T09:00:00",
  "expected_return": "2026-09-12T18:00:00"
}
```

## 3. 审批与借还（管理员）

| 方法 | 路径 | 说明 | 成功 |
|------|------|------|------|
| GET | `/api/admin/applications?status=PENDING&page=1&size=20` | 待办列表（V3：分页+索引，P95<800ms） | 200 |
| GET | `/api/admin/applications/{request_id}/approval-records` | 审批责任记录（谁批准/拒绝、为什么） | 200 |
| POST | `/api/admin/applications/{request_id}/approve` | 批准（批准即预留，写入审批记录与领取时限） | 200 |
| POST | `/api/admin/applications/{request_id}/reject` | 拒绝，须选原因代码+说明，对申请人可见（BR-10） | 200 |
| POST | `/api/admin/requests/{request_id}/pickup` | 领取确认 | 200 |
| POST | `/api/admin/requests/{request_id}/return` | 归还；`{"abnormal": true, "note": "..."}` | 200 |
| POST | `/api/admin/devices/{device_id}/repair-done` | 维修完成确认（V3 IMP-2，须填检修说明） | 200 |
| POST | `/api/admin/devices/{device_id}/correct-state` | 受控状态修正（V3：必填原因、留痕、双人可见） | 200 |

## 4. 关键错误码

| HTTP | code | 场景 |
|------|------|------|
| 409 | DEVICE_UNAVAILABLE | 批准/预留时设备已非可借（BR-02） |
| 422 | INVALID_STATE_TRANSITION | 违反状态机（BR-01） |
| 403 | SELF_APPROVAL_FORBIDDEN | 审批回避（BR-09） |
| 200 | （幂等合并） | 重复提交10分钟窗口内返回原申请号（BR-08） |
| 422 | REJECT_REASON_REQUIRED | 拒绝缺少结构化原因（BR-10） |

## 5. 内部任务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /internal/jobs/overdue-scan | 超期扫描（V3：每小时；失败重试3次+告警） |
| POST | /internal/jobs/release-expired | 超时未领取释放（V3：每小时） |

## 版本变更记录
- V1：初始契约——设备查询、申请提交/撤回、审批与借还、内部任务。
- V2：申请体增加 priority/co_users；提交幂等；审批记录查询端点；拒绝
  强制结构化原因；审批列表按优先级排序。
- V3：管理列表分页；维修完成与受控状态修正端点；定时任务每小时调度+失败
  告警语义；504 后前端引导查询而非重填（幂等键 Idempotency-Key）。
