/**
 * app.js - 渲染进程主逻辑
 * 治未病·诊中助手 桌面版
 * 使用 electronAPI（preload 注入）替代 chrome.* API
 */

'use strict';

// ─── 存储抽象（替代 chrome.storage.local）───────────────────────────────────

const storage = {
  async get(keys) {
    return window.electronAPI.storage.get(keys);
  },
  async set(items) {
    return window.electronAPI.storage.set(items);
  },
};

// ─── 配置 ───────────────────────────────────────────────────────────────────

const DEFAULT_SERVER = 'http://localhost:8015';
const DEFAULT_PARAMS = 'patient_id,pid,id,patientId,patient';
const AGENT_SSE_PATH = '/tools/plugin/agent/stream';
const TOOL_LABELS = {
  search_patient:        '搜索患者',
  get_patient_profile:   '读取患者档案',
  get_patient_metrics:   '查询健康指标',
  get_risk_analysis:     '读取风险分析',
  get_risk_tags:         '查询风险标签',
  get_current_plan:      '获取当前方案',
  get_plan_versions:     '查询方案版本',
  create_draft_plan:     '创建方案草稿',
  publish_plan:          '发布方案',
  list_templates:        '查询方案模板',
  create_followup_plan:  '创建随访计划',
  list_followup_tasks:   '查询随访任务',
  get_recall_suggestions:'查询召回建议',
  handle_recall_action:  '处理召回建议',
  get_workbench_pending: '查询工作台',
  get_patient_feedback:  '查询患者反馈',
  web_search:            '网络搜索',
  get_patient_brief:     '生成患者摘要',
  get_plan_delta_suggestion: '方案调整建议',
  get_followup_focus:    '随访重点',
  get_recall_script:     '生成召回话术',
};

// ─── 状态 ───────────────────────────────────────────────────────────────────

let serverUrl = DEFAULT_SERVER;
let apiKey = '';
let baseUrl = '';
let modelName = '';
let currentPatient = null;   // { archive_id, name, patient_no }
let currentRisk = null;
let isPinned = false;
let chatAbortCtrl = null;
let pendingImage = null;     // { data: base64, mediaType: 'image/jpeg' }

// ─── DOM 引用 ────────────────────────────────────────────────────────────────

const searchInput   = document.getElementById('search-input');
const searchBtn     = document.getElementById('search-btn');
const searchResult  = document.getElementById('search-result');
const analysisPanel = document.getElementById('analysis-panel');
const chatMessages  = document.getElementById('chat-messages');
const chatInput     = document.getElementById('chat-input');
const chatSendBtn   = document.getElementById('chat-send-btn');
const imgInput      = document.getElementById('img-input');
const chatContext   = document.getElementById('chat-context');
const chatContextText = document.getElementById('chat-context-text');
const pinBtn        = document.getElementById('pin-btn');
const miniBtn       = document.getElementById('mini-btn');
const closeBtn      = document.getElementById('close-btn');
const saveSettingsBtn = document.getElementById('save-settings-btn');
const saveResult    = document.getElementById('save-result');
const openPlatformBtn = document.getElementById('open-platform-btn');
const setServer     = document.getElementById('set-server');
const setApikey     = document.getElementById('set-apikey');
const setBaseurl    = document.getElementById('set-baseurl');
const setModel      = document.getElementById('set-model');
const setParams     = document.getElementById('set-params');

// ─── 初始化 ──────────────────────────────────────────────────────────────────

async function init() {
  const stored = await storage.get([
    'serverUrl', 'paramNames', 'anthropicApiKey', 'braveSearchKey',
    'claudeBaseUrl', 'claudeModel', 'alwaysOnTop',
  ]);

  serverUrl  = stored.serverUrl  || DEFAULT_SERVER;
  apiKey     = stored.anthropicApiKey || '';
  baseUrl    = stored.claudeBaseUrl   || '';
  modelName  = stored.claudeModel     || '';
  isPinned   = stored.alwaysOnTop     || false;

  // 填充设置页
  setServer.value  = serverUrl;
  setApikey.value  = apiKey;
  setBaseurl.value = baseUrl;
  setModel.value   = modelName;
  setParams.value  = stored.paramNames || DEFAULT_PARAMS;

  if (isPinned) pinBtn.classList.add('pinned');
  window.electronAPI.setAlwaysOnTop(isPinned);
}

// ─── 页签切换 ────────────────────────────────────────────────────────────────

document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.tab;
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(target + '-page').classList.add('active');
  });
});

// ─── 标题栏按钮 ──────────────────────────────────────────────────────────────

pinBtn.addEventListener('click', () => {
  isPinned = !isPinned;
  pinBtn.classList.toggle('pinned', isPinned);
  window.electronAPI.setAlwaysOnTop(isPinned);
  storage.set({ alwaysOnTop: isPinned });
});
miniBtn.addEventListener('click',  () => window.electronAPI.minimize());
closeBtn.addEventListener('click', () => window.electronAPI.hide());

// ─── API 工具函数 ────────────────────────────────────────────────────────────

async function apiFetch(path, opts = {}) {
  const url = serverUrl.replace(/\/$/, '') + path;
  const resp = await fetch(url, {
    credentials: 'include',
    headers: { Accept: 'application/json', ...opts.headers },
    ...opts,
  });
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

async function searchPatientApi(keyword) {
  const data = await apiFetch(`/tools/plugin/patient/search?query=${encodeURIComponent(keyword)}&page_size=20`);
  return Array.isArray(data) ? data : (data.items || data.records || []);
}

async function getRiskResult(archive_id) {
  return apiFetch(`/tools/risk/result/${archive_id}`);
}

async function getPatientProfile(patient_id) {
  return apiFetch(`/tools/plugin/patient/${patient_id}/profile`);
}

async function getPatientMetrics(patient_id, range = 90) {
  return apiFetch(`/tools/plugin/patient/${patient_id}/metrics?range=${range}`);
}

async function getRiskTags(patient_id) {
  return apiFetch(`/tools/plugin/patient/${patient_id}/risk-tags`);
}

async function getCurrentPlan(patient_id) {
  return apiFetch(`/tools/plugin/plan/current/${patient_id}`);
}

async function triggerAnalyze(archive_id) {
  return apiFetch(`/tools/risk/analyze/${archive_id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
}

// ─── 患者搜索 ────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function getRiskBadge(level) {
  const l = (level || '').toUpperCase();
  if (l === 'HIGH')   return { cls: 'badge-high',   text: '高风险' };
  if (l === 'MEDIUM') return { cls: 'badge-medium', text: '中风险' };
  if (l === 'LOW')    return { cls: 'badge-low',    text: '低风险' };
  return { cls: 'badge-unknown', text: level || '待分析' };
}

searchBtn.addEventListener('click', doSearch);
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });

async function doSearch() {
  const keyword = searchInput.value.trim();
  if (!keyword) {
    searchResult.innerHTML = '<div class="err-msg">请输入患者姓名、手机号或档案号</div>';
    return;
  }
  searchBtn.disabled = true;
  searchBtn.textContent = '搜索中…';
  searchResult.innerHTML = '<div class="loading-wrap"><div class="spinner"></div><span>搜索患者…</span></div>';
  analysisPanel.style.display = 'none';

  try {
    const list = await searchPatientApi(keyword);
    if (!list.length) {
      searchResult.innerHTML = '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>未找到患者，请确认已登录平台</div>';
    } else {
      renderPatientList(list);
    }
  } catch (err) {
    searchResult.innerHTML = `<div class="err-msg">搜索失败：${esc(err.message)}</div>`;
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = '搜索';
  }
}

function renderPatientList(list) {
  const html = list.map(p => {
    const name = esc(p.name || '未知');
    const no   = esc(p.patient_no || p.archive_no || '');
    const id   = esc(p.patient_id || p.id || '');
    const tags = (p.tags || []).slice(0, 3).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    return `
      <div class="patient-card" data-id="${id}" data-name="${name}" data-no="${no}">
        <div class="pc-name">${name}</div>
        <div class="pc-meta">档案号：${no || '—'} &nbsp;|&nbsp; ID：${id}</div>
        ${tags ? `<div class="pc-tags">${tags}</div>` : ''}
      </div>`;
  }).join('');
  searchResult.innerHTML = `<div class="patient-list">${html}</div>`;

  searchResult.querySelectorAll('.patient-card').forEach(card => {
    card.addEventListener('click', () => {
      searchResult.querySelectorAll('.patient-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      selectPatient({
        archive_id: card.dataset.id,
        name: card.dataset.name,
        patient_no: card.dataset.no,
      });
    });
  });
}

async function selectPatient(patient) {
  currentPatient = patient;
  updateChatContext();

  analysisPanel.style.display = 'block';
  analysisPanel.innerHTML = '<div class="loading-wrap"><div class="spinner"></div><span>加载患者数据…</span></div>';

  try {
    // 并行加载风险/档案/指标
    const [risk, profile, metrics, tags, plan] = await Promise.allSettled([
      getRiskResult(patient.archive_id),
      getPatientProfile(patient.archive_id),
      getPatientMetrics(patient.archive_id),
      getRiskTags(patient.archive_id),
      getCurrentPlan(patient.archive_id),
    ]);

    currentRisk = risk.status === 'fulfilled' ? risk.value : null;
    const profileData  = profile.status  === 'fulfilled' ? profile.value  : null;
    const metricsData  = metrics.status  === 'fulfilled' ? metrics.value  : null;
    const tagsData     = tags.status     === 'fulfilled' ? tags.value     : null;
    const planData     = plan.status     === 'fulfilled' ? plan.value     : null;

    renderAnalysis(patient, currentRisk, profileData, metricsData, tagsData, planData);

    // 后台异步触发新一轮分析
    triggerAnalyze(patient.archive_id).catch(() => {});
  } catch (err) {
    analysisPanel.innerHTML = `<div class="err-msg">加载失败：${esc(err.message)}</div>`;
  }
}

function renderAnalysis(patient, risk, profile, metrics, tags, plan) {
  const badge = getRiskBadge(risk?.risk_level);
  const mainSyndrome = esc(risk?.main_syndrome || '待评估');
  const summary = esc(risk?.ai_summary || risk?.analysis_summary || '');

  // 健康指标
  let metricsHtml = '';
  if (metrics && Array.isArray(metrics) && metrics.length) {
    const latest = {};
    metrics.forEach(m => {
      if (!latest[m.indicator_type]) latest[m.indicator_type] = m;
    });
    const TYPE_MAP = { BLOOD_PRESSURE: '血压', BLOOD_GLUCOSE: '血糖', WEIGHT: '体重', WAIST: '腰围' };
    const items = Object.entries(latest).map(([type, m]) => {
      const label = TYPE_MAP[type] || type;
      let val = '';
      if (type === 'BLOOD_PRESSURE') val = `${m.systolic ?? '—'}/${m.diastolic ?? '—'} <span class="metric-unit">mmHg</span>`;
      else if (type === 'BLOOD_GLUCOSE') val = `${m.value ?? '—'} <span class="metric-unit">mmol/L</span>`;
      else if (type === 'WEIGHT') val = `${m.value ?? '—'} <span class="metric-unit">kg</span>`;
      else val = `${m.value ?? '—'}`;
      return `<div class="metric-item"><div class="metric-label">${label}</div><div class="metric-value">${val}</div></div>`;
    });
    if (items.length) {
      metricsHtml = `
        <div class="section-card">
          <div class="section-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            近期健康指标
          </div>
          <div class="metric-grid">${items.join('')}</div>
        </div>`;
    }
  }

  // 风险标签
  let tagsHtml = '';
  if (tags && Array.isArray(tags) && tags.length) {
    const tagItems = tags.slice(0, 6).map(t => {
      const sev = (t.severity || '').toUpperCase();
      const cls = sev === 'HIGH' ? 'risk-high' : sev === 'MEDIUM' ? 'risk-medium' : 'risk-low';
      return `<span class="tag ${cls}">${esc(t.tag_name || t.name || t)}</span>`;
    }).join('');
    tagsHtml = `
      <div class="section-card">
        <div class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
          风险标签
        </div>
        <div class="pc-tags">${tagItems}</div>
      </div>`;
  }

  // 当前方案
  let planHtml = '';
  if (plan && plan.title) {
    const statusMap = {
      DRAFT:'草稿', PUBLISHED:'已发布', ISSUED:'已下达', IN_PROGRESS:'进行中',
      COMPLETED:'已完结', ARCHIVED:'已归档',
    };
    const statusText = statusMap[plan.status] || plan.status || '';
    planHtml = `
      <div class="section-card">
        <div class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          当前方案
        </div>
        <div class="plan-title">${esc(plan.title)}</div>
        <div class="plan-meta">${esc(plan.syndrome || '')} ${statusText ? '· ' + statusText : ''}</div>
      </div>`;
  }

  // 档案信息
  let profileHtml = '';
  if (profile) {
    const age  = profile.age  ? `${profile.age}岁` : '';
    const gender = profile.gender === 'MALE' ? '男' : profile.gender === 'FEMALE' ? '女' : '';
    const disease = profile.disease_type || profile.chronic_diseases?.join(', ') || '';
    const constitution = profile.main_constitution || profile.constitution_type || '';
    profileHtml = `
      <div class="section-card">
        <div class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>
          患者信息
        </div>
        <div style="font-size:12px;line-height:1.8;color:#3A3530">
          ${age || gender ? `<div><span style="color:#7A7268">基本：</span>${[age, gender].filter(Boolean).join('，')}</div>` : ''}
          ${disease ? `<div><span style="color:#7A7268">慢病：</span>${esc(disease)}</div>` : ''}
          ${constitution ? `<div><span style="color:#7A7268">体质：</span>${esc(constitution)}</div>` : ''}
        </div>
      </div>`;
  }

  // AI 摘要
  let summaryHtml = '';
  if (summary) {
    summaryHtml = `
      <div class="section-card">
        <div class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/></svg>
          AI 风险摘要
        </div>
        <div class="ai-summary">${summary}</div>
      </div>`;
  }

  // 操作按钮
  const actionHtml = `
    <div style="display:flex;gap:8px;margin-top:4px">
      <button class="btn btn-primary" style="flex:1;justify-content:center" id="chat-about-btn">
        与 AI 讨论此患者
      </button>
      <button class="btn btn-ghost btn-sm" id="open-detail-btn">
        打开平台 ↗
      </button>
    </div>`;

  analysisPanel.innerHTML = `
    <div class="analysis-header">
      <div class="patient-name-big">${esc(patient.name)}</div>
      <span class="badge ${badge.cls}">${badge.text}</span>
    </div>
    <div style="font-size:12px;color:#7A7268;margin-bottom:12px">
      主证：${mainSyndrome}
      ${patient.patient_no ? '&nbsp;·&nbsp; 档案号：' + esc(patient.patient_no) : ''}
    </div>
    ${profileHtml}
    ${metricsHtml}
    ${tagsHtml}
    ${summaryHtml}
    ${planHtml}
    ${actionHtml}
  `;

  document.getElementById('chat-about-btn')?.addEventListener('click', () => {
    // 切换到 AI 对话页
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelector('[data-tab="chat"]').classList.add('active');
    document.getElementById('chat-page').classList.add('active');
    // 预填问题
    chatInput.value = `请分析${patient.name}的整体健康状况，给出调护建议。`;
    chatInput.focus();
  });

  document.getElementById('open-detail-btn')?.addEventListener('click', () => {
    window.electronAPI.openExternal(`${serverUrl}/gui/admin/risk/plan?patient_id=${encodeURIComponent(patient.archive_id)}`);
  });
}

function updateChatContext() {
  if (currentPatient) {
    chatContext.style.display = 'flex';
    chatContextText.textContent = `当前患者：${currentPatient.name}（${currentPatient.archive_id}）`;
  } else {
    chatContext.style.display = 'none';
  }
}

// ─── AI 对话（SSE 后端代理）───────────────────────────────────────────────────

chatSendBtn.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.ctrlKey) sendChat();
});

imgInput.addEventListener('change', async () => {
  const file = imgInput.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    const dataUrl = ev.target.result;
    const [header, data] = dataUrl.split(',');
    const mediaType = header.match(/:(.*?);/)?.[1] || 'image/jpeg';
    pendingImage = { data, mediaType };
    appendBubble('ai', `📎 图片已附加（${file.name}），发送消息时将一并提交。`, false);
  };
  reader.readAsDataURL(file);
  imgInput.value = '';
});

function appendBubble(role, text, isMarkdown = false) {
  const div = document.createElement('div');
  div.className = `chat-bubble ${role}`;
  if (isMarkdown && role === 'ai') {
    div.classList.add('md-content');
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function appendToolCall(toolName) {
  const label = TOOL_LABELS[toolName] || toolName;
  const div = document.createElement('div');
  div.className = 'chat-bubble tool-call';
  div.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline;vertical-align:middle;margin-right:4px"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>调用工具：${label}…`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

async function sendChat() {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = '';

  appendBubble('user', text + (pendingImage ? ' [图片]' : ''));
  chatSendBtn.disabled = true;

  const thinkingBubble = appendBubble('ai', '正在思考…');
  thinkingBubble.classList.add('thinking');

  let toolCallBubble = null;
  let aiTextBubble   = null;

  try {
    const resp = await fetch(serverUrl.replace(/\/$/, '') + AGENT_SSE_PATH, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: text,
        patient_id:   currentPatient?.archive_id || null,
        patient_name: currentPatient?.name       || null,
        image_data:   pendingImage || null,
      }),
    });

    pendingImage = null;

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || err.message || `HTTP ${resp.status}`);
    }

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    thinkingBubble.textContent = '思考中…';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch { continue; }

        switch (evt.type) {
          case 'thinking':
            thinkingBubble.textContent = '思考中…';
            break;

          case 'tool_call':
            thinkingBubble.remove();
            toolCallBubble = appendToolCall(evt.tool || evt.toolName);
            break;

          case 'tool_done':
            if (toolCallBubble) {
              toolCallBubble.innerHTML = toolCallBubble.innerHTML.replace('…', ' ✓');
            }
            toolCallBubble = null;
            break;

          case 'done': {
            thinkingBubble.remove();
            if (toolCallBubble) toolCallBubble.remove();
            const finalText = evt.message || '';
            appendBubble('ai', finalText, true);
            break;
          }

          case 'error':
            thinkingBubble.remove();
            appendBubble('ai', `⚠️ ${evt.message || '出错了'}`);
            break;
        }
      }
    }

  } catch (err) {
    thinkingBubble.remove();
    appendBubble('ai', `连接失败：${err.message}\n\n请确认：\n1. 平台服务已启动（${serverUrl}）\n2. 已用浏览器登录平台\n3. 设置页中的服务器地址正确`);
  } finally {
    chatSendBtn.disabled = false;
  }
}

// ─── 简单 Markdown 渲染 ──────────────────────────────────────────────────────

function renderMarkdown(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 标题
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm,  '<h2>$1</h2>')
    .replace(/^# (.+)$/gm,   '<h1>$1</h1>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // 分割线
    .replace(/^---$/gm, '<hr>')
    // 无序列表（合并为 ul）
    .replace(/((?:^- .+\n?)+)/gm, (m) => {
      const items = m.trim().split('\n').map(l => `<li>${l.slice(2)}</li>`).join('');
      return `<ul>${items}</ul>`;
    })
    // 有序列表
    .replace(/((?:^\d+\. .+\n?)+)/gm, (m) => {
      const items = m.trim().split('\n').map(l => `<li>${l.replace(/^\d+\. /, '')}</li>`).join('');
      return `<ol>${items}</ol>`;
    })
    // 引用
    .replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')
    // 段落（双换行）
    .replace(/\n\n/g, '</p><p>')
    // 单换行
    .replace(/\n/g, '<br>');
}

// ─── 设置页 ──────────────────────────────────────────────────────────────────

saveSettingsBtn.addEventListener('click', async () => {
  const newServer  = setServer.value.trim().replace(/\/$/, '') || DEFAULT_SERVER;
  const newApiKey  = setApikey.value.trim();
  const newBaseUrl = setBaseurl.value.trim().replace(/\/$/, '');
  const newModel   = setModel.value.trim();
  const newParams  = setParams.value.trim() || DEFAULT_PARAMS;

  try { new URL(newServer); } catch (_) {
    saveResult.textContent = '服务器地址格式不正确，请含 http:// 或 https://';
    saveResult.className = 'save-result fail';
    return;
  }

  saveSettingsBtn.disabled = true;
  saveSettingsBtn.textContent = '保存中…';
  saveResult.textContent = '';

  await storage.set({
    serverUrl: newServer,
    anthropicApiKey: newApiKey,
    claudeBaseUrl: newBaseUrl,
    claudeModel: newModel,
    paramNames: newParams,
  });

  serverUrl = newServer;
  apiKey    = newApiKey;
  baseUrl   = newBaseUrl;
  modelName = newModel;

  // 测试连接
  try {
    const resp = await fetch(`${newServer}/healthz`, { credentials: 'include', signal: AbortSignal.timeout(4000) });
    if (resp.ok) {
      saveResult.textContent = '配置已保存，服务器连接正常 ✓';
      saveResult.className = 'save-result ok';
    } else {
      saveResult.textContent = '配置已保存，但服务器返回异常（请确认已登录）';
      saveResult.className = 'save-result fail';
    }
  } catch (_) {
    saveResult.textContent = '配置已保存，但无法连接服务器（请确认已启动）';
    saveResult.className = 'save-result fail';
  }

  saveSettingsBtn.disabled = false;
  saveSettingsBtn.textContent = '保存配置';
});

openPlatformBtn.addEventListener('click', () => {
  window.electronAPI.openExternal(serverUrl || DEFAULT_SERVER);
});

// ─── 启动 ────────────────────────────────────────────────────────────────────

init().catch(console.error);
