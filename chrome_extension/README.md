# 治未病·诊中助手 Chrome 插件

嵌入 HIS 系统旁边，当医生在 HIS 中查看患者时，自动识别患者 ID 并在右侧注入侧边栏，展示 AI 风险分析结果，支持一键下达中医调理方案。

---

## 文件结构

```
chrome_extension/
├── manifest.json        # 插件配置清单（Manifest V3）
├── background.js        # Service Worker，负责 API 通信
├── content.js           # 内容脚本，注入侧边栏
├── sidebar.css          # 侧边栏样式
├── popup.html           # 配置弹窗页面
├── popup.js             # 配置弹窗逻辑
├── icons/
│   ├── icon16.png
│   ├── icon48.png
│   └── icon128.png
└── README.md
```

---

## 安装方法（开发者模式）

1. 打开 Chrome 浏览器，访问 `chrome://extensions/`
2. 右上角开启 **"开发者模式"**（Developer mode）
3. 点击 **"加载已解压的扩展程序"**（Load unpacked）
4. 选择 `chrome_extension/` 目录（即本 README 所在目录）
5. 插件安装完成，工具栏出现绿色 🌿 图标

---

## 使用前提

1. **启动治未病平台后端服务**

   ```bash
   # 在项目根目录执行
   "/d/software/Python/python.exe" -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port 8010
   ```

2. **登录治未病平台**

   浏览器访问 `http://localhost:8010/login`，使用演示账号登录：

   | 账号 | 密码 |
   |------|------|
   | admin@tcm | Demo@123456 |
   | doctor@tcm | Demo@123456 |

   > 登录后浏览器会保存 `access_token` Cookie，插件通过该 Cookie 认证 API 请求。

3. **插件配置**（首次使用）

   点击工具栏插件图标，确认：
   - 后端服务地址：`http://localhost:8010`（**注意**：需在配置页手动改为 8010，默认值为 8001）
   - 患者ID参数名：`patient_id,pid,id,patientId,patient`（默认值，通常无需修改）

---

## HIS 配置说明

插件通过解析页面 URL 中的查询参数来识别患者 ID。不同 HIS 系统使用的参数名不同：

| HIS 系统示例 URL | 对应参数名 |
|-----------------|-----------|
| `.../patient?patient_id=P001` | `patient_id` |
| `.../visit?pid=12345` | `pid` |
| `.../record?id=ABC` | `id` |
| `.../emr?patientId=X99` | `patientId` |

**配置方法：**

1. 点击插件图标打开配置页
2. 在"HIS患者ID参数名"中填写您的 HIS 使用的参数名
3. 多个参数名用英文逗号分隔（插件按顺序依次尝试）
4. 点击"保存配置"

---

## 演示方法

无需 HIS 系统，直接用治未病平台页面测试：

1. 登录平台后访问档案列表：`http://localhost:8010/gui/admin/archives`
2. 点击任意患者进入详情页（URL 含 `/{archive_id}` 路径段）

**更直接的测试方式（手动搜索）：**

1. 打开任意网页（如 `http://localhost:8010/gui/admin/archives`）
2. 点击插件图标 → 在"手动搜索患者"框中输入患者姓名或档案号
3. 点击"搜索"→ 右侧边栏弹出并显示分析结果

**带 URL 参数的测试：**

在浏览器地址栏访问：
```
http://localhost:8010/gui/admin/archives?patient_id=张
```
插件会自动检测到 `patient_id=张` 并触发分析。

---

## 功能说明

### 自动检测

- 插件监听页面 URL 变化（含 SPA 路由切换）
- 检测到配置的参数名后自动向后台发起患者搜索 + AI 风险分析
- 分析结果实时展示在右侧固定侧边栏
- 使用 600ms 防抖，避免 URL 频繁变化时重复请求

### 侧边栏三 Tab

侧边栏固定在页面右侧，点击右上角「◀」收起为绿色竖条，点击竖条展开。

**Tab 1：当前风险**

- 患者信息卡：姓名 + 档案编号 + 风险等级徽章（高🔴/中🟠/低🟢）
- 风险证据：每条可点击展开溯源（检测值/参考范围/来源/日期）
- AI 摘要：自然语言风险说明（前 150 字）
- 「⚡ 确认下达方案」→ 弹出确认框（含自动随访选项：3/7/14/30 天）
- 「完整分析 ↗」→ 新标签页打开平台详情页

**Tab 2：历史方案**

展示该患者所有历史下达记录，支持状态流转：

`已下达 → 进行中 → 已随访 → 已复评 → 已完结`（或随时标记"调整方案"）

**Tab 3：数据指标**

- 总分析次数 / 已下达方案数
- 方案下达率（进度条）
- 随访完成率（进度条）

### 手动搜索

当 URL 中没有患者 ID 参数时，通过插件弹窗手动搜索患者。

---

## 注意事项

1. **跨域认证**：插件通过 `credentials: 'include'` 携带浏览器 Cookie，因此需要先在浏览器中登录平台。若出现"未授权"错误，请重新登录。

2. **AI 分析耗时**：风险分析调用 AI 接口，最多等待 15 秒。若超时，插件会尝试读取已有的历史分析结果。

3. **多标签页**：每个标签页独立运行内容脚本，侧边栏折叠状态通过 `chrome.storage` 跨标签页同步。

4. **兼容性**：仅支持 Chrome 93+ 及基于 Chromium 的浏览器（Edge、Brave 等）。

5. **性能**：插件使用防抖（600ms）避免 URL 频繁变化时重复请求。

---

## API 接口说明

插件调用的后端接口（Service Worker 通过 Cookie 认证）：

| 接口 | 说明 |
|------|------|
| `GET /tools/archive/archives?q={keyword}&page_size=1` | 搜索患者档案 |
| `POST /tools/risk/analyze/{archive_id}` | 触发 AI 风险分析（超时 15s，超时后回退读历史） |
| `GET /tools/risk/result/{archive_id}` | 获取已有风险分析结果 |
| `POST /tools/risk/plan/issue` | 下达调理方案（含 auto_followup_days 参数） |
| `GET /tools/risk/plans/{archive_id}?page_size=10` | 获取患者历史方案列表 |
| `PATCH /tools/risk/plans/{record_id}/state` | 更新方案状态 |
| `GET /tools/risk/stats` | 获取业务统计数据 |

所有接口返回格式：`{ success: bool, data: ..., error: { message: ... } }`
