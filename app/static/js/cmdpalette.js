/**
 * 全局命令面板 (Ctrl+K) - 对话式智能助手
 * 支持会话历史、上下文建议、动态补全
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'tcm_cmd_history';
  const MAX_HISTORY = 20;

  // 玉竹·自然 色系
  const C = {
    primary:      '#4E7A61',
    primaryLight: '#dcfce7',
    primaryDark:  '#3d6150',
    amber:        '#B8885E',
    bg:           '#F7F5F0',
    border:       '#E4DDD4',
    text:         '#28231E',
    muted:        '#6b7280',
  };

  // 状态
  let historyList    = [];
  let sessionMsgs    = [];   // 当前会话消息
  let isOpen         = false;
  let suggIdx        = -1;   // 建议列表当前高亮索引
  let isRequesting   = false;

  // DOM 引用
  let overlay, modal, messagesEl, inputEl, suggestionsEl, quickChipsEl;

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  快捷建议数据
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  const QUICK = [
    { icon: '⚠️', text: '查看今日高危预警' },
    { icon: '👤', text: '查询最近登记的患者' },
    { icon: '📅', text: '列出本周待完成随访' },
    { icon: '✨', text: '帮张伟创建随访任务' },
    { icon: '📊', text: '统计本月随访完成率' },
    { icon: '🏥', text: '查找糖尿病管理患者' },
    { icon: '📋', text: '新建一个居民档案' },
  ];

  // 动态补全词库
  const PRESETS = [
    '查看今日高危预警',
    '查询最近登记的患者',
    '查找患者档案',
    '列出本周待完成随访',
    '统计本月随访完成率',
    '帮张伟创建随访任务',
    '为李芳创建糖尿病随访',
    '给王国华建立高血压随访计划',
    '统计各体质类型人数',
    '查询开放中的预警',
    '查找糖尿病管理患者',
    '查询高血压患者列表',
    '查看最近的量表评估',
    '显示本月工作量统计',
    '查询气虚质患者',
    '列出近期宣教内容',
    '查询待审核档案',
    '显示系统概况',
    '查询高危预警列表',
    '统计在管患者人数',
    '查询随访依从性报告',
    '查看体质评估记录',
    '统计各病种患者分布',
  ];

  // 根据当前页面返回上下文建议
  function getContextSuggestions() {
    const p = window.location.pathname;
    if (p.includes('/alerts'))       return ['查看今日高危预警', '查询开放中的预警', '查询已关闭的预警'];
    if (p.includes('/archive'))      return ['查询最近登记的患者', '查找患者档案', '查询待审核档案'];
    if (p.includes('/followup'))     return ['列出本周待完成随访', '统计本月随访完成率', '查询随访依从性报告'];
    if (p.includes('/stats'))        return ['统计本月随访完成率', '显示本月工作量统计', '统计各体质类型人数'];
    if (p.includes('/assessment') || p.includes('/constitution'))
                                     return ['统计各体质类型人数', '查询气虚质患者', '查看最近的量表评估'];
    if (p.includes('/intervention')) return ['查询干预计划列表', '统计干预完成情况', '查找待调整干预计划'];
    return null;
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  初始化
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function init() {
    loadHistory();
    injectStyles();
    buildDOM();
    bindEvents();
  }

  function loadHistory() {
    try { historyList = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
    catch (_) { historyList = []; }
  }

  function saveHistory(q) {
    historyList = [q, ...historyList.filter(h => h !== q)].slice(0, MAX_HISTORY);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(historyList));
  }

  function injectStyles() {
    if (document.getElementById('cmd-style')) return;
    const s = document.createElement('style');
    s.id = 'cmd-style';
    s.textContent = `
      @keyframes cmd-spin   { from{transform:rotate(0)} to{transform:rotate(360deg)} }
      @keyframes cmd-fadeIn { from{opacity:0;transform:translateY(5px)} to{opacity:1;transform:translateY(0)} }
      @keyframes cmd-bounce {
        0%,80%,100% { transform:scale(.7); opacity:.4 }
        40%          { transform:scale(1);  opacity:1  }
      }
      #cmd-messages::-webkit-scrollbar       { width:4px }
      #cmd-messages::-webkit-scrollbar-track { background:transparent }
      #cmd-messages::-webkit-scrollbar-thumb { background:#d1d5db; border-radius:4px }
      .cmd-msg   { animation: cmd-fadeIn .18s ease }
      .cmd-chip  { transition: all .15s }
      .cmd-chip:hover { background:#dcfce7 !important; border-color:#4E7A61 !important; color:#1f2937 !important }
      .cmd-sugg-item { transition: background .1s; cursor:pointer }
      .cmd-sugg-item:hover, .cmd-sugg-item.active { background:#f0fdf4 !important }
      #cmd-input { scrollbar-width:none }
      #cmd-input::-webkit-scrollbar { display:none }
      #cmd-send-btn:hover { background:#3d6150 !important }
      #cmd-clear-btn:hover { background:rgba(255,255,255,.3) !important }
      #cmd-close-btn:hover { background:rgba(255,255,255,.3) !important }
    `;
    document.head.appendChild(s);
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  构建 DOM
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function buildDOM() {
    // 遮罩
    overlay = document.createElement('div');
    overlay.id = 'cmd-overlay';
    overlay.style.cssText = [
      'position:fixed;inset:0;z-index:9998',
      'background:rgba(40,35,30,.52)',
      'display:none;align-items:flex-start;justify-content:center;padding-top:7vh',
      'backdrop-filter:blur(3px)',
    ].join(';');

    // 主体
    modal = document.createElement('div');
    modal.id = 'cmd-modal';
    modal.style.cssText = [
      `background:${C.bg};border-radius:20px`,
      'box-shadow:0 24px 80px rgba(0,0,0,.28),0 0 0 1px rgba(0,0,0,.06)',
      'width:min(720px,94vw);height:min(620px,82vh)',
      'display:flex;flex-direction:column;overflow:hidden',
      'font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif',
    ].join(';');

    // ── 头部 ────────────────────────────────
    const header = document.createElement('div');
    header.style.cssText = [
      `background:${C.primary};padding:13px 18px`,
      'display:flex;align-items:center;justify-content:space-between;flex-shrink:0',
    ].join(';');
    header.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px">
        <div style="width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.18);
                    display:flex;align-items:center;justify-content:center;flex-shrink:0">
          <svg style="width:17px;height:17px;color:#fff" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
                 m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
                 A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
                 c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
          </svg>
        </div>
        <div>
          <div style="color:#fff;font-size:14px;font-weight:600;letter-spacing:.02em">智能助手</div>
          <div style="color:rgba(255,255,255,.65);font-size:11px">中医慢病管理 · AI 对话</div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:6px">
        <button id="cmd-clear-btn" class="cmd-clear-btn"
          style="background:rgba(255,255,255,.15);border:none;border-radius:8px;
                 padding:5px 10px;cursor:pointer;color:#fff;font-size:11px;
                 display:flex;align-items:center;gap:4px">
          <svg style="width:12px;height:12px" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7
                 m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
          </svg>
          清除对话
        </button>
        <button id="cmd-close-btn" class="cmd-close-btn" title="关闭 (ESC)"
          style="background:rgba(255,255,255,.15);border:none;border-radius:8px;
                 width:30px;height:30px;cursor:pointer;color:#fff;
                 display:flex;align-items:center;justify-content:center">
          <svg style="width:14px;height:14px" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>`;

    // ── 消息列表 ────────────────────────────
    messagesEl = document.createElement('div');
    messagesEl.id = 'cmd-messages';
    messagesEl.style.cssText = [
      'flex:1;overflow-y:auto;padding:16px 16px 10px',
      'display:flex;flex-direction:column;gap:14px;min-height:0',
    ].join(';');

    // ── 快捷建议芯片 ────────────────────────
    quickChipsEl = document.createElement('div');
    quickChipsEl.id = 'cmd-quick-chips';
    quickChipsEl.style.cssText = [
      `flex-shrink:0;padding:10px 16px 12px;border-top:1px solid ${C.border}`,
    ].join(';');

    // ── 输入区（含建议下拉） ─────────────────
    const inputWrap = document.createElement('div');
    inputWrap.style.cssText = [
      `background:#fff;border-top:1px solid ${C.border}`,
      'padding:10px 12px 12px;flex-shrink:0;position:relative',
    ].join(';');

    // 建议下拉（浮在输入框上方）
    suggestionsEl = document.createElement('div');
    suggestionsEl.id = 'cmd-suggestions';
    suggestionsEl.style.cssText = [
      'position:absolute;left:12px;right:12px;bottom:calc(100% + 4px)',
      `background:#fff;border:1.5px solid ${C.border};border-radius:14px`,
      'box-shadow:0 8px 28px rgba(0,0,0,.12);overflow:hidden;display:none;z-index:10',
    ].join(';');

    // 输入行
    const inputRow = document.createElement('div');
    inputRow.style.cssText = [
      `background:${C.bg};border:1.5px solid ${C.border};border-radius:14px`,
      'display:flex;align-items:flex-end;gap:8px;padding:8px 8px 8px 14px',
      'transition:border-color .15s',
    ].join(';');

    inputEl = document.createElement('textarea');
    inputEl.id = 'cmd-input';
    inputEl.placeholder = '输入问题，如"查看今日高危预警"…';
    inputEl.rows = 1;
    inputEl.style.cssText = [
      'flex:1;border:none;outline:none;font-size:14px',
      `color:${C.text};background:transparent;caret-color:${C.primary}`,
      'resize:none;line-height:1.55;max-height:96px;overflow-y:auto;font-family:inherit',
    ].join(';');

    inputRow.addEventListener('focusin',  () => { inputRow.style.borderColor = C.primary; });
    inputRow.addEventListener('focusout', () => { inputRow.style.borderColor = C.border;  });

    const sendBtn = document.createElement('button');
    sendBtn.id = 'cmd-send-btn';
    sendBtn.title = '发送 (Enter)';
    sendBtn.style.cssText = [
      `background:${C.primary};border:none;border-radius:10px`,
      'width:36px;height:36px;cursor:pointer;flex-shrink:0',
      'display:flex;align-items:center;justify-content:center',
    ].join(';');
    sendBtn.innerHTML = `
      <svg style="width:17px;height:17px;color:#fff" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2"
          d="M12 19V5M5 12l7-7 7 7"/>
      </svg>`;

    inputRow.append(inputEl, sendBtn);
    inputWrap.append(suggestionsEl, inputRow);

    modal.append(header, messagesEl, quickChipsEl, inputWrap);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  事件绑定
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function bindEvents() {
    // Ctrl+K 全局快捷键
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        isOpen ? close() : open();
      }
      if (e.key === 'Escape' && isOpen) {
        if (suggestionsEl.style.display !== 'none') hideSuggestions();
        else close();
      }
    });

    // 点击遮罩关闭
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    // 头部按钮
    document.addEventListener('click', (e) => {
      if (e.target.closest('#cmd-clear-btn')) clearChat();
      if (e.target.closest('#cmd-close-btn')) close();
    });

    // 发送按钮
    document.addEventListener('click', (e) => {
      if (e.target.closest('#cmd-send-btn')) {
        const v = inputEl.value.trim();
        if (v) submit(v);
      }
    });

    // 输入框键盘
    inputEl.addEventListener('keydown', (e) => {
      const suggOpen = suggestionsEl.style.display !== 'none';

      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (suggOpen && suggIdx >= 0) {
          pickSuggestion(suggIdx);
        } else {
          const v = inputEl.value.trim();
          if (v) submit(v);
          hideSuggestions();
        }
        return;
      }
      if (e.key === 'Tab' && suggOpen) {
        e.preventDefault();
        pickSuggestion(suggIdx >= 0 ? suggIdx : 0);
        return;
      }
      if (e.key === 'ArrowUp' && suggOpen) {
        e.preventDefault(); moveSuggIdx(-1); return;
      }
      if (e.key === 'ArrowDown' && suggOpen) {
        e.preventDefault(); moveSuggIdx(1); return;
      }
      if (e.key === 'Escape' && suggOpen) {
        e.stopPropagation(); hideSuggestions(); return;
      }
    });

    inputEl.addEventListener('input', () => {
      autoResize();
      renderSuggestions(inputEl.value);
      renderQuickChips();
    });

    inputEl.addEventListener('focus', () => {
      renderSuggestions(inputEl.value);
    });

    inputEl.addEventListener('blur', () => {
      // 延迟隐藏，让点击建议的 mousedown 先触发
      setTimeout(hideSuggestions, 160);
    });
  }

  function autoResize() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 96) + 'px';
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  打开 / 关闭 / 清除
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function open() {
    isOpen = true;
    overlay.style.display = 'flex';
    hideSuggestions();
    if (!sessionMsgs.length) showWelcome();
    renderQuickChips();
    setTimeout(() => inputEl.focus(), 40);
  }

  function close() {
    isOpen = false;
    overlay.style.display = 'none';
    hideSuggestions();
  }

  function clearChat() {
    sessionMsgs = [];
    messagesEl.innerHTML = '';
    showWelcome();
    renderQuickChips();
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  欢迎消息
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function showWelcome() {
    appendAssistantMsg(
      `您好！我是中医慢病管理平台的智能助手。\n\n我可以帮您：\n• 查询患者档案与预警信息\n• 统计随访、评估等工作数据\n• 快速定位平台功能页面\n\n请直接输入您的问题，或点击下方快捷建议开始对话。`,
      null
    );
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  快捷建议芯片
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function renderQuickChips() {
    if (!quickChipsEl) return;
    if (inputEl.value.trim()) { quickChipsEl.style.display = 'none'; return; }

    const ctxList = getContextSuggestions();
    const chips   = ctxList
      ? ctxList.map(t => ({ text: t }))
      : QUICK.slice(0, sessionMsgs.length > 1 ? 3 : 6);

    quickChipsEl.style.display = 'block';
    quickChipsEl.innerHTML = `
      <div style="font-size:11px;color:#9ca3af;margin-bottom:7px;letter-spacing:.04em">
        ${ctxList ? '📍 当前页面相关' : '💡 快速提问'}
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${chips.map(c => `
          <button class="cmd-chip" data-text="${escHtml(c.text)}"
            style="border:1.5px solid ${C.border};border-radius:20px;background:#fff;
                   padding:5px 13px;cursor:pointer;font-size:12px;color:#4b5563;
                   font-family:inherit;white-space:nowrap;outline:none">
            ${c.icon ? c.icon + ' ' : ''}${escHtml(c.text)}
          </button>`).join('')}
      </div>`;

    quickChipsEl.querySelectorAll('.cmd-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const text = btn.dataset.text;
        hideSuggestions();
        quickChipsEl.style.display = 'none';
        submit(text);
      });
    });
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  动态建议下拉
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function renderSuggestions(q) {
    if (!q.trim()) { hideSuggestions(); return; }

    const lower = q.toLowerCase();
    const histMatches   = historyList.filter(h => h.toLowerCase().includes(lower)).slice(0, 3);
    const presetMatches = PRESETS.filter(s =>
      s.toLowerCase().includes(lower) && !histMatches.includes(s)
    ).slice(0, Math.max(0, 5 - histMatches.length));

    const all = [
      ...histMatches.map(t => ({ text: t, type: 'history' })),
      ...presetMatches.map(t => ({ text: t, type: 'preset'  })),
    ];

    if (!all.length) { hideSuggestions(); return; }

    suggIdx = -1;
    suggestionsEl.innerHTML = '';

    // 分组标题
    let lastType = null;
    all.forEach((item, idx) => {
      if (item.type !== lastType) {
        const lbl = document.createElement('div');
        lbl.style.cssText = 'font-size:10px;color:#9ca3af;padding:8px 12px 4px;letter-spacing:.04em;text-transform:uppercase';
        lbl.textContent = item.type === 'history' ? '最近使用' : '智能建议';
        suggestionsEl.appendChild(lbl);
        lastType = item.type;
      }

      const el = document.createElement('div');
      el.className = 'cmd-sugg-item';
      el.dataset.idx = idx;
      el.style.cssText = 'display:flex;align-items:center;gap:8px;padding:9px 12px;border-top:1px solid #f5f5f5';

      const iconColor = item.type === 'history' ? '#9ca3af' : C.primary;
      const iconPath  = item.type === 'history'
        ? 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z'
        : 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z';
      const badge     = item.type === 'history'
        ? `<span style="font-size:10px;color:#d1d5db;flex-shrink:0">历史</span>`
        : `<span style="font-size:10px;color:#a7d4b6;flex-shrink:0">建议</span>`;

      el.innerHTML = `
        <svg style="width:13px;height:13px;flex-shrink:0;color:${iconColor}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${iconPath}"/>
        </svg>
        <span style="font-size:13px;color:#374151;flex:1">${highlightMatch(item.text, q)}</span>
        ${badge}`;

      el.addEventListener('mouseenter', () => { suggIdx = idx; syncSuggHighlight(); });
      el.addEventListener('mouseleave', () => {});
      el.addEventListener('mousedown',  (e) => {
        e.preventDefault();
        pickSuggestion(idx, all);
      });

      suggestionsEl.appendChild(el);
    });

    suggestionsEl._items = all;
    suggestionsEl.style.display = 'block';
  }

  function hideSuggestions() {
    suggestionsEl.style.display = 'none';
    suggIdx = -1;
  }

  function moveSuggIdx(dir) {
    const items = suggestionsEl.querySelectorAll('.cmd-sugg-item');
    suggIdx = Math.max(-1, Math.min(items.length - 1, suggIdx + dir));
    syncSuggHighlight();
    if (suggIdx >= 0 && items[suggIdx]) {
      const txt = items[suggIdx].querySelector('span')?.innerText;
      if (txt) { inputEl.value = txt; autoResize(); }
    }
  }

  function syncSuggHighlight() {
    suggestionsEl.querySelectorAll('.cmd-sugg-item').forEach((el, i) => {
      el.classList.toggle('active', i === suggIdx);
    });
  }

  function pickSuggestion(idx, itemsArr) {
    const items = itemsArr || suggestionsEl._items || [];
    const item  = items[idx];
    if (!item) return;
    inputEl.value = item.text;
    autoResize();
    hideSuggestions();
    submit(item.text);
  }

  function highlightMatch(text, q) {
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return escHtml(text);
    return (
      escHtml(text.slice(0, i)) +
      `<mark style="background:#dcfce7;color:#166534;border-radius:2px;padding:0 1px">${escHtml(text.slice(i, i + q.length))}</mark>` +
      escHtml(text.slice(i + q.length))
    );
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  消息渲染
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function appendUserMsg(text) {
    sessionMsgs.push({ role: 'user', text });
    const el = document.createElement('div');
    el.className = 'cmd-msg';
    el.style.cssText = 'display:flex;justify-content:flex-end';
    el.innerHTML = `
      <div style="
        max-width:76%;background:${C.primary};color:#fff;
        border-radius:18px 18px 4px 18px;padding:10px 15px;
        font-size:13px;line-height:1.6;white-space:pre-wrap;word-break:break-all">
        ${escHtml(text)}
      </div>`;
    messagesEl.appendChild(el);
    scrollBottom();
  }

  function appendAssistantMsg(text, payload) {
    sessionMsgs.push({ role: 'assistant', text });
    const el = document.createElement('div');
    el.className = 'cmd-msg';
    el.style.cssText = 'display:flex;align-items:flex-start;gap:10px';

    const formatted = text
      .replace(/\n/g, '<br>')
      .replace(/•/g, `<span style="color:${C.primary}">•</span>`);

    el.innerHTML = `
      <div style="
        width:30px;height:30px;border-radius:50%;background:${C.primaryLight};
        flex-shrink:0;display:flex;align-items:center;justify-content:center;margin-top:2px">
        <svg style="width:15px;height:15px;color:${C.primary}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
               m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
               A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
               c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
        </svg>
      </div>
      <div class="cmd-bubble" style="
        flex:1;max-width:80%;background:#fff;border-radius:4px 18px 18px 18px;
        padding:11px 15px;font-size:13px;line-height:1.6;color:${C.text};
        border:1px solid ${C.border}">
        ${formatted}
      </div>`;

    // 追加结构化数据
    if (payload) {
      const bubble = el.querySelector('.cmd-bubble');
      const { data, navigate_url, execution_id, executed_steps } = payload;

      // 显示执行过程步骤
      if (executed_steps?.length) {
        bubble.insertAdjacentHTML('beforeend', renderSteps(executed_steps));
      }

      // 显示执行结果
      if (data?.success) {
        bubble.insertAdjacentHTML('beforeend', renderSuccess(data));
      } else if (data?.items?.length > 0) {
        bubble.insertAdjacentHTML('beforeend', renderTable(data));
      } else if (data && typeof data === 'object' && !data.items) {
        bubble.insertAdjacentHTML('beforeend', renderKV(data));
      }

      // 跳转按钮（根据 URL 显示语义化标签）
      if (navigate_url) {
        const btnLabel = navigate_url.includes('followup')  ? '查看随访计划 →'
          : navigate_url.includes('guidance')  ? '查看指导记录 →'
          : navigate_url.includes('alert')     ? '查看预警列表 →'
          : navigate_url.includes('archive')   ? '查看患者档案 →'
          : '前往查看 →';
        bubble.insertAdjacentHTML('beforeend', `
          <div style="margin-top:10px">
            <a href="${escHtml(navigate_url)}"
              style="display:inline-block;background:${C.primary};color:#fff;text-decoration:none;
                     border-radius:8px;padding:6px 14px;font-size:12px;font-family:inherit;
                     transition:background .15s"
              onmouseover="this.style.background='${C.primaryDark}'"
              onmouseout="this.style.background='${C.primary}'">
              ${btnLabel}
            </a>
          </div>`);
      }

      if (execution_id) bubble.insertAdjacentHTML('beforeend', `
        <div style="margin-top:8px;font-size:10px;color:#d1d5db">执行记录：${escHtml(execution_id)}</div>`);
    }

    messagesEl.appendChild(el);
    scrollBottom();
    return el;
  }

  function appendLoadingBubble() {
    const el = document.createElement('div');
    el.className = 'cmd-msg';
    el.id = 'cmd-loading-bubble';
    el.style.cssText = 'display:flex;align-items:flex-start;gap:10px';
    el.innerHTML = `
      <div style="
        width:30px;height:30px;border-radius:50%;background:${C.primaryLight};
        flex-shrink:0;display:flex;align-items:center;justify-content:center;margin-top:2px">
        <svg style="width:15px;height:15px;color:${C.primary};animation:cmd-spin 1.2s linear infinite"
             fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9
               m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
      </div>
      <div style="
        background:#fff;border-radius:4px 18px 18px 18px;
        padding:12px 16px;border:1px solid ${C.border};
        display:flex;align-items:center;gap:8px">
        <span style="display:flex;gap:5px;align-items:center">
          <span style="width:7px;height:7px;border-radius:50%;background:${C.primary};
                       animation:cmd-bounce 1.2s ease infinite"></span>
          <span style="width:7px;height:7px;border-radius:50%;background:${C.primary};
                       animation:cmd-bounce 1.2s ease .2s infinite"></span>
          <span style="width:7px;height:7px;border-radius:50%;background:${C.primary};
                       animation:cmd-bounce 1.2s ease .4s infinite"></span>
        </span>
        <span style="font-size:12px;color:#9ca3af">正在思考…</span>
      </div>`;
    messagesEl.appendChild(el);
    scrollBottom();
    return el;
  }

  function scrollBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  流式执行（SSE via fetch ReadableStream）
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  async function submit(query) {
    if (isRequesting) return;
    isRequesting = true;

    saveHistory(query);
    inputEl.value = '';
    inputEl.style.height = 'auto';
    hideSuggestions();
    quickChipsEl.style.display = 'none';

    appendUserMsg(query);

    // 创建流式消息气泡
    const { bubbleEl, textEl, stepsEl } = appendStreamingBubble();

    try {
      const resp = await fetch('/tools/agent/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });

      if (!resp.ok) {
        textEl.innerHTML = '请求失败（HTTP ' + resp.status + '）';
        isRequesting = false;
        renderQuickChips();
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      const stepRows = {};  // tool_name → DOM element

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();  // 保留未完整行

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch { continue; }

          if (ev.type === 'thinking') {
            textEl.innerHTML = '<span style="color:#9ca3af;font-size:12px">正在思考中…</span>';

          } else if (ev.type === 'tool_call') {
            // 创建该工具的步骤行（spinner状态）
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 10px;border-top:1px solid #f3f4f6';
            row.innerHTML = `
              <span style="display:inline-block;width:14px;height:14px;border:2px solid #4E7A61;border-top-color:transparent;border-radius:50%;animation:cmd-spin 0.8s linear infinite;flex-shrink:0"></span>
              <span style="font-size:12px;color:#374151;font-weight:500">${escHtml(ev.label)}</span>
              <span style="font-size:11px;color:#9ca3af;flex:1">调用中…</span>`;
            stepRows[ev.tool] = row;
            stepsEl.appendChild(row);
            stepsEl.parentElement.classList.remove('hidden');
            scrollBottom();

          } else if (ev.type === 'tool_result') {
            // 更新对应步骤行为结果
            const row = stepRows[ev.tool];
            if (row) {
              const icon = ev.status === 'success'
                ? `<span style="color:#16a34a;font-size:14px;flex-shrink:0">✓</span>`
                : `<span style="color:#dc2626;font-size:14px;flex-shrink:0">✗</span>`;
              row.innerHTML = `
                ${icon}
                <span style="font-size:12px;color:#374151;font-weight:500;white-space:nowrap">${escHtml(ev.label)}</span>
                <span style="font-size:11px;color:#9ca3af;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(ev.summary || '')}</span>`;
            }

          } else if (ev.type === 'done') {
            // 渲染最终消息
            const msg = ev.message || '执行完成';
            textEl.innerHTML = msg.replace(/\n/g, '<br>').replace(/•/g, `<span style="color:${C.primary}">•</span>`);

            // 渲染结构化结果（复用已有函数）
            const payload = ev;
            const { data, navigate_url, execution_id } = payload;
            if (data?.success) {
              bubbleEl.insertAdjacentHTML('beforeend', renderSuccess(data));
            } else if (data?.items?.length > 0) {
              bubbleEl.insertAdjacentHTML('beforeend', renderTable(data));
            } else if (data && typeof data === 'object' && !data.items) {
              bubbleEl.insertAdjacentHTML('beforeend', renderKV(data));
            }
            if (navigate_url) {
              const btnLabel = navigate_url.includes('followup') ? '查看随访计划 →'
                : navigate_url.includes('guidance')  ? '查看指导记录 →'
                : navigate_url.includes('alert')     ? '查看预警列表 →'
                : navigate_url.includes('archive')   ? '查看患者档案 →'
                : '前往查看 →';
              bubbleEl.insertAdjacentHTML('beforeend', `
                <div style="margin-top:10px">
                  <a href="${escHtml(navigate_url)}"
                    style="display:inline-block;background:${C.primary};color:#fff;text-decoration:none;
                           border-radius:8px;padding:6px 14px;font-size:12px;font-family:inherit"
                    onmouseover="this.style.background='${C.primaryDark}'"
                    onmouseout="this.style.background='${C.primary}'">${btnLabel}</a>
                </div>`);
            }
            if (execution_id) {
              bubbleEl.insertAdjacentHTML('beforeend', `
                <div style="margin-top:8px;font-size:10px;color:#d1d5db">执行记录：${escHtml(execution_id)}</div>`);
            }
            scrollBottom();

          } else if (ev.type === 'error') {
            textEl.innerHTML = `<span style="color:#dc2626">${escHtml(ev.message || '执行失败')}</span>`;
            scrollBottom();
          }
        }
      }
    } catch (err) {
      textEl.innerHTML = `<span style="color:#dc2626">网络错误：${escHtml(err.message)}</span>`;
    }

    isRequesting = false;
    renderQuickChips();
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  流式气泡（含步骤区）
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function appendStreamingBubble() {
    const el = document.createElement('div');
    el.className = 'cmd-msg';
    el.style.cssText = 'display:flex;align-items:flex-start;gap:10px';
    el.innerHTML = `
      <div style="width:30px;height:30px;border-radius:50%;background:${C.primaryLight};
           flex-shrink:0;display:flex;align-items:center;justify-content:center;margin-top:2px">
        <svg style="width:15px;height:15px;color:${C.primary}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
               m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
               A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
               c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
        </svg>
      </div>
      <div class="cmd-bubble cmd-stream-bubble"
           style="flex:1;max-width:80%;background:#fff;border-radius:4px 18px 18px 18px;
                  padding:11px 15px;font-size:13px;line-height:1.6;color:${C.text};
                  border:1px solid ${C.border}">
        <div class="cmd-stream-text" style="min-height:18px"></div>
        <div class="cmd-steps-wrap hidden" style="margin-top:10px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
          <div style="padding:5px 10px;background:#f9fafb;border-bottom:1px solid #e5e7eb;
                      font-size:11px;color:#6b7280;font-weight:500;letter-spacing:.03em">执行过程</div>
          <div class="cmd-steps-body"></div>
        </div>
      </div>`;
    messagesEl.appendChild(el);
    scrollBottom();
    const bubbleEl  = el.querySelector('.cmd-stream-bubble');
    const textEl    = el.querySelector('.cmd-stream-text');
    const stepsEl   = el.querySelector('.cmd-steps-body');
    return { bubbleEl, textEl, stepsEl };
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  数据表格 / KV / 成功操作
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function renderSuccess(data) {
    const items = [];
    if (data.patient) items.push({ label: '患者', value: data.patient });
    if (data.disease) items.push({ label: '病种', value: data.disease });
    if (data.task_count) items.push({ label: '任务数', value: data.task_count });
    if (data.start_date) items.push({ label: '开始日期', value: data.start_date });
    if (data.end_date) items.push({ label: '结束日期', value: data.end_date });
    if (data.plan_id) items.push({ label: '计划ID', value: data.plan_id.slice(0, 8) + '…' });

    const rows = items.map(({ label, value }) => `
      <div style="display:flex;justify-content:space-between;padding:6px 10px;border-top:1px solid #f3f4f6">
        <span style="color:${C.muted};font-size:12px">${label}</span>
        <span style="font-weight:600;color:#111827;font-size:12px">${escHtml(String(value))}</span>
      </div>`).join('');

    return `
      <div style="margin-top:10px;border:1px solid #dcfce7;border-radius:8px;overflow:hidden;background:#f0fdf4">
        <div style="padding:8px 12px;background:#dcfce7;color:#166534;font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px">
          <svg style="width:14px;height:14px" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
          操作成功
        </div>
        ${rows}
      </div>`;
  }

  function renderSteps(steps) {
    if (!steps || !steps.length) return '';
    const rows = steps.map(s => {
      const icon = s.status === 'success'
        ? `<span style="color:#16a34a;font-size:14px;line-height:1;flex-shrink:0">✓</span>`
        : `<span style="color:#dc2626;font-size:14px;line-height:1;flex-shrink:0">✗</span>`;
      return `
        <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-top:1px solid #f3f4f6">
          ${icon}
          <span style="font-size:12px;color:#374151;font-weight:500;white-space:nowrap">${escHtml(s.label)}</span>
          <span style="font-size:11px;color:#9ca3af;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.summary)}</span>
        </div>`;
    }).join('');
    return `
      <div style="margin-top:10px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
        <div style="padding:5px 10px;background:#f9fafb;border-bottom:1px solid #e5e7eb;
                    font-size:11px;color:#6b7280;font-weight:500;letter-spacing:.03em">
          执行过程
        </div>
        ${rows}
      </div>`;
  }

  function renderTable(data) {
    if (!data.items.length) return '<p style="color:#9ca3af;margin-top:8px;font-size:12px">暂无数据</p>';
    const keys = Object.keys(data.items[0]).filter(k => k !== 'plan_id');
    const LABEL = {
      id: 'ID', name: '姓名', patient: '患者', phone: '手机号',
      is_active: '状态', created_at: '创建时间', severity: '严重程度',
      status: '状态', message: '内容', adherence_rate: '依从率',
      disease: '病种', start_date: '开始日期', end_date: '结束日期', count: '数量',
    };
    const ths  = keys.map(k => `<th style="padding:5px 8px;text-align:left;color:${C.muted};font-weight:500;font-size:10px;white-space:nowrap">${LABEL[k] || k}</th>`).join('');
    const rows = data.items.map(row => {
      const cells = keys.map(k => {
        let v = row[k];
        if (k === 'is_active')    v = v ? '✓ 启用' : '✗ 禁用';
        if (k === 'adherence_rate') v = (v * 100).toFixed(1) + '%';
        if (k === 'severity') {
          const colorMap = { HIGH:'#dc2626', MEDIUM:'#d97706', LOW:'#16a34a' };
          const labelMap = { HIGH:'高危', MEDIUM:'中危', LOW:'低危' };
          v = `<span style="color:${colorMap[v]||'#374151'}">${labelMap[v]||v}</span>`;
        }
        if (k === 'status' && ['OPEN','ACKED','CLOSED'].includes(v)) {
          v = { OPEN:'开放', ACKED:'已确认', CLOSED:'已关闭' }[v];
        }
        if (k === 'id'         && v?.length > 8) v = v.slice(0, 8) + '…';
        if (k === 'created_at' && v)             v = v.slice(0, 16).replace('T', ' ');
        if (v === null || v === undefined) v = '—';
        return `<td style="padding:6px 8px;vertical-align:top;font-size:12px">${v}</td>`;
      }).join('');
      return `<tr style="border-top:1px solid #f3f4f6">${cells}</tr>`;
    }).join('');
    return `
      <div style="margin-top:10px;overflow-x:auto;border-radius:8px;border:1px solid #e5e7eb">
        <div style="padding:6px 10px;background:#f9fafb;border-bottom:1px solid #e5e7eb;font-size:11px;color:${C.muted}">
          共 ${data.count} 条结果
        </div>
        <table style="width:100%;border-collapse:collapse">
          <thead style="background:#f9fafb"><tr>${ths}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function renderKV(data) {
    const LABEL = {
      total_patients:'患者总数', active_patients:'在管患者',
      open_alerts:'开放预警', high_severity_alerts:'高危预警',
      overall_adherence_rate:'整体依从率',
    };
    const rows = Object.entries(data)
      .filter(([k]) => k !== 'items' && k !== 'count')
      .map(([k, v]) => {
        if (typeof v === 'number' && k.includes('rate')) v = (v * 100).toFixed(1) + '%';
        return `<div style="display:flex;justify-content:space-between;padding:6px 10px;border-top:1px solid #f3f4f6">
          <span style="color:${C.muted};font-size:12px">${LABEL[k] || k}</span>
          <span style="font-weight:600;color:#111827;font-size:12px">${v ?? '—'}</span>
        </div>`;
      }).join('');
    return `<div style="margin-top:10px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">${rows}</div>`;
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  工具
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   *  启动
   * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // 暴露给外部点击调用
  window.openCmdPalette = function () { open(); };
})();
