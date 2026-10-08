# 版本变更日志（CHANGELOG）

四轮迭代均在上一版基础上做增量演化。格式：`[版本] 变更摘要`。

## V1 —— 从需求到工程意图
- 确立核心不变量：占用唯一性（一台设备任一时刻至多一个有效占用）、
  设备状态与借用记录一致、全程留痕。
- 业务规则 BR-01 ~ BR-07：四态状态机、占用唯一性、两级分类流程
  （重要设备审批 / 普通设备快速通道）、批准即预留、48h 超时释放、
  异常归还强制入维修、全程留痕。
- 数据模型：user / device / borrow_request / state_change_log / event_log，
  notification 表预留。
- 领域模型 `design/domain_model.py`：状态机唯一写入口 + 六个核心用例 +
  内置自检（TC-02/03/05/06）。
- API 契约 `design/api-contract.md` 初版。
- 报告完成 V1 章节（1.1-1.8）。

## V2 —— 需求扩展与复杂规则
- 变更识别与影响分析：对材料A-D的诉求区分需求/规则/约束/异常/非功能（报告 2.1）。
- 规则变更：BR-03 审批理由+优先级排序；BR-05 领取时限正式化（pickup_deadline
  + T-24h 提醒 + 48h 自动释放）；BR-06 异常归还升级为事务约束。
- 新增规则：BR-08 提交幂等、BR-09 审批回避、BR-10 结构化拒绝原因、
  BR-11 实际使用人登记。
- 数据模型：borrow_request 增 5 字段；新增 request_co_user、approval_record；
  notification 启用（schema.sql）。
- 领域模型：submit 幂等去重、approve 写审批记录、新增 reject/withdraw；
  自检覆盖 V2-01/02/04/06（domain_model.py）。
- API 契约：审批记录端点、优先级/使用人字段、幂等语义（api-contract.md）。
- 报告完成 V2 章节（2.1-2.6）；V1 能力回归项冻结。

## （后续版本在此追加）
