# Tools 接口清单

> 所有接口统一前缀 `/tools`，响应格式见末尾「统一响应结构」。
> 认证方式：HttpOnly Cookie `access_token`（JWT）。
> 角色说明：`PATIENT` 患者、`PROFESSIONAL` 医生/健康管理师、`ADMIN` 管理员。

---

## 1. 认证模块 `/tools/auth`

### POST `/tools/auth/register` — 注册
- 权限：公开
- Body：
  ```json
  { "phone": "13800000001", "password": "123456", "name": "张三", "role": "PATIENT" }
  ```
- 成功 201：`{ "user_id": "<uuid>" }`
- 错误：`VALIDATION_ERROR 400` 手机号已注册

### POST `/tools/auth/login` — 登录
- 权限：公开
- Body：`{ "phone": "...", "password": "..." }`
- 成功 200：`{ "user_id", "role", "name" }` + 写 Cookie `access_token`
- 错误：`VALIDATION_ERROR 401` 密码错误；`PERMISSION_ERROR 403` 账号禁用

### POST `/tools/auth/logout` — 退出
- 权限：已登录（任意角色）
- 成功 200：删除 Cookie

### POST `/tools/auth/consent` — 同意隐私协议
- 权限：已登录（任意角色）
- Body：`{ "version": "1.0" }`
- 成功 200：`{ "consented": true, "version": "1.0" }`

---

## 2. 健康档案模块 `/tools`

### POST `/tools/profile` — 新建/更新个人健康档案
- 权限：PATIENT
- Body（字段均可选）：
  ```json
  {
    "gender": "M",
    "birth_date": "1985-06-15",
    "height_cm": 170.0,
    "weight_kg": 70.0,
    "waist_cm": 85.0,
    "smoking": "never",
    "drinking": "occasional",
    "exercise_frequency": "3x_week",
    "sleep_hours": 7.5,
    "stress_level": "medium"
  }
  ```
- 成功 200：`{ "profile_id": "<uuid>" }`

### POST `/tools/disease` — 添加慢病记录
- 权限：PATIENT
- Body：
  ```json
  {
    "disease_type": "HYPERTENSION",
    "diagnosed_at": "2022-01-10",
    "diagnosed_hospital": "某三甲医院",
    "medications": [{"name": "氨氯地平", "dose": "5mg", "frequency": "qd"}],
    "target_values": {"systolic": 130, "diastolic": 80},
    "notes": "备注"
  }
  ```
- 病种枚举：`HYPERTENSION`、`DIABETES_T2`
- 成功 201：`{ "record_id": "<uuid>" }`

### GET `/tools/disease` — 查询我的慢病列表
- 权限：PATIENT
- 返回当前活跃慢病记录列表

### POST `/tools/indicators` — 录入健康指标
- 权限：PATIENT
- Body：
  ```json
  {
    "indicator_type": "BLOOD_PRESSURE",
    "values": { "systolic": 145, "diastolic": 92 },
    "scene": "morning",
    "note": "昨晚睡眠差",
    "recorded_at": "2026-03-03T08:00:00"
  }
  ```
- 指标类型枚举：`BLOOD_PRESSURE`、`BLOOD_GLUCOSE`、`WEIGHT`、`WAIST_CIRCUMFERENCE`
- 血压 values：`{ "systolic": int, "diastolic": int }`
- 血糖 values：`{ "value": float, "unit": "mmol/L" }`
- 体重 values：`{ "value": float }`
- 成功 201：`{ "indicator_id": "<uuid>", "alerts_created": 0 }`（自动触发预警检测）

### GET `/tools/indicators` — 查询指标历史
- 权限：PATIENT
- Query：`indicator_type=BLOOD_PRESSURE&days=30`
- `days` 范围 1–365，默认 30
- 返回按时间升序的指标列表

---

## 3. 体质辨识模块 `/tools/constitution`

### GET `/tools/constitution/questions` — 获取问卷题目
- 权限：已登录（任意角色）
- 返回所有启用题目，按体质类型 + 顺序排列
- 题目结构：`{ "id", "code", "body_type", "seq", "content", "options": [{"label","value"}], "is_reverse" }`

### POST `/tools/constitution/start` — 开始/恢复评估
- 权限：PATIENT
- 返回：`{ "assessment_id": "<uuid>", "resumed": false }`
- 若已有 ANSWERING 状态评估则直接返回（幂等）

### POST `/tools/constitution/answer` — 批量保存答案
- 权限：PATIENT
- Body：
  ```json
  {
    "assessment_id": "<uuid>",
    "answers": [
      { "question_id": "<uuid>", "answer_value": 3 }
    ]
  }
  ```
- `answer_value`：1-5（1=没有，5=总是）
- 幂等，重复提交覆盖更新
- 成功 200：`{ "saved": 60 }`

### POST `/tools/constitution/submit` — 提交评估（触发评分）
- 权限：PATIENT
- Body：`{ "assessment_id": "<uuid>" }`
- 状态机：`ANSWERING → SUBMITTED → REPORTED`（评分后）
- 返回：
  ```json
  {
    "assessment_id": "<uuid>",
    "main_type": "QI_DEFICIENCY",
    "secondary_types": ["YANG_DEFICIENCY"],
    "recommendation_plan_id": "<uuid>",
    "scores": { "QI_DEFICIENCY": 62.5, "BALANCED": 45.0, ... }
  }
  ```
- 副作用：自动生成调护建议方案（RecommendationPlan）

### GET `/tools/constitution/latest` — 查询最新评估结果
- 权限：PATIENT
- 返回最近一次 REPORTED 状态的评估，无则返回 `null`

---

## 4. 随访打卡模块 `/tools/followup`

### POST `/tools/followup/start` — 启动随访计划
- 权限：PATIENT
- Body：`{ "disease_type": "HYPERTENSION", "start_date": "2026-03-03" }`
- 从模板库匹配 30 天计划，自动生成每日任务与打卡记录
- 成功 201：`{ "plan_id", "disease_type", "start_date", "end_date" }`

### GET `/tools/followup/plans` — 查询我的随访计划列表
- 权限：PATIENT
- 返回按创建时间倒序的计划列表，含状态（CREATED/ACTIVE/COMPLETED/TERMINATED）

### GET `/tools/followup/today` — 查询今日任务清单
- 权限：PATIENT
- 返回当前活跃计划今天的任务与打卡状态

### POST `/tools/followup/checkin` — 打卡
- 权限：PATIENT
- Body：`{ "task_id": "<uuid>", "value": {"steps": 8000}, "note": "感觉良好" }`
- 成功 200：`{ "checkin_id", "status": "DONE", "checked_at" }`
- 错误：`NOT_FOUND 404`（task 不属于该用户）

### GET `/tools/followup/adherence?plan_id=<uuid>` — 查询依从性
- 权限：PATIENT
- 返回：`{ "plan_id": "<uuid>", "adherence_rate": 0.85 }`

---

## 5. 预警模块 `/tools/alerts`

### GET `/tools/alerts/` — 查询我的预警列表
- 权限：已登录（任意角色）
- Query：`status=OPEN`（可选，枚举：OPEN / ACKED / CLOSED）
- 返回当前用户的预警事件列表

### GET `/tools/alerts/admin` — 查询全部预警（管理端）
- 权限：ADMIN / PROFESSIONAL
- Query：`status=OPEN&severity=HIGH`
- 返回所有用户的预警事件

### GET `/tools/alerts/{event_id}` — 查询预警详情
- 权限：ADMIN / PROFESSIONAL
- 返回单条预警事件完整信息

### PATCH `/tools/alerts/{event_id}/ack` — 确认预警
- 权限：ADMIN / PROFESSIONAL
- Body：`{ "handler_note": "已电话联系" }`
- 状态机：`OPEN → ACKED`
- 错误：`STATE_ERROR 409`（状态不符）

### PATCH `/tools/alerts/{event_id}/close` — 关闭预警
- 权限：ADMIN / PROFESSIONAL
- Body：`{ "handler_note": "复测正常，关闭" }`
- 状态机：`OPEN|ACKED → CLOSED`

---

## 6. 内容库模块 `/tools/content`

### GET `/tools/content/` — 查询已发布内容列表
- 权限：已登录（任意角色）
- Query：`tags=体质&skip=0&limit=20`
- 返回分页列表（不含 body 全文）

### GET `/tools/content/{content_id}` — 查询内容详情
- 权限：已登录（任意角色）
- 返回含 body 全文

### GET `/tools/content/admin` — 查询全量内容（管理端）
- 权限：ADMIN
- Query：`status=DRAFT&skip=0&limit=50`

### POST `/tools/content/` — 创建内容
- 权限：ADMIN
- Body：`{ "title", "summary", "body", "tags": [], "cover_url" }`
- 初始状态：DRAFT
- 成功 201：`{ "id", "content_id" }`

### PATCH `/tools/content/{content_id}` — 编辑内容
- 权限：ADMIN
- 仅 DRAFT / OFFLINE 状态可编辑

### PATCH `/tools/content/{content_id}/submit-review` — 提交审核
- 权限：ADMIN
- 状态机：`DRAFT → PENDING_REVIEW`

### PATCH `/tools/content/{content_id}/publish` — 发布
- 权限：ADMIN
- Body：`{ "review_note": "审核通过" }`
- 状态机：`PENDING_REVIEW → PUBLISHED`

### PATCH `/tools/content/{content_id}/offline` — 下线
- 权限：ADMIN
- 状态机：`PUBLISHED → OFFLINE`

---

## 7. 审计日志模块 `/tools/audit`

### GET `/tools/audit/` — 查询审计日志
- 权限：ADMIN
- Query：
  - `user_id=<uuid>`（可选）
  - `action=LOGIN`（可选）
  - `from_date=2026-01-01`（可选，YYYY-MM-DD）
  - `to_date=2026-03-03`（可选）
  - `page=1&page_size=30`
- 返回：
  ```json
  {
    "total": 1250,
    "page": 1,
    "page_size": 30,
    "items": [
      {
        "id", "action", "resource_type", "resource_id",
        "user_id", "ip_address", "old_values", "new_values",
        "extra", "created_at"
      }
    ]
  }
  ```
- 已覆盖 action 类型：`LOGIN`、`REGISTER`、`CONSENT`、`UPDATE_PROFILE`、`ADD_DISEASE`、`ADD_INDICATOR`、`START_ASSESSMENT`、`SUBMIT_ASSESSMENT`、`START_FOLLOWUP_PLAN`、`CHECKIN`、`ACK_ALERT`、`CLOSE_ALERT`、`CREATE_CONTENT`、`SUBMIT_REVIEW`、`PUBLISH_CONTENT`、`OFFLINE_CONTENT`

---

## 统一响应结构

### 成功
```json
{ "ok": true, "data": <any> }
```

### 失败
```json
{ "ok": false, "code": "ERROR_CODE", "message": "错误描述" }
```

### 错误码
| code | 含义 |
|---|---|
| `VALIDATION_ERROR` | 参数校验失败 |
| `NOT_FOUND` | 资源不存在 |
| `PERMISSION_ERROR` | 权限不足 / 账号禁用 |
| `STATE_ERROR` | 状态机流转非法 |
| `INTERNAL_ERROR` | 服务内部错误 |

---

## 枚举值速查

| 枚举 | 值 |
|---|---|
| UserRole | `PATIENT` `PROFESSIONAL` `ADMIN` |
| DiseaseType | `HYPERTENSION` `DIABETES_T2` |
| IndicatorType | `BLOOD_PRESSURE` `BLOOD_GLUCOSE` `WEIGHT` `WAIST_CIRCUMFERENCE` |
| BodyType | `BALANCED` `QI_DEFICIENCY` `YANG_DEFICIENCY` `YIN_DEFICIENCY` `PHLEGM_DAMPNESS` `DAMP_HEAT` `BLOOD_STASIS` `QI_STAGNATION` `SPECIAL_DIATHESIS` |
| AssessmentStatus | `ANSWERING` `SUBMITTED` `SCORED` `REPORTED` |
| FollowupStatus | `CREATED` `ACTIVE` `COMPLETED` `TERMINATED` |
| CheckInStatus | `PENDING` `DONE` `MISSED` |
| AlertSeverity | `LOW` `MEDIUM` `HIGH` |
| AlertStatus | `OPEN` `ACKED` `CLOSED` |
| ContentStatus | `DRAFT` `PENDING_REVIEW` `PUBLISHED` `OFFLINE` |
| TaskType | `INDICATOR_REPORT` `EXERCISE` `MEDICATION` `SLEEP` `DIET` |
| RecommendationCategory | `DAILY_ROUTINE` `DIET` `EXERCISE` `EMOTIONAL` `EXTERNAL` |
