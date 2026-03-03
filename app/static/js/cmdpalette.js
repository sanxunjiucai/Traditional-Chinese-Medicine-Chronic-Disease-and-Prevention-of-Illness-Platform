/**
 * 全局命令面板 (Ctrl+K)
 * 医生通过自然语言下达操作指令，智能体调用平台工具并返回结果。
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'tcm_cmd_history';
  const MAX_HISTORY = 10;

  // ── 状态 ────────────────────────────────────────────────────────────────
  let historyList = [];
  let histIdx = -1;        // 历史导航索引
  let isOpen = false;

  // ── DOM 引用（在 open() 时填充）────────────────────────────────────────
  let overlay, modal, input, statusEl, resultEl, histEl, goBtn;

  // ── 初始化 ───────────────────────────────────────────────────────────────
  function init() {
    loadHistory();
    buildDOM();
    bindEvents();
  }

  // ── 历史记录 ─────────────────────────────────────────────────────────────
  function loadHistory() {
    try { historyList = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch (_) { historyList = []; }
  }

  function saveHistory(query) {
    historyList = [query, ...historyList.filter(h => h !== query)].slice(0, MAX_HISTORY);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(historyList));
  }

  // ── 构建 DOM ─────────────────────────────────────────────────────────────
  function buildDOM() {
    // 遮罩
    overlay = document.createElement('div');
    overlay.id = 'cmd-overlay';
    overlay.style.cssText = [
      'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9998',
      'display:none;align-items:flex-start;justify-content:center;padding-top:10vh',
      'backdrop-filter:blur(2px)',
    ].join(';');

    // 主体
    modal = document.createElement('div');
    modal.id = 'cmd-modal';
    modal.style.cssText = [
      'background:#fff;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.25)',
      'width:min(680px,92vw);max-height:72vh;display:flex;flex-direction:column',
      'overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif',
    ].join(';');

    // 头部（输入行）
    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;padding:16px 18px;border-bottom:1px solid #f0f0f0;gap:10px';

    // 搜索图标
    header.insertAdjacentHTML('beforeend', `
      <svg style="width:20px;height:20px;flex-shrink:0;color:#16a34a" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
          d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
      </svg>`);

    input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '用自然语言下达指令，如：查一下张三最近的预警';
    input.autocomplete = 'off';
    input.style.cssText = [
      'flex:1;border:none;outline:none;font-size:16px;color:#1f2937',
      'background:transparent;caret-color:#16a34a',
    ].join(';');

    // Esc 提示
    const escBadge = document.createElement('kbd');
    escBadge.textContent = 'ESC';
    escBadge.style.cssText = [
      'font-size:11px;color:#9ca3af;border:1px solid #e5e7eb',
      'border-radius:4px;padding:2px 6px;flex-shrink:0',
    ].join(';');

    header.append(input, escBadge);

    // 状态栏
    statusEl = document.createElement('div');
    statusEl.style.cssText = [
      'font-size:12px;color:#6b7280;padding:6px 18px 0',
      'display:none',
    ].join(';');

    // 历史建议
    histEl = document.createElement('div');
    histEl.style.cssText = 'padding:0 8px';

    // 结果区
    resultEl = document.createElement('div');
    resultEl.style.cssText = [
      'padding:0 18px 18px;overflow-y:auto;flex:1',
      'font-size:13px;color:#374151',
    ].join(';');

    // 底部跳转按钮（动态显示）
    goBtn = document.createElement('button');
    goBtn.style.cssText = [
      'display:none;margin:0 18px 14px;padding:8px 16px',
      'background:#16a34a;color:#fff;border:none;border-radius:8px',
      'font-size:13px;cursor:pointer;align-self:flex-start',
      'transition:background .15s',
    ].join(';');
    goBtn.onmouseenter = () => { goBtn.style.background = '#15803d'; };
    goBtn.onmouseleave = () => { goBtn.style.background = '#16a34a'; };

    modal.append(header, statusEl, histEl, resultEl, goBtn);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  }

  // ── 事件绑定 ─────────────────────────────────────────────────────────────
  function bindEvents() {
    // Ctrl+K 全局快捷键
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        isOpen ? close() : open();
      }
      if (e.key === 'Escape' && isOpen) close();
    });

    // 点遮罩关闭
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });

    // 输入框键盘
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && input.value.trim()) {
        e.preventDefault();
        submit(input.value.trim());
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        navigateHistory(-1);
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        navigateHistory(1);
      }
    });

    // 输入时更新历史建议
    input.addEventListener('input', () => {
      histIdx = -1;
      renderHistorySuggestions(input.value);
    });
  }

  // ── 打开 / 关闭 ──────────────────────────────────────────────────────────
  function open() {
    isOpen = true;
    overlay.style.display = 'flex';
    resultEl.innerHTML = '';
    statusEl.style.display = 'none';
    goBtn.style.display = 'none';
    input.value = '';
    histIdx = -1;
    renderHistorySuggestions('');
    setTimeout(() => input.focus(), 30);
  }

  function close() {
    isOpen = false;
    overlay.style.display = 'none';
  }

  // ── 历史导航 ─────────────────────────────────────────────────────────────
  function navigateHistory(dir) {
    if (!historyList.length) return;
    histIdx = Math.max(-1, Math.min(historyList.length - 1, histIdx + dir));
    input.value = histIdx >= 0 ? historyList[histIdx] : '';
    renderHistorySuggestions(input.value);
  }

  // ── 历史建议列表 ─────────────────────────────────────────────────────────
  function renderHistorySuggestions(q) {
    histEl.innerHTML = '';
    const matches = q
      ? historyList.filter(h => h.toLowerCase().includes(q.toLowerCase()))
      : historyList;
    if (!matches.length) return;

    const label = document.createElement('div');
    label.textContent = '最近指令';
    label.style.cssText = 'font-size:11px;color:#9ca3af;padding:8px 10px 4px;letter-spacing:.05em';
    histEl.appendChild(label);

    matches.slice(0, 5).forEach(h => {
      const item = document.createElement('div');
      item.textContent = h;
      item.style.cssText = [
        'padding:7px 10px;border-radius:8px;cursor:pointer',
        'color:#4b5563;font-size:13px;display:flex;align-items:center;gap:8px',
        'transition:background .1s',
      ].join(';');
      item.insertAdjacentHTML('afterbegin',
        `<svg style="width:14px;height:14px;flex-shrink:0;color:#d1d5db" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>`);
      item.onmouseenter = () => { item.style.background = '#f9fafb'; };
      item.onmouseleave = () => { item.style.background = ''; };
      item.onclick = () => {
        input.value = h;
        histEl.innerHTML = '';
        submit(h);
      };
      histEl.appendChild(item);
    });
  }

  // ── 提交执行 ─────────────────────────────────────────────────────────────
  async function submit(query) {
    saveHistory(query);
    histEl.innerHTML = '';
    showLoading(query);

    let resp, json;
    try {
      resp = await fetch('/tools/agent/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      json = await resp.json();
    } catch (err) {
      showError('网络请求失败：' + err.message);
      return;
    }

    if (!json.success) {
      showError(json.message || '执行失败');
      return;
    }

    renderResult(query, json.data);
  }

  // ── 加载态 ───────────────────────────────────────────────────────────────
  function showLoading(query) {
    statusEl.style.display = 'block';
    statusEl.innerHTML = `
      <span style="display:inline-flex;align-items:center;gap:6px">
        <svg style="width:13px;height:13px;animation:spin 1s linear infinite" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        正在执行：${escHtml(query)}
      </span>`;
    resultEl.innerHTML = '';
    goBtn.style.display = 'none';

    // 注入旋转动画（只注入一次）
    if (!document.getElementById('cmd-spin-style')) {
      const s = document.createElement('style');
      s.id = 'cmd-spin-style';
      s.textContent = '@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}';
      document.head.appendChild(s);
    }
  }

  // ── 错误态 ───────────────────────────────────────────────────────────────
  function showError(msg) {
    statusEl.style.display = 'none';
    resultEl.innerHTML = `
      <div style="display:flex;align-items:flex-start;gap:10px;margin-top:12px;
                  background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px">
        <svg style="width:18px;height:18px;flex-shrink:0;color:#ef4444;margin-top:1px"
             fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
        <span style="color:#b91c1c">${escHtml(msg)}</span>
      </div>`;
  }

  // ── 渲染结果 ─────────────────────────────────────────────────────────────
  function renderResult(query, payload) {
    statusEl.style.display = 'none';

    const { message, data, navigate_url, execution_id } = payload;

    let html = '';

    // 主消息气泡
    if (message) {
      html += `
        <div style="display:flex;gap:10px;margin-top:12px;align-items:flex-start">
          <div style="width:28px;height:28px;border-radius:50%;background:#dcfce7;
                      flex-shrink:0;display:flex;align-items:center;justify-content:center">
            <svg style="width:15px;height:15px;color:#16a34a" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
          </div>
          <div style="flex:1;background:#f9fafb;border-radius:0 12px 12px 12px;
                      padding:10px 14px;line-height:1.6;color:#1f2937">
            ${escHtml(message)}
          </div>
        </div>`;
    }

    // 结构化数据表格
    if (data && data.items && data.items.length > 0) {
      html += renderDataTable(data);
    } else if (data && typeof data === 'object' && !data.items) {
      // key-value 类数据（如 stats）
      html += renderKV(data);
    }

    // 执行 ID（用于审计）
    if (execution_id) {
      html += `<div style="margin-top:10px;font-size:11px;color:#d1d5db">
        执行记录 ID：${escHtml(execution_id)}</div>`;
    }

    resultEl.innerHTML = html;

    // 跳转按钮
    if (navigate_url) {
      goBtn.textContent = `前往 → ${navigate_url.replace('/gui/admin/', '')}`;
      goBtn.style.display = 'block';
      goBtn.onclick = () => { window.location.href = navigate_url; };
    } else {
      goBtn.style.display = 'none';
    }
  }

  // ── 数据表格渲染 ─────────────────────────────────────────────────────────
  function renderDataTable(data) {
    if (!data.items.length) return '<p style="color:#9ca3af;margin-top:12px">暂无数据</p>';
    const keys = Object.keys(data.items[0]);

    const labelMap = {
      id: 'ID', name: '姓名', patient: '患者', phone: '手机号',
      is_active: '状态', created_at: '注册时间', severity: '严重程度',
      status: '状态', message: '预警内容', adherence_rate: '依从率',
      disease: '病种', start_date: '开始日期', end_date: '结束日期',
      plan_id: '计划ID', count: '数量',
    };

    const visibleKeys = keys.filter(k => !['plan_id'].includes(k));

    let rows = data.items.map(item => {
      const cells = visibleKeys.map(k => {
        let v = item[k];
        if (k === 'is_active') v = v ? '✓ 启用' : '✗ 禁用';
        if (k === 'adherence_rate') v = (v * 100).toFixed(1) + '%';
        if (k === 'severity') {
          const colors = { HIGH: '#dc2626', MEDIUM: '#d97706', LOW: '#16a34a' };
          const labels = { HIGH: '高危', MEDIUM: '中危', LOW: '低危' };
          v = `<span style="color:${colors[v] || '#374151'}">${labels[v] || v}</span>`;
        }
        if (k === 'status' && ['OPEN','ACKED','CLOSED'].includes(v)) {
          const sl = { OPEN: '开放', ACKED: '已确认', CLOSED: '已关闭' };
          v = sl[v] || v;
        }
        if (k === 'id' && v && v.length > 8) v = v.slice(0, 8) + '…';
        if (k === 'created_at' && v) v = v.slice(0, 16).replace('T', ' ');
        if (v === null || v === undefined) v = '—';
        return `<td style="padding:7px 10px;vertical-align:top">${v}</td>`;
      }).join('');
      return `<tr style="border-top:1px solid #f3f4f6">${cells}</tr>`;
    }).join('');

    const headers = visibleKeys.map(k =>
      `<th style="padding:6px 10px;text-align:left;color:#6b7280;font-weight:500;
                  font-size:11px;text-transform:uppercase;letter-spacing:.05em">
        ${labelMap[k] || k}
      </th>`
    ).join('');

    return `
      <div style="margin-top:12px;overflow-x:auto;border-radius:8px;border:1px solid #e5e7eb">
        <div style="padding:8px 12px;background:#f9fafb;border-bottom:1px solid #e5e7eb;
                    font-size:12px;color:#6b7280">共 ${data.count} 条结果</div>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead style="background:#f9fafb"><tr>${headers}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // ── KV 数据渲染 ──────────────────────────────────────────────────────────
  function renderKV(data) {
    const labelMap = {
      total_patients: '患者总数', active_patients: '在管患者',
      open_alerts: '开放预警', high_severity_alerts: '高危预警',
      overall_adherence_rate: '整体依从率',
    };
    const items = Object.entries(data)
      .filter(([k]) => k !== 'items' && k !== 'count')
      .map(([k, v]) => {
        if (typeof v === 'number' && k.includes('rate')) v = (v * 100).toFixed(1) + '%';
        return `
          <div style="display:flex;justify-content:space-between;padding:8px 12px;
                      border-top:1px solid #f3f4f6">
            <span style="color:#6b7280">${labelMap[k] || k}</span>
            <span style="font-weight:600;color:#111827">${v ?? '—'}</span>
          </div>`;
      }).join('');

    return `
      <div style="margin-top:12px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
        ${items}
      </div>`;
  }

  // ── 工具函数 ─────────────────────────────────────────────────────────────
  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── 启动 ─────────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
