/**
 * content.js - 诊中助手内容脚本 v3.0
 * 四Tab：患者档案 | 当前风险 | 方案管理 | 随访指标
 * 实现 A-E 插件规范
 */

(function () {
  'use strict';

  if (window.__tcmAssistantInjected) return;
  window.__tcmAssistantInjected = true;

  const SIDEBAR_ID = 'tcm-assistant-sidebar';
  const DEBOUNCE_MS = 600;
  const DEFAULT_PARAM_NAMES = ['patient_id', 'pid', 'id', 'patientId', 'patient'];

  // 状态
  let currentPatientId = null;
  let currentPatient   = null;  // { archive_id, name, patient_no }
  let currentContext   = null;  // A: { patient_id, visit_id, doctor_id, ... }
  let currentRisk      = null;
  let currentProfile   = null;  // B: 患者详情
  let currentMetrics   = null;  // B: 健康指标
  let currentRiskTags  = null;  // B: 风险标签
  let currentPlanVersions = null; // C: 方案版本列表
  let isCollapsed = false;
  let activeTab   = 'patient';
  let debounceTimer = null;
  let confirmPending  = null;
  let serverUrl = 'http://localhost:8010';

  // ─── 配置 ───────────────────────────────────────────────────────────────────

  function getConfig() {
    return new Promise((resolve) => {
      chrome.storage.local.get(['serverUrl', 'paramNames', 'sidebarCollapsed'], (r) => {
        const url = r.serverUrl || 'http://localhost:8010';
        serverUrl = url;
        resolve({
          serverUrl: url,
          paramNames: r.paramNames
            ? r.paramNames.split(',').map(s => s.trim()).filter(Boolean)
            : DEFAULT_PARAM_NAMES,
          sidebarCollapsed: r.sidebarCollapsed !== undefined ? r.sidebarCollapsed : true
        });
      });
    });
  }

  function extractPatientId(paramNames) {
    const url = new URL(window.location.href);
    for (const name of paramNames) {
      const val = url.searchParams.get(name);
      if (val && val.trim()) return val.trim();
    }
    const hashParams = new URLSearchParams(window.location.hash.replace(/^#\/?/, ''));
    for (const name of paramNames) {
      const val = hashParams.get(name);
      if (val && val.trim()) return val.trim();
    }
    return null;
  }

  // ─── 工具 ───────────────────────────────────────────────────────────────────

  function esc(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function getRiskBadge(level) {
    const l = (level || '').toUpperCase();
    if (l === 'HIGH')   return { cls: 'tcm-badge-high',    text: '高风险' };
    if (l === 'MEDIUM') return { cls: 'tcm-badge-medium',  text: '中风险' };
    if (l === 'LOW')    return { cls: 'tcm-badge-low',     text: '低风险' };
    return { cls: 'tcm-badge-unknown', text: level || '未知' };
  }

  function getSevColor(sev) {
    if (sev === 'HIGH')   return '#dc2626';
    if (sev === 'MEDIUM') return '#d97706';
    return '#6b7280';
  }

  const PLAN_STATES = {
    DRAFT:       { label: '草稿',   color: '#9ca3af', icon: '✏️' },
    PUBLISHED:   { label: '已发布', color: '#16a34a', icon: '✅' },
    ISSUED:      { label: '已下达', color: '#3b82f6', icon: '📋' },
    IN_PROGRESS: { label: '进行中', color: '#d97706', icon: '⏳' },
    FOLLOWED_UP: { label: '已随访', color: '#8b5cf6', icon: '📞' },
    RE_ASSESSED: { label: '已复评', color: '#0891b2', icon: '🔄' },
    COMPLETED:   { label: '已完结', color: '#16a34a', icon: '✅' },
    ADJUSTED:    { label: '已调整', color: '#ea580c', icon: '✏️' },
  };

  function msg(action, payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ action, ...payload }, (resp) => {
        if (chrome.runtime.lastError) resolve({ success: false, error: chrome.runtime.lastError.message });
        else resolve(resp);
      });
    });
  }

  // ─── 侧边栏骨架 ─────────────────────────────────────────────────────────────

  function createSidebar() {
    if (document.getElementById(SIDEBAR_ID)) return;

    const sidebar = document.createElement('div');
    sidebar.id = SIDEBAR_ID;
    sidebar.className = 'tcm-sidebar';
    sidebar.innerHTML = `
      <div class="tcm-sidebar-inner">
        <div class="tcm-header">
          <div class="tcm-header-left">
            <span class="tcm-logo">🌿</span>
            <span class="tcm-title">诊中助手</span>
          </div>
          <button class="tcm-collapse-btn" id="tcm-collapse-btn" title="收起">◀</button>
        </div>
        <div class="tcm-tabs" id="tcm-tabs">
          <button class="tcm-tab tcm-tab-active" data-tab="patient">患者</button>
          <button class="tcm-tab" data-tab="risk">风险</button>
          <button class="tcm-tab" data-tab="plan">方案</button>
          <button class="tcm-tab" data-tab="followup">随访</button>
        </div>
        <div class="tcm-content" id="tcm-content">
          <div class="tcm-idle">
            <div class="tcm-idle-icon">🔍</div>
            <p>等待检测患者信息…</p>
            <p class="tcm-hint">请在HIS系统中打开含患者ID参数的页面</p>
          </div>
        </div>
      </div>
      <div class="tcm-collapsed-bar" id="tcm-collapsed-bar">
        <span class="tcm-expand-arrow">▶</span>
        <span class="tcm-collapsed-label">诊中</span>
      </div>
      <div class="tcm-confirm-overlay" id="tcm-confirm-overlay" style="display:none;">
        <div class="tcm-confirm-box">
          <div class="tcm-confirm-title">确认下达方案</div>
          <div class="tcm-confirm-body" id="tcm-confirm-body"></div>
          <div class="tcm-confirm-followup">
            <label class="tcm-confirm-followup-label">
              <input type="checkbox" id="tcm-followup-check" checked>
              <span>自动创建随访提醒</span>
            </label>
            <div id="tcm-followup-days-row" style="margin-top:6px;display:flex;align-items:center;gap:6px;font-size:12px;">
              <span>随访时间：</span>
              <select id="tcm-followup-days" class="tcm-select">
                <option value="3">3天后</option>
                <option value="7" selected>7天后</option>
                <option value="14">14天后</option>
                <option value="30">30天后</option>
              </select>
            </div>
          </div>
          <div class="tcm-confirm-actions">
            <button class="tcm-btn tcm-btn-secondary" id="tcm-confirm-cancel">取消</button>
            <button class="tcm-btn tcm-btn-primary" id="tcm-confirm-ok">确认下达</button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(sidebar);

    document.querySelectorAll('.tcm-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        activeTab = btn.dataset.tab;
        document.querySelectorAll('.tcm-tab').forEach(b => b.classList.remove('tcm-tab-active'));
        btn.classList.add('tcm-tab-active');
        renderActiveTab();
      });
    });

    document.getElementById('tcm-collapse-btn').addEventListener('click', toggleSidebar);
    document.getElementById('tcm-collapsed-bar').addEventListener('click', toggleSidebar);
    document.getElementById('tcm-confirm-cancel').addEventListener('click', closeConfirm);
    document.getElementById('tcm-confirm-ok').addEventListener('click', doIssue);
    document.getElementById('tcm-followup-check').addEventListener('change', (e) => {
      document.getElementById('tcm-followup-days-row').style.display = e.target.checked ? 'flex' : 'none';
    });
  }

  function toggleSidebar() {
    isCollapsed = !isCollapsed;
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (!sidebar) return;
    if (isCollapsed) sidebar.classList.add('tcm-collapsed');
    else sidebar.classList.remove('tcm-collapsed');
    chrome.storage.local.set({ sidebarCollapsed: isCollapsed });
  }

  // ─── Tab 调度 ───────────────────────────────────────────────────────────────

  function renderActiveTab() {
    if (!currentPatient) return;
    if (activeTab === 'patient')  renderPatientTab();
    else if (activeTab === 'risk') renderRiskTab();
    else if (activeTab === 'plan') renderPlanTab();
    else renderFollowupTab();
  }

  // ─── Tab 1: 患者档案 (B) ────────────────────────────────────────────────────

  async function renderPatientTab() {
    const c = document.getElementById('tcm-content');
    if (!c) return;

    const patient = currentPatient;
    c.innerHTML = `<div class="tcm-loading"><div class="tcm-spinner"></div><p>加载患者档案…</p></div>`;

    // 并行加载 profile + risk-tags
    if (!currentProfile || !currentRiskTags) {
      const [pResp, tResp] = await Promise.all([
        msg('getPatientProfile', { patient_id: patient.archive_id }),
        msg('getRiskTags',       { patient_id: patient.archive_id }),
      ]);
      if (pResp?.success) currentProfile  = pResp.data;
      if (tResp?.success) currentRiskTags = tResp.data;
    }

    const p = currentProfile || {};
    const tags = Array.isArray(currentRiskTags) ? currentRiskTags
                 : (currentRiskTags?.tags || []);

    const tagHtml = tags.length
      ? tags.map(t => `<span class="tcm-tag" style="background:${esc(t.color||'#e5e7eb')};color:${esc(t.text_color||'#374151')}">${esc(t.name||t)}</span>`).join('')
      : '<span class="tcm-hint">暂无风险标签</span>';

    const constitutionHtml = p.constitution_type
      ? `<div class="tcm-profile-row"><span class="tcm-profile-label">体质</span><span class="tcm-profile-val tcm-badge-constitution">${esc(p.constitution_type)}</span></div>`
      : '';

    const diseasesHtml = Array.isArray(p.chronic_diseases) && p.chronic_diseases.length
      ? `<div class="tcm-profile-row"><span class="tcm-profile-label">慢病</span><span class="tcm-profile-val">${p.chronic_diseases.map(d => esc(d)).join('、')}</span></div>`
      : '';

    const bmiHtml = p.bmi
      ? `<div class="tcm-profile-row"><span class="tcm-profile-label">BMI</span><span class="tcm-profile-val">${esc(String(p.bmi))}</span></div>`
      : '';

    c.innerHTML = `
      <div class="tcm-patient-card">
        <div class="tcm-patient-name">${esc(patient.name)}</div>
        ${patient.patient_no ? `<div class="tcm-patient-no">档案号：${esc(patient.patient_no)}</div>` : ''}
        ${p.gender || p.age ? `<div class="tcm-patient-meta">${p.gender ? esc(p.gender==='M'?'男':'女') : ''}${p.age ? ' · '+esc(String(p.age))+'岁' : ''}</div>` : ''}
      </div>
      ${constitutionHtml || diseasesHtml || bmiHtml ? `
      <div class="tcm-section">
        <div class="tcm-section-title">基本信息</div>
        ${constitutionHtml}${diseasesHtml}${bmiHtml}
        ${p.smoking !== undefined ? `<div class="tcm-profile-row"><span class="tcm-profile-label">吸烟</span><span class="tcm-profile-val">${p.smoking ? '是' : '否'}</span></div>` : ''}
        ${p.exercise !== undefined ? `<div class="tcm-profile-row"><span class="tcm-profile-label">运动</span><span class="tcm-profile-val">${p.exercise || '-'}</span></div>` : ''}
      </div>` : ''}
      <div class="tcm-section">
        <div class="tcm-section-title">风险标签</div>
        <div class="tcm-tag-list">${tagHtml}</div>
      </div>
      ${currentContext?.visit_id ? `
      <div class="tcm-section">
        <div class="tcm-section-title">就诊上下文</div>
        <div class="tcm-profile-row"><span class="tcm-profile-label">就诊ID</span><span class="tcm-profile-val">${esc(currentContext.visit_id)}</span></div>
        ${currentContext.his_page_type ? `<div class="tcm-profile-row"><span class="tcm-profile-label">页面类型</span><span class="tcm-profile-val">${esc(currentContext.his_page_type)}</span></div>` : ''}
      </div>` : ''}
      <div class="tcm-actions">
        <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-load-metrics-btn">查看健康指标</button>
        <a class="tcm-btn tcm-btn-secondary tcm-btn-sm" href="${serverUrl}/gui/admin/archive/archives" target="_blank">完整档案 ↗</a>
      </div>
      <div id="tcm-metrics-panel"></div>
    `;

    document.getElementById('tcm-load-metrics-btn')?.addEventListener('click', loadMetricsPanel);
  }

  async function loadMetricsPanel() {
    const panel = document.getElementById('tcm-metrics-panel');
    if (!panel) return;
    panel.innerHTML = '<div class="tcm-loading-sm">加载中…</div>';

    if (!currentMetrics) {
      const resp = await msg('getPatientMetrics', { patient_id: currentPatient.archive_id, range: 90 });
      if (resp?.success) currentMetrics = resp.data;
    }

    const m = currentMetrics || {};
    const indicators = Array.isArray(m.indicators) ? m.indicators : (Array.isArray(m) ? m : []);
    if (!indicators.length) {
      panel.innerHTML = '<div class="tcm-section"><p class="tcm-hint">近90天暂无健康指标记录</p></div>';
      return;
    }

    const rows = indicators.slice(0, 8).map(ind => `
      <div class="tcm-metric-row-sm">
        <span class="tcm-metric-name-sm">${esc(ind.name||ind.indicator_name)}</span>
        <span class="tcm-metric-val-sm" style="color:${ind.abnormal?'#dc2626':'#374151'}">${esc(String(ind.latest_value||ind.value||'-'))} ${esc(ind.unit||'')}</span>
        <span class="tcm-metric-date-sm">${esc((ind.date||ind.measured_at||'').slice(0,10))}</span>
      </div>`).join('');

    panel.innerHTML = `<div class="tcm-section"><div class="tcm-section-title">近90天健康指标</div>${rows}</div>`;
  }

  // ─── Tab 2: 当前风险 ─────────────────────────────────────────────────────────

  function renderLoading(patientId) {
    const c = document.getElementById('tcm-content');
    if (!c) return;
    c.innerHTML = `<div class="tcm-loading"><div class="tcm-spinner"></div><p>正在识别 <strong>${esc(patientId)}</strong></p><p class="tcm-hint">AI风险分析中…</p></div>`;
  }

  function renderError(message) {
    const c = document.getElementById('tcm-content');
    if (!c) return;
    c.innerHTML = `<div class="tcm-error"><div class="tcm-error-icon">⚠️</div><p class="tcm-error-msg">${esc(message)}</p><p class="tcm-hint">请确认已登录治未病平台，且患者档案存在</p><button class="tcm-btn tcm-btn-retry" id="tcm-retry-btn">重新检测</button></div>`;
    document.getElementById('tcm-retry-btn')?.addEventListener('click', () => { currentPatientId = null; checkUrl(); });
  }

  function renderRiskTab() {
    const c = document.getElementById('tcm-content');
    if (!c) return;
    const patient = currentPatient;
    const risk = currentRisk;

    if (!risk) {
      c.innerHTML = `<div style="padding:16px"><div class="tcm-patient-card"><div class="tcm-patient-name">${esc(patient.name)}</div><span class="tcm-badge tcm-badge-unknown">暂无评估</span></div><p class="tcm-hint" style="margin-top:12px">暂无风险评估，请先完成体质/健康评估</p></div>`;
      return;
    }

    const { cls, text } = getRiskBadge(risk.risk_level);
    const evidence = risk.risk_evidence || [];
    const factors  = risk.risk_factors  || [];
    const summary  = (risk.raw_summary || '').slice(0, 150);

    const evidenceHtml = evidence.length > 0
      ? evidence.map((ev, i) => `
          <div class="tcm-ev-item">
            <div class="tcm-ev-header" onclick="(function(el){el.classList.toggle('tcm-ev-open')})(document.getElementById('tcm-evb-${i}'))">
              <span class="tcm-ev-dot" style="background:${getSevColor(ev.severity)}"></span>
              <span class="tcm-ev-factor">${esc(ev.factor)}</span>
              <span class="tcm-ev-arrow">▾</span>
            </div>
            <div class="tcm-ev-body" id="tcm-evb-${i}">
              <table class="tcm-ev-table">
                <tr><td>检测值</td><td><strong>${esc(ev.value)}</strong></td></tr>
                <tr><td>参考范围</td><td>${esc(ev.reference)}</td></tr>
                <tr><td>来源</td><td>${esc(ev.source)}</td></tr>
                ${ev.date ? `<tr><td>日期</td><td>${esc(ev.date)}</td></tr>` : ''}
              </table>
            </div>
          </div>`).join('')
      : factors.map(f => `<div class="tcm-factor-plain">• ${esc(f)}</div>`).join('');

    c.innerHTML = `
      <div class="tcm-patient-card">
        <div class="tcm-patient-name">${esc(patient.name)}</div>
        ${patient.patient_no ? `<div class="tcm-patient-no">档案号：${esc(patient.patient_no)}</div>` : ''}
        <span class="tcm-badge ${cls}">${text}</span>
      </div>
      <div class="tcm-section">
        <div class="tcm-section-title">风险证据 ${evidence.length > 0 ? '<span class="tcm-hint">点击展开溯源</span>' : ''}</div>
        <div class="tcm-ev-list">${evidenceHtml}</div>
      </div>
      ${summary ? `<div class="tcm-section"><div class="tcm-section-title">AI摘要</div><div class="tcm-summary">${esc(summary)}${(risk.raw_summary||'').length > 150 ? '…' : ''}</div></div>` : ''}
      <div class="tcm-actions">
        <button class="tcm-btn tcm-btn-primary" id="tcm-issue-btn"
          data-archive-id="${esc(String(patient.archive_id))}"
          data-plan="${esc(risk.suggested_tcm_plan || risk.raw_summary || '')}">
          ⚡ 确认下达方案
        </button>
        <a class="tcm-btn tcm-btn-secondary" href="${serverUrl}/gui/admin/risk/plan" target="_blank">完整分析 ↗</a>
      </div>`;

    document.getElementById('tcm-issue-btn')?.addEventListener('click', (e) => {
      const btn = e.currentTarget;
      confirmPending = {
        archive_id: btn.dataset.archiveId,
        plan_title: `AI风险调理方案（${new Date().toLocaleDateString('zh-CN')}）`,
        plan_content: btn.dataset.plan || '中医调理综合方案',
      };
      const body = document.getElementById('tcm-confirm-body');
      if (body) {
        const prev = confirmPending.plan_content;
        body.innerHTML = `<div class="tcm-confirm-patient">患者：<strong>${esc(patient.name)}</strong></div><div class="tcm-confirm-plan-preview">${esc(prev.slice(0,120))}${prev.length > 120 ? '…' : ''}</div>`;
      }
      const overlay = document.getElementById('tcm-confirm-overlay');
      if (overlay) overlay.style.display = 'flex';
    });
  }

  // ─── 确认弹窗 ───────────────────────────────────────────────────────────────

  function closeConfirm() {
    confirmPending = null;
    const overlay = document.getElementById('tcm-confirm-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  function doIssue() {
    if (!confirmPending) return;
    const auto_followup_days = document.getElementById('tcm-followup-check')?.checked
      ? parseInt(document.getElementById('tcm-followup-days')?.value || '7', 10)
      : 0;

    const okBtn = document.getElementById('tcm-confirm-ok');
    if (okBtn) { okBtn.textContent = '下达中…'; okBtn.disabled = true; }

    chrome.runtime.sendMessage(
      { action: 'issuePlan', ...confirmPending, auto_followup_days },
      (response) => {
        closeConfirm();
        if (okBtn) { okBtn.textContent = '确认下达'; okBtn.disabled = false; }
        if (chrome.runtime.lastError) { showToast('插件通信失败，请刷新重试', 'error'); return; }
        if (response?.success) {
          const d = response.data;
          const tip = d?.followup_date ? `，${d.followup_date} 随访提醒已创建` : '';
          showToast(`方案已下达${tip} ✓`, 'success');
          const issueBtn = document.getElementById('tcm-issue-btn');
          if (issueBtn) { issueBtn.textContent = '已下达 ✓'; issueBtn.className = 'tcm-btn tcm-btn-success'; issueBtn.disabled = true; }
        } else {
          showToast(`下达失败：${response?.error || '未知错误'}`, 'error');
        }
      }
    );
  }

  // ─── Tab 3: 方案管理 (C + D) ────────────────────────────────────────────────

  async function renderPlanTab() {
    const c = document.getElementById('tcm-content');
    if (!c) return;
    c.innerHTML = `<div class="tcm-loading"><div class="tcm-spinner"></div><p>加载方案版本…</p></div>`;

    const resp = await msg('getPlanVersions', { patient_id: currentPatient.archive_id });
    if (!resp?.success) {
      c.innerHTML = `<div class="tcm-error"><p>${esc(resp?.error || '加载失败')}</p></div>`;
      return;
    }

    const versions = Array.isArray(resp.data) ? resp.data : (resp.data?.items || []);
    currentPlanVersions = versions;

    const versionsHtml = versions.length
      ? versions.map((v, i) => {
          const st = PLAN_STATES[v.status] || { label: v.status || '未知', color: '#6b7280', icon: '•' };
          return `
            <div class="tcm-plan-card">
              <div class="tcm-plan-card-header">
                <span style="color:${st.color};font-size:12px">${st.icon} ${st.label}</span>
                <span class="tcm-plan-date">${esc((v.created_at||v.updated_at||'').slice(0,10))}</span>
              </div>
              <div class="tcm-plan-title">${esc(v.title || `方案 v${i+1}`)}</div>
              <div class="tcm-plan-preview">${esc((v.content_preview || v.summary || '').slice(0,80))}</div>
              <div class="tcm-plan-actions">
                ${v.status === 'DRAFT' ? `<button class="tcm-state-btn" data-publish-id="${esc(v.id)}">发布</button>` : ''}
                <button class="tcm-state-btn tcm-state-btn-alt" data-summary-id="${esc(v.id)}">摘要</button>
                ${i > 0 ? `<button class="tcm-state-btn tcm-state-btn-alt" data-diff-a="${esc(versions[i-1].id)}" data-diff-b="${esc(v.id)}">与上版对比</button>` : ''}
              </div>
            </div>`;
        }).join('')
      : '<div class="tcm-empty"><p>暂无方案记录</p></div>';

    c.innerHTML = `
      <div class="tcm-plan-actions-bar">
        <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-new-draft-btn">+ 新建草稿</button>
        <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-pick-template-btn">模板库</button>
      </div>
      <div id="tcm-draft-form" style="display:none;" class="tcm-section">
        <div class="tcm-section-title">新建草稿</div>
        <input type="text" id="tcm-draft-title" class="tcm-input" placeholder="方案标题" />
        <textarea id="tcm-draft-content" class="tcm-textarea" rows="4" placeholder="方案内容（中医调理方案）"></textarea>
        <div style="display:flex;gap:6px;margin-top:6px">
          <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-save-draft-btn">保存草稿</button>
          <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-cancel-draft-btn">取消</button>
        </div>
      </div>
      <div id="tcm-template-panel" style="display:none;" class="tcm-section"></div>
      <div id="tcm-diff-panel" style="display:none;" class="tcm-section"></div>
      <div id="tcm-summary-panel" style="display:none;" class="tcm-section"></div>
      <div class="tcm-plan-list">${versionsHtml}</div>
    `;

    // 新建草稿
    document.getElementById('tcm-new-draft-btn')?.addEventListener('click', () => {
      const form = document.getElementById('tcm-draft-form');
      if (form) form.style.display = form.style.display === 'none' ? 'block' : 'none';
    });

    document.getElementById('tcm-cancel-draft-btn')?.addEventListener('click', () => {
      const form = document.getElementById('tcm-draft-form');
      if (form) form.style.display = 'none';
    });

    document.getElementById('tcm-save-draft-btn')?.addEventListener('click', async () => {
      const title   = document.getElementById('tcm-draft-title')?.value.trim();
      const content = document.getElementById('tcm-draft-content')?.value.trim();
      if (!title || !content) { showToast('请填写标题和内容', 'error'); return; }

      const btn = document.getElementById('tcm-save-draft-btn');
      if (btn) { btn.textContent = '保存中…'; btn.disabled = true; }
      const r = await msg('createDraft', { body: { patient_id: currentPatient.archive_id, title, content } });
      if (btn) { btn.textContent = '保存草稿'; btn.disabled = false; }

      if (r?.success) { showToast('草稿已保存', 'success'); renderPlanTab(); }
      else showToast(`保存失败：${r?.error || ''}`, 'error');
    });

    // 模板库
    document.getElementById('tcm-pick-template-btn')?.addEventListener('click', loadTemplatePanel);

    // 版本操作（发布/摘要/对比）
    c.querySelectorAll('[data-publish-id]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const r = await msg('publishPlan', { plan_id: btn.dataset.publishId });
        if (r?.success) { showToast('已发布', 'success'); renderPlanTab(); }
        else showToast(`发布失败：${r?.error || ''}`, 'error');
      });
    });

    c.querySelectorAll('[data-summary-id]').forEach(btn => {
      btn.addEventListener('click', () => loadSummaryPanel(btn.dataset.summaryId));
    });

    c.querySelectorAll('[data-diff-a]').forEach(btn => {
      btn.addEventListener('click', () => loadDiffPanel(btn.dataset.diffA, btn.dataset.diffB));
    });
  }

  async function loadTemplatePanel() {
    const panel = document.getElementById('tcm-template-panel');
    if (!panel) return;
    panel.style.display = 'block';
    panel.innerHTML = '<div class="tcm-section-title">模板库</div><div class="tcm-loading-sm">加载中…</div>';

    const r = await msg('listTemplates', {});
    if (!r?.success) { panel.innerHTML = `<div class="tcm-section-title">模板库</div><p class="tcm-hint">${esc(r?.error || '加载失败')}</p>`; return; }

    const templates = Array.isArray(r.data) ? r.data : (r.data?.items || []);
    if (!templates.length) {
      panel.innerHTML = '<div class="tcm-section-title">模板库</div><p class="tcm-hint">暂无模板</p>';
      return;
    }

    panel.innerHTML = `
      <div class="tcm-section-title">模板库 <button class="tcm-close-panel" data-panel="tcm-template-panel">×</button></div>
      ${templates.slice(0, 10).map(t => `
        <div class="tcm-template-item" data-tpl-id="${esc(t.id)}">
          <div class="tcm-template-name">${esc(t.title || t.name)}</div>
          <div class="tcm-template-cat">${esc(t.category || '')}</div>
          <button class="tcm-state-btn" data-use-tpl-id="${esc(t.id)}">使用此模板</button>
        </div>`).join('')}
    `;

    panel.querySelector('.tcm-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });

    panel.querySelectorAll('[data-use-tpl-id]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const tResp = await msg('getTemplate', { template_id: btn.dataset.useTplId });
        if (tResp?.success) {
          const tpl = tResp.data;
          const titleEl   = document.getElementById('tcm-draft-title');
          const contentEl = document.getElementById('tcm-draft-content');
          const form      = document.getElementById('tcm-draft-form');
          if (titleEl)   titleEl.value   = tpl.title || tpl.name || '';
          if (contentEl) contentEl.value = tpl.content || tpl.body || '';
          if (form) form.style.display = 'block';
          panel.style.display = 'none';
          showToast('模板已填入', 'success');
        } else {
          showToast(`模板加载失败：${tResp?.error || ''}`, 'error');
        }
      });
    });
  }

  async function loadDiffPanel(idA, idB) {
    const panel = document.getElementById('tcm-diff-panel');
    if (!panel) return;
    panel.style.display = 'block';
    panel.innerHTML = '<div class="tcm-section-title">版本对比</div><div class="tcm-loading-sm">对比中…</div>';

    const r = await msg('diffPlans', { plan_id_a: idA, plan_id_b: idB });
    if (!r?.success) {
      panel.innerHTML = `<div class="tcm-section-title">版本对比 <button class="tcm-close-panel" data-panel="tcm-diff-panel">×</button></div><p class="tcm-hint">${esc(r?.error || '加载失败')}</p>`;
      panel.querySelector('.tcm-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });
      return;
    }

    const diff = r.data;
    const lines = Array.isArray(diff.lines) ? diff.lines : (diff.diff_lines || []);
    const linesHtml = lines.map(line => {
      if (line.type === 'add' || line.op === '+') return `<div class="tcm-diff-add">+ ${esc(line.text || line.content)}</div>`;
      if (line.type === 'del' || line.op === '-') return `<div class="tcm-diff-del">- ${esc(line.text || line.content)}</div>`;
      return `<div class="tcm-diff-ctx">  ${esc(line.text || line.content)}</div>`;
    }).join('');

    panel.innerHTML = `
      <div class="tcm-section-title">版本对比 <button class="tcm-close-panel" data-panel="tcm-diff-panel">×</button></div>
      <div class="tcm-diff-box">${linesHtml || '<p class="tcm-hint">两版本内容相同</p>'}</div>
    `;
    panel.querySelector('.tcm-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });
  }

  async function loadSummaryPanel(planId) {
    const panel = document.getElementById('tcm-summary-panel');
    if (!panel) return;
    panel.style.display = 'block';
    panel.innerHTML = '<div class="tcm-section-title">方案摘要</div><div class="tcm-loading-sm">生成中…</div>';

    const r = await msg('renderSummary', { plan_id: planId, format: 'his_text' });
    if (!r?.success) {
      panel.innerHTML = `<div class="tcm-section-title">方案摘要 <button class="tcm-close-panel" data-panel="tcm-summary-panel">×</button></div><p class="tcm-hint">${esc(r?.error || '加载失败')}</p>`;
      panel.querySelector('.tcm-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });
      return;
    }

    const summary = r.data;
    const text = summary.his_text || summary.patient_text || summary.content || JSON.stringify(summary);

    panel.innerHTML = `
      <div class="tcm-section-title">方案摘要（HIS格式）<button class="tcm-close-panel" data-panel="tcm-summary-panel">×</button></div>
      <div class="tcm-summary-text">${esc(text)}</div>
      <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-copy-summary-btn">复制到剪贴板</button>
    `;
    panel.querySelector('.tcm-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });
    document.getElementById('tcm-copy-summary-btn')?.addEventListener('click', () => {
      navigator.clipboard.writeText(text).then(() => showToast('已复制', 'success')).catch(() => showToast('复制失败', 'error'));
    });
  }

  // ─── Tab 4: 随访指标 (E + stats) ───────────────────────────────────────────

  async function renderFollowupTab() {
    const c = document.getElementById('tcm-content');
    if (!c) return;
    c.innerHTML = `<div class="tcm-loading"><div class="tcm-spinner"></div><p>加载随访任务…</p></div>`;

    const [tasksResp, statsResp] = await Promise.all([
      msg('listFollowupTasks', { patient_id: currentPatient.archive_id }),
      msg('getRiskStats', {}),
    ]);

    const tasks = tasksResp?.success
      ? (Array.isArray(tasksResp.data) ? tasksResp.data : (tasksResp.data?.items || []))
      : [];

    const tasksHtml = tasks.length
      ? tasks.map(t => `
          <div class="tcm-plan-card">
            <div class="tcm-plan-card-header">
              <span style="color:${t.completed_at ? '#16a34a' : '#d97706'};font-size:12px">${t.completed_at ? '✅ 已完成' : '⏳ 待随访'}</span>
              <span class="tcm-plan-date">${esc((t.scheduled_date || t.plan_date || '').slice(0,10))}</span>
            </div>
            <div class="tcm-plan-title">${esc(t.title || t.followup_type || '随访任务')}</div>
            ${t.note || t.content ? `<div class="tcm-plan-preview">${esc((t.note || t.content || '').slice(0,60))}</div>` : ''}
          </div>`).join('')
      : '<div class="tcm-empty"><p>暂无随访任务</p></div>';

    // 快速创建随访
    const createForm = `
      <div class="tcm-section" id="tcm-followup-create-section" style="display:none;">
        <div class="tcm-section-title">快速创建随访</div>
        <input type="text" id="tcm-fw-title" class="tcm-input" placeholder="随访标题" />
        <select id="tcm-fw-days" class="tcm-select" style="margin-top:4px;width:100%;">
          <option value="3">3天后</option>
          <option value="7" selected>7天后</option>
          <option value="14">14天后</option>
          <option value="30">30天后</option>
        </select>
        <div style="display:flex;gap:6px;margin-top:6px">
          <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-fw-save-btn">创建</button>
          <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-fw-cancel-btn">取消</button>
        </div>
      </div>
    `;

    // 统计数据
    let statsHtml = '';
    if (statsResp?.success) {
      const d = statsResp.data || {};
      statsHtml = `
        <div class="tcm-section">
          <div class="tcm-section-title">业务统计</div>
          <div class="tcm-stats-grid">
            <div class="tcm-kpi-card"><div class="tcm-kpi-value">${d.total_analyzed ?? 0}</div><div class="tcm-kpi-label">总分析次数</div></div>
            <div class="tcm-kpi-card"><div class="tcm-kpi-value">${d.total_issued ?? 0}</div><div class="tcm-kpi-label">已下达方案</div></div>
          </div>
        </div>`;
    }

    c.innerHTML = `
      <div class="tcm-plan-actions-bar">
        <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-create-fw-btn">+ 新建随访</button>
      </div>
      ${createForm}
      <div class="tcm-section">
        <div class="tcm-section-title">随访任务（${tasks.length}条）</div>
        <div class="tcm-plan-list">${tasksHtml}</div>
      </div>
      ${statsHtml}
    `;

    document.getElementById('tcm-create-fw-btn')?.addEventListener('click', () => {
      const section = document.getElementById('tcm-followup-create-section');
      if (section) section.style.display = section.style.display === 'none' ? 'block' : 'none';
    });

    document.getElementById('tcm-fw-cancel-btn')?.addEventListener('click', () => {
      const section = document.getElementById('tcm-followup-create-section');
      if (section) section.style.display = 'none';
    });

    document.getElementById('tcm-fw-save-btn')?.addEventListener('click', async () => {
      const title = document.getElementById('tcm-fw-title')?.value.trim();
      const days  = parseInt(document.getElementById('tcm-fw-days')?.value || '7', 10);
      if (!title) { showToast('请输入随访标题', 'error'); return; }

      const schedDate = new Date();
      schedDate.setDate(schedDate.getDate() + days);
      const dateStr = schedDate.toISOString().slice(0, 10);

      const btn = document.getElementById('tcm-fw-save-btn');
      if (btn) { btn.textContent = '创建中…'; btn.disabled = true; }

      const r = await msg('createFollowupPlan', { body: {
        patient_id: currentPatient.archive_id,
        title,
        scheduled_date: dateStr,
      }});

      if (btn) { btn.textContent = '创建'; btn.disabled = false; }
      if (r?.success) { showToast('随访已创建', 'success'); renderFollowupTab(); }
      else showToast(`创建失败：${r?.error || ''}`, 'error');
    });
  }

  // ─── Toast ──────────────────────────────────────────────────────────────────

  function showToast(text, type) {
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (!sidebar) return;
    const t = document.createElement('div');
    t.className = `tcm-toast tcm-toast-${type}`;
    t.textContent = text;
    sidebar.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  // ─── 渲染入口 ───────────────────────────────────────────────────────────────

  function renderResult(patient, context, risk, warning) {
    currentPatient = patient;
    currentContext = context || null;
    currentRisk    = risk;
    // 清除旧的缓存
    currentProfile   = null;
    currentMetrics   = null;
    currentRiskTags  = null;
    currentPlanVersions = null;

    createSidebar();
    if (warning) showToast(`⚠️ ${warning}`, 'error');
    renderPatientTab();
  }

  // ─── URL 检测 ───────────────────────────────────────────────────────────────

  async function checkUrl() {
    const config = await getConfig();
    const patientId = extractPatientId(config.paramNames);

    if (!patientId) {
      if (currentPatientId !== null) {
        currentPatientId = null; currentPatient = null; currentRisk = null;
        currentProfile = null; currentMetrics = null; currentRiskTags = null;
        const c = document.getElementById('tcm-content');
        if (c) c.innerHTML = `<div class="tcm-idle"><div class="tcm-idle-icon">🔍</div><p>等待检测患者信息…</p><p class="tcm-hint">当前页面未检测到患者ID参数</p></div>`;
      }
      return;
    }
    if (patientId === currentPatientId) return;
    currentPatientId = patientId;

    createSidebar();
    activeTab = 'patient';
    document.querySelectorAll('.tcm-tab').forEach(b => b.classList.remove('tcm-tab-active'));
    document.querySelector('.tcm-tab[data-tab="patient"]')?.classList.add('tcm-tab-active');

    renderLoading(patientId);

    chrome.runtime.sendMessage({ action: 'patientDetected', patientId }, (response) => {
      if (chrome.runtime.lastError) { renderError('插件内部通信失败，请重新加载插件'); return; }
      if (!response) { renderError('未收到后台响应'); return; }
      if (response.error) { renderError(response.error); return; }
      renderResult(response.patient, response.context, response.risk, response.warning);
    });
  }

  function debouncedCheck() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(checkUrl, DEBOUNCE_MS);
  }

  // ─── 手动搜索监听 ───────────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action !== 'manualSearch') return;
    const keyword = message.keyword?.trim();
    if (!keyword) { sendResponse({ ok: false, error: '请输入患者姓名或档案号' }); return; }

    createSidebar();
    isCollapsed = false;
    document.getElementById(SIDEBAR_ID)?.classList.remove('tcm-collapsed');
    currentPatientId = keyword;
    renderLoading(keyword);

    chrome.runtime.sendMessage({ action: 'patientDetected', patientId: keyword }, (response) => {
      if (chrome.runtime.lastError || !response) { renderError('通信失败，请重试'); return; }
      if (response.error) { renderError(response.error); return; }
      renderResult(response.patient, response.context, response.risk, response.warning);
    });
    sendResponse({ ok: true });
  });

  // ─── History API 拦截 ───────────────────────────────────────────────────────

  const _push = history.pushState.bind(history);
  const _replace = history.replaceState.bind(history);
  history.pushState    = (...args) => { _push(...args); debouncedCheck(); };
  history.replaceState = (...args) => { _replace(...args); debouncedCheck(); };
  window.addEventListener('popstate',    debouncedCheck);
  window.addEventListener('hashchange',  debouncedCheck);

  // ─── 初始化 ────────────────────────────────────────────────────────────────

  async function init() {
    const config = await getConfig();
    isCollapsed = config.sidebarCollapsed !== false;
    createSidebar();
    if (isCollapsed) document.getElementById(SIDEBAR_ID)?.classList.add('tcm-collapsed');
    checkUrl();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

})();
