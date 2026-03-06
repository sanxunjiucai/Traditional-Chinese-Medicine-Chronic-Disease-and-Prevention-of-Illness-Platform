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
  const data = await get(serverUrl, `/tools/plugin/patient/search?q=${encodeURIComponent(keyword)}&page_size=10`);
  const list = Array.isArray(data) ? data : (data.items || data.records || []);
  if (!list || list.length === 0) {
    throw new Error(`未找到患者"${keyword}"，请确认已在平台登录且患者档案存在`);
  }
  return list; // 返回列表，调用方取第一个或供选择
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
  return get(serverUrl, `/tools/plugin/plan/diff?a=${plan_id_a}&b=${plan_id_b}`);
}

async function publishPlan(serverUrl, plan_id) {
  return post(serverUrl, `/tools/plugin/plan/${plan_id}/publish`, {});
}

async function renderSummary(serverUrl, plan_id, format = 'his_text') {
  return get(serverUrl, `/tools/plugin/plan/${plan_id}/summary?format=${format}`);
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

// ─── 旧版 API（保留兼容）────────────────────────────────────────────────────

async function triggerAnalyze(serverUrl, archive_id) {
  return fetchWithTimeout(
    `${serverUrl}/tools/risk/analyze/${archive_id}`,
    { method: 'POST', credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: '{}' },
    ANALYZE_TIMEOUT_MS
  ).then(parseApiResponse);
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
    const patient = { archive_id: p.id, name: p.name || '未知', patient_no: p.patient_no || p.archive_no || '' };

    // A. 绑定患者上下文
    let context = {};
    try {
      context = await bindPatientContext(serverUrl, patientId, { archive_id: patient.archive_id });
    } catch (_) { /* 上下文绑定失败不阻塞主流程 */ }

    // 触发风险分析（异步，允许失败）
    let risk = null;
    try {
      const analyzeResp = await triggerAnalyze(serverUrl, patient.archive_id);
      risk = analyzeResp?.analysis ?? analyzeResp;
    } catch (analyzeErr) {
      try {
        risk = await getRiskResult(serverUrl, patient.archive_id);
      } catch (_) {
        sendResponse({ patient, context, risk: null, warning: `AI分析暂时不可用：${analyzeErr.message}` });
        return;
      }
    }

    sendResponse({ patient, context, risk });
  } catch (err) {
    sendResponse({ error: `处理失败：${err.message}` });
  }
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

  if (action === 'getServerUrl') {
    getServerUrl().then(url => sendResponse({ url }));
    return true;
  }
});
