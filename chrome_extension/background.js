/**
 * background.js - Service Worker
 * 治未病·诊中助手 后台服务
 * v3.0 - 支持 A-E 插件规范：上下文绑定/患者档案/方案版本/模板/随访
 */

const DEFAULT_SERVER = 'http://localhost:8010';
const ANALYZE_TIMEOUT_MS = 15000;

async function getServerUrl() {
  return new Promise((resolve) => {
    chrome.storage.local.get(['serverUrl'], (r) => resolve(r.serverUrl || DEFAULT_SERVER));
  });
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 10000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { ...options, signal: ctrl.signal });
    clearTimeout(timer);
    return resp;
  } catch (err) {
    clearTimeout(timer);
    if (err.name === 'AbortError') throw new Error('请求超时，请检查网络连接');
    throw err;
  }
}

async function parseApiResponse(resp) {
  let body;
  try { body = await resp.json(); } catch (_) {
    throw new Error(`服务器返回非JSON响应 (HTTP ${resp.status})`);
  }
  if (!resp.ok || body.success === false) {
    const msg = body?.error?.message || body?.detail || `HTTP ${resp.status}`;
    throw new Error(msg);
  }
  return body.data !== undefined ? body.data : body;
}

function get(serverUrl, path, timeoutMs = 8000) {
  return fetchWithTimeout(`${serverUrl}${path}`, {
    credentials: 'include', headers: { Accept: 'application/json' }
  }, timeoutMs).then(parseApiResponse);
}

function post(serverUrl, path, body = {}, timeoutMs = 10000) {
  return fetchWithTimeout(`${serverUrl}${path}`, {
    method: 'POST', credentials: 'include',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }, timeoutMs).then(parseApiResponse);
}

function patch(serverUrl, path, body = {}, timeoutMs = 8000) {
  return fetchWithTimeout(`${serverUrl}${path}`, {
    method: 'PATCH', credentials: 'include',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }, timeoutMs).then(parseApiResponse);
}

// ─── A. 上下文绑定 ────────────────────────────────────────────────────────────

async function bindPatientContext(serverUrl, patient_key, extra = {}) {
  return post(serverUrl, '/tools/plugin/bind', { patient_key, ...extra });
}

// ─── B. 患者档案 ─────────────────────────────────────────────────────────────

async function searchPatient(serverUrl, keyword) {
  const data = await get(serverUrl, `/tools/plugin/patient/search?query=${encodeURIComponent(keyword)}&page_size=10`);
  const list = Array.isArray(data) ? data : (data.items || data.records || []);
  if (!list || list.length === 0) {
    throw new Error(`未找到患者"${keyword}"，请确认已在平台登录且患者档案存在`);
  }
  return list; // 返回列表，调用方取第一个或供选择
}

async function searchPatientList(serverUrl, keyword, pageSize = 50) {
  // 用 "1" 作为空查询兜底（所有中国手机号含 "1"）
  const q = keyword?.trim() || '1';
  const data = await get(serverUrl, `/tools/plugin/patient/search?query=${encodeURIComponent(q)}&page_size=${pageSize}`);
  return Array.isArray(data) ? data : (data.items || []);
}

async function getPatientProfile(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/patient/${patient_id}/profile`);
}

async function getPatientMetrics(serverUrl, patient_id, range = 90) {
  return get(serverUrl, `/tools/plugin/patient/${patient_id}/metrics?range=${range}`);
}

async function getRiskTags(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/patient/${patient_id}/risk-tags`);
}

async function getRiskConclusions(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/patient/${patient_id}/risk-conclusions`);
}

async function supplementPatient(serverUrl, patient_id, body) {
  return post(serverUrl, `/tools/plugin/patient/${patient_id}/supplement`, body);
}

// ─── C. 方案版本 ─────────────────────────────────────────────────────────────

async function getPlanVersions(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/plan/versions/${patient_id}`);
}

async function getCurrentPlan(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/plan/current/${patient_id}`);
}

async function createDraft(serverUrl, body) {
  return post(serverUrl, '/tools/plugin/plan/draft', body);
}

async function updateDraft(serverUrl, plan_id, body) {
  return patch(serverUrl, `/tools/plugin/plan/${plan_id}/draft`, body);
}

async function diffPlans(serverUrl, plan_id_a, plan_id_b) {
  return get(serverUrl, `/tools/plugin/plan/diff?plan_id_old=${plan_id_a}&plan_id_new=${plan_id_b}`);
}

async function publishPlan(serverUrl, plan_id) {
  return post(serverUrl, `/tools/plugin/plan/${plan_id}/publish`, {});
}

async function renderSummary(serverUrl, plan_id, format = 'his_text') {
  return get(serverUrl, `/tools/plugin/plan/${plan_id}/summary?format=${format}`);
}

async function getPlanPreview(serverUrl, plan_id) {
  return get(serverUrl, `/tools/plugin/plan/${plan_id}/preview`);
}

async function confirmPlan(serverUrl, plan_id) {
  return post(serverUrl, `/tools/plugin/plan/${plan_id}/confirm`, {});
}

async function distributePlan(serverUrl, plan_id, auto_followup_days = 7) {
  return post(serverUrl, `/tools/plugin/plan/${plan_id}/distribute`, {
    targets: ['his', 'patient_h5', 'management'],
    auto_followup_days,
  });
}

async function getPackageRecommendation(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/patient/${patient_id}/package-recommendation`);
}

// ─── D. 模板知识库 ────────────────────────────────────────────────────────────

async function listTemplates(serverUrl, category = '') {
  const q = category ? `?category=${encodeURIComponent(category)}` : '';
  return get(serverUrl, `/tools/plugin/template/list${q}`);
}

async function getTemplate(serverUrl, template_id) {
  return get(serverUrl, `/tools/plugin/template/${template_id}`);
}

// ─── E. 随访 ─────────────────────────────────────────────────────────────────

async function createFollowupPlan(serverUrl, body) {
  return post(serverUrl, '/tools/plugin/followup/plan', body);
}

async function listFollowupTasks(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/followup/tasks/${patient_id}`);
}

// ─── F. 召回建议 ──────────────────────────────────────────────────────────────

async function getRecallSuggestions(serverUrl, patient_id) {
  return get(serverUrl, `/tools/plugin/recall/${patient_id}`);
}

async function handleRecallAction(serverUrl, alert_id, action, note) {
  return patch(serverUrl, `/tools/plugin/recall/${alert_id}/action`, { action, note });
}

// ─── G. 工作台 ────────────────────────────────────────────────────────────────

async function getWorkbenchPending(serverUrl) {
  return get(serverUrl, '/tools/plugin/workbench/pending');
}

// ─── H. 患者反馈摘要 ──────────────────────────────────────────────────────────

async function getPatientFeedback(serverUrl, patient_id, limit = 5) {
  return get(serverUrl, `/tools/plugin/patient/${patient_id}/feedback?limit=${limit}`);
}

// ─── 旧版 API（保留兼容）────────────────────────────────────────────────────

async function triggerAnalyze(serverUrl, archive_id) {
  return fetchWithTimeout(
    `${serverUrl}/tools/risk/analyze/${archive_id}`,
    { method: 'POST', credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: '{}' },
    ANALYZE_TIMEOUT_MS
  ).then(parseApiResponse);
}

async function triggerAnalyzeWithContext(serverUrl, archive_id, extra_context = '') {
  return fetchWithTimeout(
    `${serverUrl}/tools/risk/analyze/${archive_id}`,
    { method: 'POST', credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ extra_context }) },
    ANALYZE_TIMEOUT_MS
  ).then(parseApiResponse);
}

async function generatePlanWithContext(serverUrl, archive_id, extra_context = '') {
  return post(serverUrl, '/tools/risk/plan/generate', { archive_id, extra_context }, ANALYZE_TIMEOUT_MS);
}

async function getRiskResult(serverUrl, archive_id) {
  return get(serverUrl, `/tools/risk/result/${archive_id}`);
}

async function issuePlanApi(serverUrl, archive_id, plan_title, plan_content, auto_followup_days) {
  return post(serverUrl, '/tools/risk/plan/issue', { archive_id, title: plan_title, plan_content, auto_followup_days });
}

async function getIssuedPlansApi(serverUrl, archive_id) {
  return get(serverUrl, `/tools/risk/plans/${archive_id}?page_size=10`);
}

async function getRiskStatsApi(serverUrl) {
  return get(serverUrl, '/tools/risk/stats');
}

async function updatePlanStateApi(serverUrl, record_id, state, note) {
  return patch(serverUrl, `/tools/risk/plans/${record_id}/state`, { state, note });
}

// ─── 主流程：患者检测 ─────────────────────────────────────────────────────────

async function handlePatientDetected(patientId, sendResponse) {
  try {
    const serverUrl = await getServerUrl();

    // B. 搜索患者
    let patientList;
    try {
      patientList = await searchPatient(serverUrl, patientId);
    } catch (err) {
      sendResponse({ error: err.message });
      return;
    }
    const p = patientList[0];
    const patient = { archive_id: p.patient_id, name: p.name || '未知', patient_no: p.patient_no || p.archive_no || '' };

    // A. 绑定患者上下文
    let context = {};
    try {
      context = await bindPatientContext(serverUrl, patientId, { archive_id: patient.archive_id });
    } catch (_) { /* 上下文绑定失败不阻塞主流程 */ }

    // 优先使用已有缓存结果，立即返回（避免 triggerAnalyze 的 15 秒阻塞）
    let risk = null;
    try {
      risk = await getRiskResult(serverUrl, patient.archive_id);
    } catch (_) { /* 无缓存风险，正常，risk = null */ }

    // 先立即响应（带或不带 risk），让 UI 快速呈现
    sendResponse({ patient, context, risk });

    // 后台异步触发新一轮分析（不阻塞 UI）
    triggerAnalyze(serverUrl, patient.archive_id).catch(() => {});
  } catch (err) {
    sendResponse({ error: `处理失败：${err.message}` });
  }
}

// ─── Agent Configuration ───────────────────────────────────────────────────

const CLAUDE_MODEL_DEFAULT = 'claude-3-5-sonnet-20241022';
const AGENT_MAX_ITERATIONS = 10;

async function getApiKey() {
  return new Promise(resolve =>
    chrome.storage.local.get(['anthropicApiKey'], r => resolve(r.anthropicApiKey || ''))
  );
}

async function getSearchKey() {
  return new Promise(resolve =>
    chrome.storage.local.get(['braveSearchKey'], r => resolve(r.braveSearchKey || ''))
  );
}

async function getClaudeBaseUrl() {
  return new Promise(resolve =>
    chrome.storage.local.get(['claudeBaseUrl'], r =>
      resolve((r.claudeBaseUrl || 'https://api.anthropic.com').replace(/\/$/, ''))
    )
  );
}

async function getClaudeModel() {
  return new Promise(resolve =>
    chrome.storage.local.get(['claudeModel'], r =>
      resolve(r.claudeModel?.trim() || CLAUDE_MODEL_DEFAULT)
    )
  );
}

// ─── Tool Definitions ──────────────────────────────────────────────────────

const TCM_TOOL_DEFS = [
  {
    name: 'search_patient',
    description: '按姓名、手机号或档案号搜索患者，返回匹配列表',
    input_schema: { type: 'object', properties: { keyword: { type: 'string', description: '患者姓名、手机号或档案号' } }, required: ['keyword'] }
  },
  {
    name: 'get_patient_profile',
    description: '获取患者详细档案（基本信息、既往史、过敏史等）',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' } }, required: ['patient_id'] }
  },
  {
    name: 'get_patient_metrics',
    description: '获取患者近期健康指标（血压、血糖、体重等）',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' }, range: { type: 'number', description: '查询天数，默认90' } }, required: ['patient_id'] }
  },
  {
    name: 'get_risk_analysis',
    description: '获取患者中医风险评估结果（风险等级、证候、证据链）',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' } }, required: ['patient_id'] }
  },
  {
    name: 'get_risk_tags',
    description: '获取患者风险标签列表',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' } }, required: ['patient_id'] }
  },
  {
    name: 'get_current_plan',
    description: '获取患者当前有效治疗方案',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' } }, required: ['patient_id'] }
  },
  {
    name: 'get_plan_versions',
    description: '获取患者所有历史方案版本',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' } }, required: ['patient_id'] }
  },
  {
    name: 'create_draft_plan',
    description: '为患者创建新的方案草稿（需用户确认后发布）',
    input_schema: { type: 'object', properties: { archive_id: { type: 'string', description: '患者档案ID' }, title: { type: 'string', description: '方案标题' }, plan_content: { type: 'string', description: '方案内容（治法、方药、医嘱）' }, syndrome: { type: 'string', description: '中医证型' } }, required: ['archive_id', 'title', 'plan_content'] }
  },
  {
    name: 'publish_plan',
    description: '正式发布/下达患者方案（草稿 → 已发布）',
    input_schema: { type: 'object', properties: { plan_id: { type: 'string', description: '方案ID' } }, required: ['plan_id'] }
  },
  {
    name: 'list_templates',
    description: '列出中医方案模板库',
    input_schema: { type: 'object', properties: { category: { type: 'string', description: '模板类别，如：高血压、糖尿病、失眠（不传返回全部）' } } }
  },
  {
    name: 'create_followup_plan',
    description: '为患者创建随访计划',
    input_schema: { type: 'object', properties: { archive_id: { type: 'string', description: '患者档案ID' }, followup_date: { type: 'string', description: '随访日期 YYYY-MM-DD' }, followup_type: { type: 'string', description: 'PHONE/VISIT/ONLINE' }, content: { type: 'string', description: '随访内容说明' } }, required: ['archive_id', 'followup_date'] }
  },
  {
    name: 'list_followup_tasks',
    description: '获取患者随访任务列表',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' } }, required: ['patient_id'] }
  },
  {
    name: 'get_recall_suggestions',
    description: '获取患者召回建议（需复诊理由和紧迫程度）',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' } }, required: ['patient_id'] }
  },
  {
    name: 'handle_recall_action',
    description: '处理召回建议（接受或忽略）',
    input_schema: { type: 'object', properties: { alert_id: { type: 'string', description: '召回提醒ID' }, action: { type: 'string', enum: ['accept', 'dismiss'], description: '处理动作' }, note: { type: 'string', description: '备注' } }, required: ['alert_id', 'action'] }
  },
  {
    name: 'get_workbench_pending',
    description: '获取当前医生工作台的待处理事项',
    input_schema: { type: 'object', properties: {} }
  },
  {
    name: 'get_patient_feedback',
    description: '获取患者最近反馈和主诉记录',
    input_schema: { type: 'object', properties: { patient_id: { type: 'string', description: '患者档案ID' }, limit: { type: 'number', description: '返回条数，默认5' } }, required: ['patient_id'] }
  },
  {
    name: 'web_search',
    description: '搜索网络获取最新医学资讯、药品说明、临床指南等信息',
    input_schema: { type: 'object', properties: { query: { type: 'string', description: '搜索关键词（中文或专业术语）' } }, required: ['query'] }
  }
];

// ─── Tool Execution ────────────────────────────────────────────────────────

async function executeTool(toolName, input, serverUrl) {
  switch (toolName) {
    case 'search_patient':         return searchPatient(serverUrl, input.keyword);
    case 'get_patient_profile':    return getPatientProfile(serverUrl, input.patient_id);
    case 'get_patient_metrics':    return getPatientMetrics(serverUrl, input.patient_id, input.range || 90);
    case 'get_risk_analysis':      return getRiskResult(serverUrl, input.patient_id);
    case 'get_risk_tags':          return getRiskTags(serverUrl, input.patient_id);
    case 'get_current_plan':       return getCurrentPlan(serverUrl, input.patient_id);
    case 'get_plan_versions':      return getPlanVersions(serverUrl, input.patient_id);
    case 'create_draft_plan':      return createDraft(serverUrl, { archive_id: input.archive_id, title: input.title, plan_content: input.plan_content, syndrome: input.syndrome || '' });
    case 'publish_plan':           return publishPlan(serverUrl, input.plan_id);
    case 'list_templates':         return listTemplates(serverUrl, input.category || '');
    case 'create_followup_plan':   return createFollowupPlan(serverUrl, { archive_id: input.archive_id, followup_date: input.followup_date, followup_type: input.followup_type || 'PHONE', content: input.content || '' });
    case 'list_followup_tasks':    return listFollowupTasks(serverUrl, input.patient_id);
    case 'get_recall_suggestions': return getRecallSuggestions(serverUrl, input.patient_id);
    case 'handle_recall_action':   return handleRecallAction(serverUrl, input.alert_id, input.action, input.note || '');
    case 'get_workbench_pending':  return getWorkbenchPending(serverUrl);
    case 'get_patient_feedback':   return getPatientFeedback(serverUrl, input.patient_id, input.limit || 5);
    case 'web_search':             return agentWebSearch(input.query);
    default: throw new Error(`未知工具：${toolName}`);
  }
}

// ─── Web Search ───────────────────────────────────────────────────────────

async function agentWebSearch(query) {
  const searchKey = await getSearchKey();
  if (searchKey) {
    try {
      const resp = await fetchWithTimeout(
        `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=5&text_decorations=false`,
        { headers: { 'Accept': 'application/json', 'X-Subscription-Token': searchKey } },
        10000
      );
      const data = await resp.json();
      const results = (data.web?.results || []).slice(0, 5).map(r => ({ title: r.title, url: r.url, description: r.description }));
      return { query, results, source: 'brave' };
    } catch (_) { /* fall through */ }
  }
  // DuckDuckGo Instant Answer fallback
  const resp = await fetchWithTimeout(
    `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1`,
    {}, 8000
  );
  const data = await resp.json();
  const results = [];
  if (data.AbstractText) results.push({ title: data.Heading, url: data.AbstractURL, description: data.AbstractText });
  (data.RelatedTopics || []).slice(0, 4).forEach(t => {
    if (t.Text) results.push({ title: t.Text.slice(0, 80), url: t.FirstURL, description: t.Text });
  });
  return { query, results, source: 'duckduckgo', note: '结果有限，可在配置中添加 Brave Search Key 获取更好效果' };
}

// ─── System Prompt ────────────────────────────────────────────────────────

function buildSystemPrompt(patientCtx) {
  const now = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
  const p = patientCtx?.patient;
  const risk = patientCtx?.risk;
  const plan = patientCtx?.plan;

  let ctx = '当前未选择患者，需要时请用 search_patient 工具查找。';
  if (p?.name) {
    ctx = `当前患者：${p.name}（档案ID：${p.archive_id}${p.patient_no ? '，档案号：' + p.patient_no : ''}）`;
    if (risk?.risk_level) ctx += `\n风险状态：${risk.risk_level} | 主证：${risk.main_syndrome || '待评估'}`;
    if (plan?.title)      ctx += `\n当前方案：${plan.title}（${plan.status || '未知'}）`;
  }

  return `你是治未病·诊中助手，中医慢病管理平台的临床决策AI，今日：${now}。

${ctx}

工作原则：
1. 优先用已有患者上下文，避免重复API调用
2. 写操作（创建/发布方案、创建随访）前明确告知用户
3. 回复用简洁专业中文，可用 **加粗** 和分条列举
4. 引用数据注明来源（哪个工具返回）
5. 医学建议说明局限性，建议结合医师判断`;
}

// ─── Claude API Call ──────────────────────────────────────────────────────

async function callClaude(messages, systemPrompt, apiKey, claudeBaseUrl, claudeModel) {
  const endpoint = (claudeBaseUrl || 'https://api.anthropic.com') + '/v1/messages';
  const resp = await fetchWithTimeout(
    endpoint,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model: claudeModel || CLAUDE_MODEL_DEFAULT,
        max_tokens: 4096,
        system: systemPrompt,
        messages,
        tools: TCM_TOOL_DEFS
      })
    },
    90000
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error?.message || `Claude API 错误 (HTTP ${resp.status})`);
  }
  return resp.json();
}

// ─── Agent via Local Server (SSE) ─────────────────────────────────────────

async function runAgentViaServer(tabId, userMessage, patientCtx, serverUrl, imageData) {
  sendProgress(tabId, { type: 'thinking' });

  // 若有图片，先提示（SSE 端点暂不传图片，直接附在 query 里说明）
  let query = userMessage || '请分析';
  if (imageData) {
    query += '\n（注：用户附带了一张图片，请根据上下文理解）';
  }

  const url = `${serverUrl}/tools/plugin/agent/stream`;
  let resp;
  try {
    resp = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        patient_id:   patientCtx?.id   || null,
        patient_name: patientCtx?.name || null,
      }),
    });
  } catch (err) {
    sendProgress(tabId, { type: 'error', text: `无法连接到本地服务器：${err.message}` });
    return;
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const msg = body?.detail || body?.message || `HTTP ${resp.status}`;
    sendProgress(tabId, { type: 'error', text: `服务器错误：${msg}` });
    return;
  }

  // 读取 SSE 流
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // 逐行解析 SSE data: {...}
    const lines = buf.split('\n');
    buf = lines.pop(); // 最后不完整行留给下次
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      let evt;
      try { evt = JSON.parse(line.slice(6)); } catch { continue; }

      switch (evt.type) {
        case 'thinking':
          sendProgress(tabId, { type: 'thinking' });
          break;
        case 'tool_call':
          sendProgress(tabId, { type: 'tool_call', toolName: evt.tool, toolInput: evt.input });
          break;
        case 'tool_result':
          sendProgress(tabId, { type: 'tool_done', toolName: evt.tool });
          break;
        case 'done':
          sendProgress(tabId, { type: 'done', text: evt.message || '' });
          break;
        case 'error':
          sendProgress(tabId, { type: 'error', text: evt.message || 'Agent 出错' });
          break;
      }
    }
  }
}

// ─── Progress Sender ──────────────────────────────────────────────────────

function sendProgress(tabId, payload) {
  if (!tabId) return;
  chrome.tabs.sendMessage(tabId, { action: 'agentProgress', ...payload }).catch(() => {});
}

// ─── Agent Loop ───────────────────────────────────────────────────────────

async function runAgentLoop(tabId, userMessage, patientCtx, apiKey, serverUrl, imageData, claudeBaseUrl, claudeModel) {
  const systemPrompt = buildSystemPrompt(patientCtx);

  // Build first user message (optionally with image for OCR/vision)
  let firstContent = userMessage || '请分析';
  if (imageData) {
    firstContent = [
      { type: 'image', source: { type: 'base64', media_type: imageData.mediaType, data: imageData.data } },
      { type: 'text', text: userMessage || '请分析这张图片' }
    ];
  }

  const messages = [{ role: 'user', content: firstContent }];
  sendProgress(tabId, { type: 'thinking' });

  for (let i = 0; i < AGENT_MAX_ITERATIONS; i++) {
    let claudeResp;
    try {
      claudeResp = await callClaude(messages, systemPrompt, apiKey, claudeBaseUrl, claudeModel);
    } catch (err) {
      sendProgress(tabId, { type: 'error', text: `AI调用失败：${err.message}` });
      return;
    }

    if (claudeResp.stop_reason === 'end_turn') {
      const text = claudeResp.content.filter(b => b.type === 'text').map(b => b.text).join('\n');
      sendProgress(tabId, { type: 'done', text });
      return;
    }

    if (claudeResp.stop_reason === 'tool_use') {
      const toolBlocks = claudeResp.content.filter(b => b.type === 'tool_use');
      messages.push({ role: 'assistant', content: claudeResp.content });

      const toolResults = [];
      for (const tu of toolBlocks) {
        sendProgress(tabId, { type: 'tool_call', toolName: tu.name, toolInput: tu.input });
        let result;
        try {
          result = await executeTool(tu.name, tu.input, serverUrl);
          sendProgress(tabId, { type: 'tool_done', toolName: tu.name });
        } catch (err) {
          result = { error: err.message };
          sendProgress(tabId, { type: 'tool_error', toolName: tu.name, error: err.message });
        }
        toolResults.push({ type: 'tool_result', tool_use_id: tu.id, content: JSON.stringify(result) });
      }
      messages.push({ role: 'user', content: toolResults });
      sendProgress(tabId, { type: 'thinking' });
      continue;
    }

    sendProgress(tabId, { type: 'error', text: `意外停止：${claudeResp.stop_reason}` });
    return;
  }

  sendProgress(tabId, { type: 'error', text: '已达最大推理轮次，任务中断' });
}

// ─── 消息路由 ─────────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const { action } = message;

  // ── A ──
  if (action === 'patientDetected') {
    handlePatientDetected(message.patientId, sendResponse);
    return true;
  }

  if (action === 'bindContext') {
    getServerUrl().then(serverUrl =>
      bindPatientContext(serverUrl, message.patient_key, message.extra || {})
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── B ──
  if (action === 'getPatientProfile') {
    getServerUrl().then(serverUrl =>
      getPatientProfile(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getPatientMetrics') {
    getServerUrl().then(serverUrl =>
      getPatientMetrics(serverUrl, message.patient_id, message.range || 90)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getRiskTags') {
    getServerUrl().then(serverUrl =>
      getRiskTags(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getRiskConclusions') {
    getServerUrl().then(serverUrl =>
      getRiskConclusions(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'supplementPatient') {
    getServerUrl().then(serverUrl =>
      supplementPatient(serverUrl, message.patient_id, message.body || {})
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── C ──
  if (action === 'getPlanVersions') {
    getServerUrl().then(serverUrl =>
      getPlanVersions(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getCurrentPlan') {
    getServerUrl().then(serverUrl =>
      getCurrentPlan(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'createDraft') {
    getServerUrl().then(serverUrl =>
      createDraft(serverUrl, message.body)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'updateDraft') {
    getServerUrl().then(serverUrl =>
      updateDraft(serverUrl, message.plan_id, message.body)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'diffPlans') {
    getServerUrl().then(serverUrl =>
      diffPlans(serverUrl, message.plan_id_a, message.plan_id_b)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'publishPlan') {
    getServerUrl().then(serverUrl =>
      publishPlan(serverUrl, message.plan_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'renderSummary') {
    getServerUrl().then(serverUrl =>
      renderSummary(serverUrl, message.plan_id, message.format || 'his_text')
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getPlanPreview') {
    getServerUrl().then(serverUrl =>
      getPlanPreview(serverUrl, message.plan_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'confirmPlan') {
    getServerUrl().then(serverUrl =>
      confirmPlan(serverUrl, message.plan_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'distributePlan') {
    getServerUrl().then(serverUrl =>
      distributePlan(serverUrl, message.plan_id, message.auto_followup_days || 7)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getPackageRecommendation') {
    getServerUrl().then(serverUrl =>
      getPackageRecommendation(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── D ──
  if (action === 'listTemplates') {
    getServerUrl().then(serverUrl =>
      listTemplates(serverUrl, message.category || '')
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getTemplate') {
    getServerUrl().then(serverUrl =>
      getTemplate(serverUrl, message.template_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── E ──
  if (action === 'createFollowupPlan') {
    getServerUrl().then(serverUrl =>
      createFollowupPlan(serverUrl, message.body)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'listFollowupTasks') {
    getServerUrl().then(serverUrl =>
      listFollowupTasks(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── 风险结果（独立查询）──
  if (action === 'getRiskResult') {
    getServerUrl().then(serverUrl =>
      getRiskResult(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'analyzeRiskWithContext') {
    getServerUrl().then(serverUrl =>
      triggerAnalyzeWithContext(serverUrl, message.patient_id, message.extra_context || '')
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'generatePlanWithContext') {
    getServerUrl().then(serverUrl =>
      generatePlanWithContext(serverUrl, message.patient_id, message.extra_context || '')
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── 旧版兼容 ──
  if (action === 'issuePlan') {
    const { archive_id, plan_title, plan_content, auto_followup_days } = message;
    getServerUrl().then(serverUrl =>
      issuePlanApi(serverUrl, archive_id, plan_title, plan_content, auto_followup_days ?? 7)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getIssuedPlans') {
    getServerUrl().then(serverUrl =>
      getIssuedPlansApi(serverUrl, message.archive_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getRiskStats') {
    getServerUrl().then(serverUrl =>
      getRiskStatsApi(serverUrl)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'updatePlanState') {
    getServerUrl().then(serverUrl =>
      updatePlanStateApi(serverUrl, message.record_id, message.state, message.note || '')
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── F. 召回建议 ──
  if (action === 'getRecallSuggestions') {
    getServerUrl().then(serverUrl =>
      getRecallSuggestions(serverUrl, message.patient_id)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'handleRecallAction') {
    getServerUrl().then(serverUrl =>
      handleRecallAction(serverUrl, message.alert_id, message.recall_action, message.note || '')
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── G. 工作台 ──
  if (action === 'getWorkbenchPending') {
    getServerUrl().then(serverUrl =>
      getWorkbenchPending(serverUrl)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── H. 患者反馈摘要 ──
  if (action === 'getPatientFeedback') {
    getServerUrl().then(serverUrl =>
      getPatientFeedback(serverUrl, message.patient_id, message.limit || 5)
        .then(data => sendResponse({ success: true, data }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  if (action === 'getServerUrl') {
    getServerUrl().then(url => sendResponse({ url }));
    return true;
  }

  if (action === 'patientSearch') {
    getServerUrl().then(serverUrl =>
      searchPatientList(serverUrl, message.keyword || ' ', message.pageSize || 50)
        .then(items => sendResponse({ success: true, data: { items } }))
        .catch(err => sendResponse({ success: false, error: err.message }))
    );
    return true;
  }

  // ── I. Agent Chat ──
  if (action === 'agentChat') {
    const tabId = sender?.tab?.id;
    sendResponse({ started: true });
    Promise.all([getApiKey(), getServerUrl(), getClaudeBaseUrl(), getClaudeModel()]).then(([apiKey, serverUrl, claudeBaseUrl, claudeModel]) => {
      if (apiKey) {
        // 扩展本地有 key → 直接从浏览器调用（绕过后端，不受 Cloudflare 拦截）
        runAgentLoop(tabId, message.message, message.patientContext, apiKey, serverUrl, message.imageData, claudeBaseUrl, claudeModel);
      } else {
        // 无本地 key → 回退到后端服务器代理
        runAgentViaServer(tabId, message.message, message.patientContext, serverUrl, message.imageData);
      }
    });
    return true;
  }
});
