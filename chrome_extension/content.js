/**
 * content.js - 诊中助手内容脚本 v4.0
 * P0 重构：Tab 式 → 一屏四块决策面板 + 抽屉系统 + AI Dock
 */

(function () {
  'use strict';

  // 扩展重载时：旧侧边栏 DOM 留存但事件监听失效，需清理后重新初始化
  if (window.__tcmAssistantInjected) {
    // 移除旧侧边栏，允许本次重新注入
    document.getElementById('tcm-assistant-sidebar')?.remove();
  }
  window.__tcmAssistantInjected = true;

  const SIDEBAR_ID = 'tcm-assistant-sidebar';
  const DEBOUNCE_MS = 600;
  const DEFAULT_PARAM_NAMES = ['patient_id', 'pid', 'id', 'patientId', 'patient'];

  // ─── 状态 ──────────────────────────────────────────────────────────────────
  let currentPatientId    = null;
  let currentPatient      = null;
  let currentContext      = null;
  let currentRisk         = null;
  let currentProfile      = null;
  let currentRiskTags     = null;
  let currentMetrics      = null;
  let currentPlan             = null;
  let currentPlanVersions     = null;
  let currentRiskConclusions  = null;  // AI 风险结论缓存
  let isCollapsed         = false;
  let activeDrawer        = null;
  let drawerFromMap       = {};   // drawerFromMap[drawerId] = parentDrawerId | null
  let drawerLoaderMap     = {};   // drawerLoaderMap[drawerId] = loader fn
  let debounceTimer       = null;
  let confirmPending      = null;  // reserved (unused)
  let serverUrl           = 'http://localhost:8010';

  // 四诊状态（补充采集抽屉）
  let sizhenState = { tongue_color: null, tongue_coating: null, pulse: [], sleep: null, stool: null, urine: null };
  let _sizhenTimer = null;

  // IDE 化状态
  let isDocked    = true;   // 吸附模式 vs 浮动模式
  let panelWidth  = 360;    // 面板宽度（px）
  let isResizing  = false;  // 是否正在拖拽分割线

  // ─── 配置 ──────────────────────────────────────────────────────────────────
  function getConfig() {
    return new Promise((resolve) => {
      chrome.storage.local.get(['serverUrl', 'paramNames', 'sidebarCollapsed', 'isDocked', 'panelWidth'], (r) => {
        const url = r.serverUrl || 'http://localhost:8010';
        serverUrl = url;
        isDocked   = r.isDocked   !== false;   // 默认 true
        panelWidth = r.panelWidth || 360;
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

  // ─── 工具函数 ──────────────────────────────────────────────────────────────
  function esc(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function getRiskBadge(level) {
    const l = (level || '').toUpperCase();
    if (l === 'HIGH')   return { cls: 'tcm-badge-high',   text: '高风险' };
    if (l === 'MEDIUM') return { cls: 'tcm-badge-medium', text: '中风险' };
    if (l === 'LOW')    return { cls: 'tcm-badge-low',    text: '低风险' };
    return { cls: 'tcm-badge-unknown', text: level || '未知' };
  }

  function getSevColor(sev) {
    if (sev === 'HIGH')   return '#D95C4A';
    if (sev === 'MEDIUM') return '#B8885E';
    return '#9A9188';
  }

  function msg(action, payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ action, ...payload }, (resp) => {
        if (chrome.runtime.lastError)
          resolve({ success: false, error: chrome.runtime.lastError.message });
        else resolve(resp);
      });
    });
  }

  // ─── SVG 图标库 ─────────────────────────────────────────────────────────────
  const ICONS = {
    logo:         `<svg class="tcm-icon tcm-icon-lg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22V12"/><path d="M12 12C12 7 8 3 3 3c0 5 3 9 9 9z"/><path d="M12 12c0-5 4-9 9-9c-1 5-4 9-9 9z"/></svg>`,
    user:         `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>`,
    bell:         `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>`,
    chevronLeft:  `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>`,
    chevronRight: `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>`,
    search:       `<svg class="tcm-icon tcm-icon-lg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>`,
    warning:      `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    bolt:         `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>`,
    pin:          `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>`,
    checkCircle:  `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/></svg>`,
    clock:        `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>`,
    clipboard:    `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/></svg>`,
    check:        `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`,
    xMark:        `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>`,
    refresh:      `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>`,
    phone:        `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.07 9.81a19.79 19.79 0 01-3.07-8.72A2 2 0 012 .9h3a2 2 0 012 1.72c.13.96.36 1.9.7 2.81a2 2 0 01-.45 2.11L6.09 8.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0122 16.92z"/></svg>`,
    pen:          `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
    send:         `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`,
    sparkle:      `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/></svg>`,
    // 弹出为浮窗（吸附中显示）
    undock:       `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14L21 3"/><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/></svg>`,
    // 吸附到侧边（浮动中显示）
    dock:         `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="15" y1="3" x2="15" y2="21"/></svg>`,
    chevronDown:  `<svg class="tcm-block-chevron" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>`,
    mic:          `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0014 0"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="9" y1="22" x2="15" y2="22"/></svg>`,
    image:        `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>`,
    volume:       `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14"/><path d="M15.54 8.46a5 5 0 010 7.07"/></svg>`,
    workbench:    `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>`,
    patients:     `<svg class="tcm-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="7" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="18" cy="8" r="2.5"/><path d="M21 20c0-2.8-1.8-5-4-5.5"/></svg>`,
  };

  // 工具名 → 中文标签（Agent 步骤展示用）
  const TOOL_LABELS = {
    get_patient_context:     '获取患者档案',
    get_risk_analysis:       '读取风险分析',
    get_plan_versions:       '查询方案版本',
    get_active_plan:         '获取当前方案',
    create_plan:             '生成干预方案',
    update_plan:             '更新方案内容',
    get_followup_tasks:      '查询随访任务',
    create_followup:         '创建随访任务',
    get_recall_suggestions:  '查询召回建议',
    get_templates:           '获取方案模板',
    search_patients:         '搜索患者',
    get_workbench_info:      '获取工作台信息',
    get_clinical_summary:    '生成临床摘要',
    get_constitution:        '读取体质评估',
    get_scale_records:       '查询量表记录',
    submit_feedback:         '提交医生反馈',
    get_intervention_records:'查询干预记录',
    web_search:              '网页搜索',
  };

  const PLAN_STATES = {
    DRAFT:       { label: '草稿',   color: '#9A9188', icon: ICONS.pen },
    CONFIRMED:   { label: '已确认', color: '#2B6CB0', icon: ICONS.checkCircle },
    DISTRIBUTED: { label: '已分发', color: '#4E7A61', icon: ICONS.bolt },
    PUBLISHED:   { label: '已发布', color: '#4E7A61', icon: ICONS.checkCircle },
    ISSUED:      { label: '已下达', color: '#2B6CB0', icon: ICONS.clipboard },
    IN_PROGRESS: { label: '进行中', color: '#B8885E', icon: ICONS.clock },
    FOLLOWED_UP: { label: '已随访', color: '#6B46C1', icon: ICONS.phone },
    RE_ASSESSED: { label: '已复评', color: '#2C7A7B', icon: ICONS.refresh },
    COMPLETED:   { label: '已完结', color: '#4E7A61', icon: ICONS.checkCircle },
    ADJUSTED:    { label: '已调整', color: '#C05621', icon: ICONS.pen },
    ARCHIVED:    { label: '已归档', color: '#9A9188', icon: ICONS.clipboard },
  };

  // ─── 侧边栏 HTML 骨架 ───────────────────────────────────────────────────────
  function createSidebar() {
    if (document.getElementById(SIDEBAR_ID)) {
      // Extension 重注入后 DOM 已存在但事件未绑定，重新绑定一次
      if (!document.getElementById(SIDEBAR_ID).dataset.bound) {
        bindSidebarEvents();
        document.getElementById(SIDEBAR_ID).dataset.bound = '1';
      }
      return;
    }

    const sidebar = document.createElement('div');
    sidebar.id = SIDEBAR_ID;
    sidebar.className = 'tcm-sidebar';
    sidebar.innerHTML = `
      <!-- 拖拽分割线（吸附模式左边缘）-->
      <div class="tcm-resize-handle" id="tcm-resize-handle"></div>
      <div class="tcm-sidebar-inner">
        <!-- 顶部标题栏 -->
        <div class="tcm-header">
          <div class="tcm-header-left">
            <span class="tcm-logo">${ICONS.logo}</span>
            <span class="tcm-title">诊中助手</span>
            <span class="tcm-header-patient-name" id="tcm-header-patient-name"></span>
          </div>
          <div class="tcm-header-right">
            <button class="tcm-icon-btn" id="tcm-patients-btn" title="患者列表">${ICONS.patients}</button>
            <button class="tcm-icon-btn" id="tcm-workbench-btn" title="工作台">${ICONS.workbench}<span class="tcm-recall-badge" id="tcm-recall-badge"></span></button>
            <button class="tcm-icon-btn" id="tcm-dock-toggle-btn" title="弹出为浮窗">${ICONS.undock}</button>
            <button class="tcm-collapse-btn" id="tcm-collapse-btn" title="收起">${ICONS.chevronRight}</button>
          </div>
        </div>

        <!-- 主内容区：等待 / 加载 / 四块决策面板 -->
        <div class="tcm-dashboard" id="tcm-dashboard">
          <div class="tcm-idle" id="tcm-idle-state">
            <div class="tcm-idle-icon">${ICONS.search}</div>
            <p>等待检测患者信息…</p>
            <p class="tcm-hint">请在HIS系统中打开含患者ID参数的页面</p>
          </div>
        </div>

        <!-- 底部 AI Dock -->
        <div class="tcm-ai-dock" id="tcm-ai-dock" style="display:none;">
          <div class="tcm-ai-chips" id="tcm-ai-chips">
            <button class="tcm-chip" data-chip="risk">查风险</button>
            <button class="tcm-chip" data-chip="plan">方案</button>
            <button class="tcm-chip" data-chip="followup">随访</button>
            <button class="tcm-chip" data-chip="recall">召回</button>
            <button class="tcm-chip" data-chip="summary">临床摘要</button>
          </div>
          <div class="tcm-ai-input-row">
            <textarea class="tcm-ai-input" id="tcm-ai-input" rows="3" placeholder="输入指令，如：生成方案草稿…\nShift+Enter 换行，Enter 发送"></textarea>
            <div style="display:flex;flex-direction:column;gap:4px;align-items:center;">
              <button class="tcm-ai-send-btn" id="tcm-ai-send-btn" title="发送（Enter）">${ICONS.send}</button>
              <button class="tcm-ai-tool-btn" id="tcm-ai-mic-btn" title="语音输入">${ICONS.mic}</button>
              <button class="tcm-ai-tool-btn" id="tcm-ai-img-btn" title="上传图片（OCR）">${ICONS.image}</button>
              <input type="file" id="tcm-ai-img-input" accept="image/*" style="display:none;" />
            </div>
          </div>
          <div id="tcm-ai-img-preview-row" style="display:none;"></div>
          <div class="tcm-ai-response" id="tcm-ai-response" style="display:none;"></div>
        </div>
      </div>

      <!-- 折叠手柄 -->
      <div class="tcm-collapsed-bar" id="tcm-collapsed-bar">
        <span class="tcm-expand-arrow">${ICONS.chevronLeft}</span>
        <span class="tcm-collapsed-label">诊中</span>
      </div>

      <!-- 抽屉层（overlay 方式，叠在 inner 上方） -->
      ${makeDrawerHtml('tcm-drawer-clinical',  '关键提醒')}
      ${makeDrawerHtml('tcm-drawer-evidence',  '风险证据链')}
      ${makeDrawerHtml('tcm-drawer-plan',      '方案管理')}
      ${makeDrawerHtml('tcm-drawer-preview',   '方案预览与分发')}
      ${makeDrawerHtml('tcm-drawer-supplement', '补充采集信息')}
      ${makeDrawerHtml('tcm-drawer-followup',  '随访管理')}
      ${makeDrawerHtml('tcm-drawer-recall',    '召回建议')}
      ${makeDrawerHtml('tcm-drawer-workbench', '工作台')}
      ${makeDrawerHtml('tcm-drawer-patients',  '患者列表')}

    `;

    document.body.appendChild(sidebar);

    // 恢复上次拖拽位置（仅浮动模式）
    chrome.storage.local.get(['sidebarLeft', 'sidebarTop'], (r) => {
      if (!isDocked && r.sidebarLeft && r.sidebarTop) {
        sidebar.style.setProperty('right', 'auto', 'important');
        sidebar.style.setProperty('left',  r.sidebarLeft, 'important');
        sidebar.style.setProperty('top',   r.sidebarTop,  'important');
      }
    });

    makeDraggable(sidebar);
    bindSidebarEvents();
    sidebar.dataset.bound = '1';
  }

  // ─── 拖拽逻辑 ──────────────────────────────────────────────────────────────
  function makeDraggable(sidebar) {
    const header = sidebar.querySelector('.tcm-header');
    if (!header) return;

    let dragging  = false;
    let startMX, startMY, startLeft, startTop;

    header.addEventListener('mousedown', (e) => {
      // 点到按钮时不触发拖拽；吸附模式下禁用拖拽
      if (e.target.closest('.tcm-header-right')) return;
      if (isDocked) return;
      dragging = true;
      sidebar.classList.add('tcm-dragging');

      // 如果当前是 right 定位，先换算成 left（需要 !important 覆盖 CSS 基础样式）
      const rect = sidebar.getBoundingClientRect();
      startLeft = rect.left;
      startTop  = rect.top;
      sidebar.style.setProperty('right', 'auto', 'important');
      sidebar.style.setProperty('left',  startLeft + 'px', 'important');
      sidebar.style.setProperty('top',   startTop  + 'px', 'important');

      startMX = e.clientX;
      startMY = e.clientY;
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const newLeft = startLeft + (e.clientX - startMX);
      const newTop  = startTop  + (e.clientY - startMY);
      // 限制在视口内
      const maxLeft = window.innerWidth  - sidebar.offsetWidth;
      const maxTop  = window.innerHeight - 60;
      sidebar.style.setProperty('left', Math.max(0, Math.min(newLeft, maxLeft)) + 'px', 'important');
      sidebar.style.setProperty('top',  Math.max(0, Math.min(newTop,  maxTop))  + 'px', 'important');
    });

    document.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      sidebar.classList.remove('tcm-dragging');
      // 持久化位置
      chrome.storage.local.set({
        sidebarLeft: sidebar.style.left,
        sidebarTop:  sidebar.style.top,
      });
    });
  }

  // ─── 吸附/浮动模式 ─────────────────────────────────────────────────────────
  function applyBodyMargin() {
    // 通过 inline style 设置过渡，避免污染 HIS 页全局 body CSS
    document.body.style.transition = 'margin-right 0.25s ease';
    if (isDocked && !isCollapsed) {
      // 吸附展开：页面右侧让出 panelWidth 空间
      document.body.style.setProperty('margin-right', panelWidth + 'px', 'important');
    } else {
      // 收起（悬浮图标）或浮动模式：不占用页面空间
      document.body.style.removeProperty('margin-right');
      document.body.style.transition = '';
    }
  }

  function enterDockedMode() {
    isDocked = true;
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (!sidebar) return;
    sidebar.classList.add('tcm-docked');
    sidebar.classList.remove('tcm-floating');
    if (!isCollapsed) {
      // 清除浮动时设置的 inline !important，让 .tcm-docked CSS 接管 right/top
      sidebar.style.removeProperty('left');
      sidebar.style.removeProperty('top');
      sidebar.style.removeProperty('right');
      sidebar.style.removeProperty('transform');
      sidebar.style.removeProperty('height');
      // 宽度需覆盖 CSS 基础的 width: 320px !important
      sidebar.style.setProperty('width', panelWidth + 'px', 'important');
    }
    applyBodyMargin();
  }

  function enterFloatingMode() {
    isDocked = false;
    document.body.style.removeProperty('margin-right');
    document.body.style.transition = '';
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (!sidebar) return;
    sidebar.classList.remove('tcm-docked');
    sidebar.classList.add('tcm-floating');
    if (!isCollapsed) {
      // 浮动位置需覆盖 CSS 基础的 !important 规则
      sidebar.style.setProperty('right', '20px', 'important');
      sidebar.style.setProperty('top',   '80px', 'important');
      sidebar.style.removeProperty('left');
      sidebar.style.removeProperty('transform');
      sidebar.style.removeProperty('height');
      sidebar.style.setProperty('width', panelWidth + 'px', 'important');
    }
  }

  function updateDockToggleIcon() {
    const btn = document.getElementById('tcm-dock-toggle-btn');
    if (!btn) return;
    if (isDocked) {
      btn.innerHTML = ICONS.undock;
      btn.title     = '弹出为浮窗';
    } else {
      btn.innerHTML = ICONS.dock;
      btn.title     = '吸附到侧边';
    }
  }

  // ─── 分割线拖拽 ────────────────────────────────────────────────────────────
  function bindResizeHandle() {
    const handle = document.getElementById('tcm-resize-handle');
    if (!handle) return;
    handle.addEventListener('mousedown', (e) => {
      if (!isDocked) return;
      isResizing = true;
      handle.classList.add('tcm-resizing');
      document.addEventListener('mousemove', onResize);
      document.addEventListener('mouseup',   stopResize);
      // 鼠标拖出浏览器窗口再松手时也能清理
      window.addEventListener('blur', stopResize, { once: true });
      e.preventDefault();
    });
  }

  function onResize(e) {
    if (!isResizing || !isDocked) return;
    const newWidth = window.innerWidth - e.clientX;
    panelWidth = Math.max(280, Math.min(700, newWidth));
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (sidebar) sidebar.style.setProperty('width', panelWidth + 'px', 'important');
    applyBodyMargin();
  }

  function stopResize() {
    if (!isResizing) return;
    isResizing = false;
    const handle = document.getElementById('tcm-resize-handle');
    if (handle) handle.classList.remove('tcm-resizing');
    document.removeEventListener('mousemove', onResize);
    document.removeEventListener('mouseup',   stopResize);
    window.removeEventListener('blur', stopResize);
    chrome.storage.local.set({ panelWidth });
  }

  // ─── 块折叠/展开（箭头旋转由纯 CSS 控制）─────────────────────────────────
  function toggleBlock(headerEl) {
    const block = headerEl.closest('.tcm-block');
    if (!block) return;
    block.classList.toggle('tcm-block-folded');
  }

  function makeDrawerHtml(id, title) {
    return `
      <div class="tcm-drawer-overlay" id="${id}" style="display:none;">
        <div class="tcm-drawer">
          <div class="tcm-drawer-header">
            <button class="tcm-drawer-back" data-back-for="${id}" style="display:none" title="返回上一页">←</button>
            <span class="tcm-drawer-title">${title}</span>
            <button class="tcm-drawer-close" data-drawer="${id}">×</button>
          </div>
          <div class="tcm-drawer-body" id="${id}-body">
            <div class="tcm-loading-sm">加载中…</div>
          </div>
        </div>
      </div>`;
  }

  // ─── 患者列表 Hover 浮窗 ────────────────────────────────────────────────────
  function initPatientHoverPopup() {
    const btn = document.getElementById('tcm-patients-btn');
    if (!btn) return;

    // 创建浮窗 DOM，挂在 sidebar 上（sidebar 是 position:fixed 祖先）
    const popup = document.createElement('div');
    popup.id = 'tcm-patients-popup';
    popup.className = 'tcm-patients-popup';
    popup.innerHTML = `
      <div class="tcm-popup-header">患者列表</div>
      <div class="tcm-patient-list-search" style="padding:0 8px 8px">
        <input type="text" id="tcm-popup-search-input" class="tcm-input" placeholder="搜索姓名、手机号…" autocomplete="off" />
      </div>
      <div id="tcm-popup-list" style="overflow-y:auto;flex:1"><div class="tcm-loading-sm">加载中…</div></div>
    `;
    document.getElementById(SIDEBAR_ID).appendChild(popup);

    let loaded = false;
    let hideTimer = null;
    let searchTimer = null;
    let allPatients = [];

    function showPopup() {
      clearTimeout(hideTimer);
      popup.style.display = 'flex';
      if (!loaded) { loaded = true; loadPopupPatients(); }
    }
    function hidePopup() {
      hideTimer = setTimeout(() => { popup.style.display = 'none'; }, 180);
    }

    btn.addEventListener('mouseenter', showPopup);
    btn.addEventListener('mouseleave', hidePopup);
    popup.addEventListener('mouseenter', () => clearTimeout(hideTimer));
    popup.addEventListener('mouseleave', hidePopup);

    async function loadPopupPatients() {
      const listEl = document.getElementById('tcm-popup-list');
      const r = await msg('patientSearch', { keyword: '', pageSize: 50 });
      if (r?.success && r.data?.items) {
        allPatients = r.data.items;
        renderPopupList(allPatients);
      } else if (listEl) {
        listEl.innerHTML = '<p class="tcm-hint" style="padding:8px">加载失败，请确认已登录</p>';
      }
    }

    function renderPopupList(list) {
      const listEl = document.getElementById('tcm-popup-list');
      if (!listEl) return;
      if (!list.length) { listEl.innerHTML = '<p class="tcm-hint" style="padding:8px">未找到匹配患者</p>'; return; }
      listEl.innerHTML = list.slice(0, 40).map(p => `
        <div class="tcm-pl-card" data-archive-id="${esc(p.patient_id||p.archive_id)}" data-name="${esc(p.name)}">
          <div class="tcm-pl-name">${esc(p.name)}
            ${p.archive_type ? `<span class="tcm-pl-type">${esc(p.archive_type)}</span>` : ''}
            ${(p.patient_id||p.archive_id) === currentPatient?.archive_id ? '<span class="tcm-pl-current">当前</span>' : ''}
          </div>
          <div class="tcm-pl-meta">
            ${p.gender ? `<span>${p.gender === 'male' ? '男' : '女'}</span>` : ''}
            ${p.age ? `<span>${p.age}岁</span>` : ''}
            ${p.phone ? `<span>${esc(p.phone)}</span>` : ''}
          </div>
        </div>`).join('');

      listEl.querySelectorAll('.tcm-pl-card').forEach(card => {
        card.addEventListener('click', () => {
          const archiveId = card.dataset.archiveId;
          if (!archiveId) return;
          popup.style.display = 'none';
          currentPatientId = archiveId;
          renderLoading(archiveId);
          sendMsgWithTimeout(
            'patientDetected', { patientId: archiveId },
            (response) => {
              if (response.error) { renderError(response.error); return; }
              renderResult(response.patient, response.context, response.risk, response.warning);
            },
            (errMsg) => renderError(errMsg)
          );
        });
      });
    }

    document.getElementById('tcm-popup-search-input')?.addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      if (!q) { renderPopupList(allPatients); return; }
      searchTimer = setTimeout(async () => {
        const local = allPatients.filter(p => p.name?.includes(q) || p.phone?.includes(q) || p.id_number?.includes(q));
        if (local.length) { renderPopupList(local); return; }
        const sr = await msg('patientSearch', { keyword: q, pageSize: 20 });
        renderPopupList(sr?.data?.items || []);
      }, 300);
    });
  }

  function bindSidebarEvents() {
    document.getElementById('tcm-collapse-btn').addEventListener('click', toggleSidebar);
    document.getElementById('tcm-collapsed-bar').addEventListener('click', toggleSidebar);

    // 工作台 & 患者列表 header 按钮
    document.getElementById('tcm-workbench-btn').addEventListener('click', () => openDrawer('tcm-drawer-workbench', loadWorkbenchDrawer));
    initPatientHoverPopup();

    // 吸附/浮动切换
    document.getElementById('tcm-dock-toggle-btn').addEventListener('click', () => {
      if (isDocked) enterFloatingMode();
      else          enterDockedMode();
      chrome.storage.local.set({ isDocked });
      updateDockToggleIcon();
    });

    // 统一抽屉关闭
    document.getElementById(SIDEBAR_ID).addEventListener('click', (e) => {
      const closeBtn = e.target.closest('[data-drawer]');
      if (closeBtn) { closeDrawer(closeBtn.dataset.drawer); return; }
      const backBtn = e.target.closest('[data-back-for]');
      if (backBtn) goBackDrawer(backBtn.dataset.backFor);
    });

    // AI dock chips
    document.getElementById('tcm-ai-chips').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-chip]');
      if (!btn) return;
      handleChip(btn.dataset.chip);
    });

    // AI dock send
    document.getElementById('tcm-ai-send-btn').addEventListener('click', handleAiSend);
    document.getElementById('tcm-ai-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAiSend(); }
    });

    // AI dock mic
    document.getElementById('tcm-ai-mic-btn').addEventListener('click', startVoiceInput);

    // AI dock image upload
    document.getElementById('tcm-ai-img-btn').addEventListener('click', () => {
      document.getElementById('tcm-ai-img-input').click();
    });
    document.getElementById('tcm-ai-img-input').addEventListener('change', handleImageUpload);
  }

  // ─── 抽屉管理 ───────────────────────────────────────────────────────────────
  function openDrawer(drawerId, loader, fromDrawer) {
    // 关闭其他抽屉
    document.querySelectorAll('#' + SIDEBAR_ID + ' .tcm-drawer-overlay').forEach(el => {
      el.style.display = 'none';
    });
    activeDrawer = drawerId;
    // 记录来源抽屉和 loader
    drawerFromMap[drawerId]   = fromDrawer || null;
    drawerLoaderMap[drawerId] = loader     || null;
    const overlay = document.getElementById(drawerId);
    if (!overlay) return;
    overlay.style.display = 'flex';
    // 更新返回按钮
    const backBtn = overlay.querySelector('.tcm-drawer-back');
    if (backBtn) {
      const parent = fromDrawer;
      if (parent) {
        // 取父抽屉标题作为按钮文字
        const parentEl    = document.getElementById(parent);
        const parentTitle = parentEl?.querySelector('.tcm-drawer-title')?.textContent || '返回';
        backBtn.textContent = `← ${parentTitle}`;
      } else {
        backBtn.textContent = '← 返回';
      }
      backBtn.style.display = 'inline-flex';   // 始终显示返回按钮
    }
    if (loader) loader();
  }

  function closeDrawer(drawerId) {
    const overlay = document.getElementById(drawerId);
    if (overlay) overlay.style.display = 'none';
    if (activeDrawer === drawerId) activeDrawer = null;
  }

  function goBackDrawer(drawerId) {
    const parentId = drawerFromMap[drawerId];
    const overlay  = document.getElementById(drawerId);
    if (overlay) overlay.style.display = 'none';
    activeDrawer = null;
    if (parentId) {
      const parentLoader = drawerLoaderMap[parentId] || null;
      openDrawer(parentId, parentLoader, drawerFromMap[parentId]);
    }
  }

  // ─── 收起/展开 ──────────────────────────────────────────────────────────────
  function toggleSidebar() {
    isCollapsed = !isCollapsed;
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (!sidebar) return;
    if (isCollapsed) {
      sidebar.classList.add('tcm-collapsed');
      // 覆盖吸附模式的 top:0 / height:100vh，变为居中小标签
      sidebar.style.setProperty('top', '50%', 'important');
      sidebar.style.setProperty('height', '92px', 'important');
      sidebar.style.setProperty('transform', 'translateY(-50%)', 'important');
      sidebar.style.setProperty('width', '36px', 'important');
    } else {
      sidebar.classList.remove('tcm-collapsed');
      // 恢复吸附/浮动各自的布局
      sidebar.style.removeProperty('top');
      sidebar.style.removeProperty('height');
      sidebar.style.removeProperty('transform');
      sidebar.style.removeProperty('width');
      if (isDocked) enterDockedMode();
      else          enterFloatingMode();
    }
    chrome.storage.local.set({ sidebarCollapsed: isCollapsed });
    applyBodyMargin();
  }

  // ─── 四块决策面板 ────────────────────────────────────────────────────────────

  function renderDashboard() {
    const dash = document.getElementById('tcm-dashboard');
    if (!dash) return;

    const patient = currentPatient;

    // 在标题栏显示当前患者姓名
    const nameEl = document.getElementById('tcm-header-patient-name');
    if (nameEl) nameEl.textContent = patient?.name || '';

    dash.innerHTML = `
      <!-- 四块决策区 -->
      <div class="tcm-blocks-grid">

        <!-- Block A: 关键提醒 -->
        <div class="tcm-block tcm-block-a" id="tcm-block-a">
          <div class="tcm-block-header" data-collapse-header>
            <span class="tcm-block-icon tcm-block-icon-red">${ICONS.warning}</span>
            <span class="tcm-block-title">关键提醒</span>
            <button class="tcm-block-expand" data-block="a">详情</button>
            ${ICONS.chevronDown}
          </div>
          <div class="tcm-block-body" id="tcm-block-a-body">
            <div class="tcm-block-skeleton"></div>
          </div>
        </div>

        <!-- Block B: 体质/风险结论 -->
        <div class="tcm-block tcm-block-b" id="tcm-block-b">
          <div class="tcm-block-header" data-collapse-header>
            <span class="tcm-block-icon tcm-block-icon-amber">${ICONS.bolt}</span>
            <span class="tcm-block-title">体质/风险</span>
            <button class="tcm-block-expand" data-block="b">详情</button>
            ${ICONS.chevronDown}
          </div>
          <div class="tcm-block-body" id="tcm-block-b-body">
            <div class="tcm-block-skeleton"></div>
          </div>
        </div>

        <!-- Block C: 方案状态 -->
        <div class="tcm-block tcm-block-c" id="tcm-block-c">
          <div class="tcm-block-header" data-collapse-header>
            <span class="tcm-block-icon tcm-block-icon-green">${ICONS.clipboard}</span>
            <span class="tcm-block-title">方案状态</span>
            <button class="tcm-block-expand" data-block="c">详情</button>
            ${ICONS.chevronDown}
          </div>
          <div class="tcm-block-body" id="tcm-block-c-body">
            <div class="tcm-block-skeleton"></div>
          </div>
        </div>

        <!-- Block D: 复评/召回 -->
        <div class="tcm-block tcm-block-d" id="tcm-block-d">
          <div class="tcm-block-header" data-collapse-header>
            <span class="tcm-block-icon tcm-block-icon-blue">${ICONS.refresh}</span>
            <span class="tcm-block-title">复评/召回</span>
            <button class="tcm-block-expand" data-block="d">详情</button>
            ${ICONS.chevronDown}
          </div>
          <div class="tcm-block-body" id="tcm-block-d-body">
            <div class="tcm-block-skeleton"></div>
          </div>
        </div>

      </div>
    `;

    // 绑定展开按钮（打开抽屉）
    dash.querySelectorAll('[data-block]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();  // 阻止冒泡到折叠头部
        const b = btn.dataset.block;
        if (b === 'a') openDrawer('tcm-drawer-clinical',  loadClinicalDrawer);
        if (b === 'b') openDrawer('tcm-drawer-evidence',  loadEvidenceDrawer);
        if (b === 'c') openDrawer('tcm-drawer-plan',      loadPlanDrawer);
        if (b === 'd') openDrawer('tcm-drawer-followup',  loadFollowupDrawer);
      });
    });

    // 绑定块折叠（点击标题栏，跳过展开按钮）
    dash.querySelectorAll('[data-collapse-header]').forEach(header => {
      header.addEventListener('click', (e) => {
        if (e.target.closest('.tcm-block-expand')) return;
        toggleBlock(header);
      });
    });

    // 顺序加载四块数据（从上至下依次生成）
    (async () => {
      await loadBlockA();
      await loadBlockB();
      await loadBlockC();
      await loadBlockD();
    })();

    // 显示 AI dock
    const dock = document.getElementById('tcm-ai-dock');
    if (dock) dock.style.display = 'flex';

    // 更新工作台召回徽章
    msg('getRecallSuggestions', { patient_id: patient.archive_id }).then(resp => {
      const total = resp?.success ? (resp.data?.total || 0) : 0;
      const badge = document.getElementById('tcm-recall-badge');
      if (badge) badge.textContent = total > 0 ? String(total) : '';
    });
  }

  // Block A: 关键提醒（分类：过敏史 / 禁忌 / 共病 / 近期异常指标 / 依从性）
  async function loadBlockA() {
    if (!currentProfile || !currentRiskTags) {
      const [pResp, tResp] = await Promise.all([
        msg('getPatientProfile', { patient_id: currentPatient.archive_id }),
        msg('getRiskTags',       { patient_id: currentPatient.archive_id }),
      ]);
      if (pResp?.success) currentProfile  = pResp.data;
      if (tResp?.success) currentRiskTags = tResp.data;
    }

    const body = document.getElementById('tcm-block-a-body');
    if (!body) return;

    const ka = currentRiskTags?.key_alerts || {};

    // ── 帮助函数 ──────────────────────────────────────────────────────────
    function makeCategory(icon, label, levelCls, items) {
      if (!items.length) return '';
      return `
        <div class="tcm-ka-group">
          <div class="tcm-ka-label tcm-ka-label-${levelCls}">${icon} ${label}</div>
          ${items.map(text => `
            <div class="tcm-ka-item tcm-alert-${levelCls}">
              <span class="tcm-alert-dot"></span>
              <span class="tcm-alert-text">${esc(text)}</span>
            </div>`).join('')}
        </div>`;
    }

    // ── 1. 过敏史 ──────────────────────────────────────────────────────
    const allergyItems = (ka.allergy || []).filter(Boolean);

    // ── 2. 禁忌 ────────────────────────────────────────────────────────
    const contraItems = (ka.contraindications || []).map(c =>
      c.disease ? `[${c.disease}] ${c.item}` : c.item
    );

    // ── 3. 共病 ────────────────────────────────────────────────────────
    const comorbItems = (ka.comorbidities || []).map(c =>
      `${c.disease} → ${c.complication}`
    );

    // ── 4. 近期异常指标（HIGH+MEDIUM 合并一组，各自配色）──────────────
    const indicatorAlerts = ka.indicator_alerts || currentRiskTags?.alert_tags || [];
    const indItems = indicatorAlerts.slice(0, 4).map(a => ({
      level: a.severity === 'HIGH' ? 'high' : 'med',
      text:  (a.message || '').replace(/^⚠️\s*[危急提示：]*/u, '').trim(),
    })).filter(i => i.text);
    const indGroupHtml = indItems.length ? `
      <div class="tcm-ka-group">
        <div class="tcm-ka-label tcm-ka-label-${indItems[0].level}">↑ 近期异常指标</div>
        ${indItems.map(i => `
          <div class="tcm-ka-item tcm-alert-${i.level}">
            <span class="tcm-alert-dot"></span>
            <span class="tcm-alert-text">${esc(i.text)}</span>
          </div>`).join('')}
      </div>` : '';

    // ── 5. 依从性风险 ────────────────────────────────────────────────
    const adh = ka.adherence;
    const adhItems = adh
      ? [`${adh.text}（完成 ${adh.done_count}/${adh.total_count} 项）`]
      : [];
    const adhLevel = adh?.risk_level === 'HIGH' ? 'high' : (adh?.risk_level === 'MEDIUM' ? 'med' : 'ok');

    // ── 渲染 ──────────────────────────────────────────────────────────
    const html = [
      makeCategory('⚠', '过敏史',      'high', allergyItems),
      makeCategory('⊘', '用药禁忌',    'high', contraItems.slice(0, 4)),
      makeCategory('◉', '共病/并发症', 'med',  comorbItems),
      indGroupHtml,
      makeCategory('⊡', '依从性风险',  adhLevel, adhItems),
    ].filter(Boolean).join('');

    body.innerHTML = html || `
      <div class="tcm-alert-item tcm-alert-ok">
        <span class="tcm-alert-dot"></span>
        <span class="tcm-alert-text">暂无关键提醒</span>
      </div>`;
  }

  // Block B: 体质/风险结论
  async function loadBlockB() {
    const body = document.getElementById('tcm-block-b-body');
    if (!body) return;

    const p    = currentProfile || {};

    // 优先使用旧 risk 分析；若无，从 risk-tags 合成
    let risk = currentRisk;
    if (!risk && currentRiskTags) {
      const rt = currentRiskTags;
      risk = {
        risk_level:       rt.inferred_risk_level || 'MEDIUM',
        risk_topic:       (rt.disease_tags || []).join('、'),
        evidence_summary: (rt.alert_tags || [])[0]?.message?.replace(/^⚠️\s*/, '').slice(0, 60) || '',
      };
    }

    // 合并标签：疾病标签 + 人工标签
    const rawTags = Array.isArray(currentRiskTags) ? currentRiskTags
      : [...(currentRiskTags?.disease_tags || []), ...(currentRiskTags?.manual_tags || [])];
    const tags = rawTags;

    // 无任何数据时才显示 loading
    if (!risk) {
      body.innerHTML = `
        <div class="tcm-b-no-risk">
          <span class="tcm-hint">风险数据加载中…</span>
          <button class="tcm-btn tcm-btn-secondary tcm-btn-xs" id="tcm-reanalyze-btn">重新分析</button>
          <button class="tcm-btn tcm-btn-accent tcm-btn-xs" id="tcm-supplement-btn">补充信息</button>
        </div>`;
      document.getElementById('tcm-supplement-btn')?.addEventListener('click', () =>
        openDrawer('tcm-drawer-supplement', loadSupplementDrawer));
      document.getElementById('tcm-reanalyze-btn')?.addEventListener('click', async () => {
        body.innerHTML = '<div class="tcm-block-skeleton"></div>';
        const resp = await msg('getRiskResult', { patient_id: currentPatient.archive_id });
        if (resp?.success && resp.data) {
          currentRisk = resp.data;
          loadBlockB();
          loadBlockA();
        } else {
          body.innerHTML = '<span class="tcm-hint">暂无风险评估，请先完成体质评估</span>';
        }
      });
      return;
    }

    // 体质：主体质 + 伴随体质（secondary_types）
    const constMain = p.constitution?.main_type_cn || p.constitution_type || '';
    const constSec  = p.constitution?.secondary_types || [];
    let constitutionHtml = '';
    if (constMain) {
      const secHtml = constSec.length
        ? `<div class="tcm-b-const-row">
             <span class="tcm-const-label tcm-const-label-sec">伴</span>
             ${constSec.map(s => `<span class="tcm-mini-tag tcm-tag-constitution-sec">${esc(typeof s === 'object' ? (s.type_cn || s.type || '') : s)}</span>`).join('')}
           </div>`
        : '';
      constitutionHtml = `
        <div class="tcm-b-const-row">
          <span class="tcm-const-label tcm-const-label-main">主</span>
          <span class="tcm-mini-tag tcm-tag-constitution">${esc(constMain)}</span>
        </div>
        ${secHtml}`;
    } else {
      constitutionHtml = '<span class="tcm-hint">暂无体质数据</span>';
    }

    // 读取确认状态（存 chrome.storage.local，key 带 patient_id）
    const pid = currentPatient?.archive_id || '';
    const storageKey = `tcm_confirmed_${pid}`;
    const storedState = await new Promise(res =>
      chrome.storage.local.get([storageKey], r => res(r[storageKey] || {}))
    );
    const constConfirmed = storedState.constitution || false;
    const riskConfirmed  = storedState.risk || false;

    // 整体风险等级来源
    const riskLevelSrc = risk.risk_level || currentRiskTags?.inferred_risk_level || 'MEDIUM';
    const { cls, text: riskText } = getRiskBadge(riskLevelSrc);

    body.innerHTML = `
      <div class="tcm-b-sub-area">
        <div class="tcm-b-sub-title">体质结论
          ${constConfirmed
            ? '<span class="tcm-inline-confirmed" title="已确认">✓</span>'
            : `<button class="tcm-inline-confirm-icon" id="tcm-confirm-constitution-btn" title="点击确认体质">${ICONS.checkCircle}</button>`}
        </div>
        ${constitutionHtml}
      </div>
      <div class="tcm-b-sub-area" style="margin-top:8px">
        <div class="tcm-b-sub-title">风险提示
          ${riskConfirmed
            ? '<span class="tcm-inline-confirmed" title="已确认">✓</span>'
            : `<button class="tcm-inline-confirm-icon" id="tcm-confirm-risk-btn" title="点击确认风险">${ICONS.checkCircle}</button>`}
        </div>
        <div class="tcm-b-risk-row" style="margin-bottom:6px">
          <span class="tcm-badge ${cls}">${riskText}</span>
        </div>
        <div class="tcm-b-conclusion-label">风险结论</div>
        <div class="tcm-rc-chips" id="tcm-rc-chips">
          <span class="tcm-rc-loading">AI 分析中…</span>
        </div>
        ${risk.patient_talk_track
          ? `<div class="tcm-b-talktrack">"${esc(risk.patient_talk_track.slice(0, 50))}…"</div>`
          : ''}
      </div>
      <div class="tcm-b-supplement-hint">
        <button class="tcm-b-supplement-link" id="tcm-supplement-btn-b">补充舌脉/睡眠/食欲/二便</button>
        <span class="tcm-b-supplement-tip">可优化辨体和调理建议</span>
      </div>
    `;

    document.getElementById('tcm-supplement-btn-b')?.addEventListener('click', () =>
      openDrawer('tcm-drawer-supplement', loadSupplementDrawer));

    document.getElementById('tcm-confirm-constitution-btn')?.addEventListener('click', async () => {
      chrome.storage.local.set({ [storageKey]: { ...storedState, constitution: true } });
      showToast('体质已确认', 'success');
      await loadBlockB();
    });

    document.getElementById('tcm-confirm-risk-btn')?.addEventListener('click', async () => {
      chrome.storage.local.set({ [storageKey]: { ...storedState, risk: true } });
      showToast('风险已确认', 'success');
      await loadBlockB();
    });

    // ── 异步加载 AI 风险结论（不阻塞主渲染）──────────────────────────────
    const chipsEl = document.getElementById('tcm-rc-chips');
    if (chipsEl) {
      (async () => {
        // 级别 → CSS 类
        const lvClass = { high: 'tcm-rc-high', medium: 'tcm-rc-medium', low: 'tcm-rc-low' };
        const lvOrder = { high: 0, medium: 1, low: 2 };

        // 从 risk.risk_factors 合成降级 chips
        const buildFallbackChips = () => {
          const factors = risk.risk_factors || [];
          if (!factors.length) return null;
          return factors.slice(0, 5).map(f => {
            const lv = /严重|极高|HH|↑↑/.test(f) ? 'high'
                     : /偏高|偏低|异常|并存|高血压|糖尿病/.test(f) ? 'medium' : 'low';
            // 智能提取短标签："X偏高/偏低" 或 去括号后前10字
            const match = f.match(/^(.{2,6}?)\s*(偏高|偏低|异常|偏多|偏少)/);
            const label = match
              ? (match[1].trim() + match[2])
              : f.replace(/（[^）]*）/g, '').replace(/\([^)]*\)/g, '').trim().slice(0, 10);
            return { label, category: '综合', level: lv };
          });
        };

        const renderChips = (conclusions) => {
          const el = document.getElementById('tcm-rc-chips');
          if (!el) return;
          if (!conclusions || !conclusions.length) {
            el.innerHTML = '<span class="tcm-rc-empty">暂无风险结论</span>';
            return;
          }
          const sorted = [...conclusions].sort(
            (a, b) => (lvOrder[a.level] ?? 2) - (lvOrder[b.level] ?? 2)
          );
          el.innerHTML = sorted.map(c =>
            `<span class="tcm-rc-chip ${lvClass[c.level] || 'tcm-rc-medium'}" title="${esc(c.category)}">${esc(c.label)}</span>`
          ).join('');
        };

        // 若已缓存，直接渲染
        if (currentRiskConclusions) {
          renderChips(currentRiskConclusions);
          return;
        }

        // 带 5s 超时的 API 调用
        let timedOut = false;
        const timeoutId = setTimeout(() => {
          timedOut = true;
          const fallback = buildFallbackChips();
          const el = document.getElementById('tcm-rc-chips');
          if (el && el.querySelector('.tcm-rc-loading')) {
            if (fallback) {
              renderChips(fallback);
            } else {
              el.innerHTML = '<span class="tcm-rc-empty">暂无风险结论</span>';
            }
          }
        }, 5000);

        const resp = await msg('getRiskConclusions', { patient_id: currentPatient.archive_id });
        clearTimeout(timeoutId);
        if (timedOut) return;   // 已由超时处理

        if (resp?.success && Array.isArray(resp.data?.conclusions) && resp.data.conclusions.length) {
          currentRiskConclusions = resp.data.conclusions;
          renderChips(currentRiskConclusions);
        } else {
          // API 失败或无数据 → 降级用 risk_factors
          const fallback = buildFallbackChips();
          renderChips(fallback);
        }
      })();
    }
  }

  // ── 四诊辅助函数 ────────────────────────────────────────────────────────────

  function buildSizhenContext() {
    const parts = [];
    if (sizhenState.tongue_color)  parts.push(`舌色${sizhenState.tongue_color}`);
    if (sizhenState.tongue_coating) parts.push(`苔${sizhenState.tongue_coating}`);
    if (sizhenState.pulse.length)  parts.push(`脉${sizhenState.pulse.join('')}`);
    if (sizhenState.sleep)         parts.push(`睡眠${sizhenState.sleep}`);
    if (sizhenState.stool)         parts.push(`大便${sizhenState.stool}`);
    if (sizhenState.urine)         parts.push(`小便${sizhenState.urine}`);
    return parts.join('，');
  }

  function updateSizhenSummary() {
    const el = document.getElementById('tcm-sz-summary');
    if (!el) return;
    const ctx = buildSizhenContext();
    if (ctx) {
      el.textContent = ctx;
      el.style.display = 'block';
    } else {
      el.style.display = 'none';
    }
  }

  function onSizhenChange() {
    updateSizhenSummary();
    if (!currentPatient?.archive_id) return;
    clearTimeout(_sizhenTimer);
    // 显示更新中指示
    const indicator = document.getElementById('tcm-sz-updating');
    if (indicator) { indicator.style.display = 'inline'; indicator.textContent = 'AI 分析中…'; }
    _sizhenTimer = setTimeout(async () => {
      const ctx = buildSizhenContext();
      if (!ctx) {
        if (indicator) indicator.style.display = 'none';
        return;
      }
      // 1. 更新风险分析
      const r = await msg('analyzeRiskWithContext', {
        patient_id: currentPatient.archive_id,
        extra_context: ctx,
      });
      if (r?.success) {
        currentRisk = r.data?.analysis || r.data || null;
        currentRiskConclusions = null;  // 清缓存，让 loadBlockB 重新拉结论
        loadBlockB();
      }
      // 2. 若存在草稿方案，自动更新
      const hasDraft = (currentPlanVersions || []).some(v => v.status === 'DRAFT') || currentPlan?.status === 'DRAFT';
      if (hasDraft) {
        if (indicator) indicator.textContent = 'AI 更新草稿…';
        await autoUpdateDraftPlan(ctx);
      }
      if (indicator) indicator.style.display = 'none';
    }, 800);
  }

  async function autoUpdateDraftPlan(extraContext) {
    if (!currentPatient?.archive_id) return;

    // 1. 生成新方案 markdown
    const r = await msg('generatePlanWithContext', {
      patient_id: currentPatient.archive_id,
      extra_context: extraContext,
    });
    if (!r?.success) return;

    const markdown = r.data?.plan_markdown || '';
    if (!markdown) return;

    // 2. 找现有草稿 plan_id
    const versions = currentPlanVersions || [];
    const draft = versions.find(v => v.status === 'DRAFT')
               || (currentPlan?.status === 'DRAFT' ? currentPlan : null);
    const draftId = draft?.plan_id || draft?.id || null;

    if (draftId) {
      // 有草稿：更新内容
      await msg('updateDraft', {
        plan_id: draftId,
        body: { content: markdown },
      });
    } else {
      // 无草稿：自动创建一份
      await msg('createDraft', {
        body: {
          patient_id: currentPatient.archive_id,
          title: 'AI 四诊辅助草稿',
          content: markdown,
        },
      });
    }

    // 3. 重新加载 Block C（从数据库读最新内容）
    currentPlanVersions = null;
    await loadBlockC();
  }

  // ── 补充采集抽屉 ──────────────────────────────────────────────────────────
  function loadSupplementDrawer() {
    const body = document.getElementById('tcm-drawer-supplement-body');
    if (!body) return;

    // 还原当前 sizhenState 到按钮高亮
    const renderBtns = (id, options, selected, isMulti) =>
      options.map(({ v, label }) => {
        const active = isMulti ? sizhenState[id]?.includes(v) : sizhenState[id] === v;
        return `<button class="tcm-sz-btn${active ? ' tcm-sz-active' : ''}" data-field="${id}" data-value="${v}" data-multi="${isMulti}">${label}</button>`;
      }).join('');

    body.innerHTML = `
      <div class="tcm-supplement-form">
        <div class="tcm-section-title">四诊快速采集 <span id="tcm-sz-updating" style="display:none" class="tcm-sz-updating"></span></div>
        <div id="tcm-sz-summary" class="tcm-sz-summary"></div>

        <div class="tcm-form-row">
          <label class="tcm-form-label">舌色</label>
          <div class="tcm-tag-row">
            ${renderBtns('tongue_color', [
              {v:'淡红',label:'淡红'},{v:'红',label:'红'},{v:'暗红',label:'暗红'},
              {v:'淡白',label:'淡白'},{v:'紫暗',label:'紫暗'}
            ], sizhenState.tongue_color, false)}
          </div>
        </div>
        <div class="tcm-form-row">
          <label class="tcm-form-label">舌苔</label>
          <div class="tcm-tag-row">
            ${renderBtns('tongue_coating', [
              {v:'薄白',label:'薄白'},{v:'薄黄',label:'薄黄'},{v:'厚腻',label:'厚腻'},
              {v:'黄腻',label:'黄腻'},{v:'无苔',label:'无苔'}
            ], sizhenState.tongue_coating, false)}
          </div>
        </div>
        <div class="tcm-form-row">
          <label class="tcm-form-label">脉象<span style="font-size:10px;color:#999">（可多选）</span></label>
          <div class="tcm-tag-row">
            ${renderBtns('pulse', [
              {v:'浮',label:'浮'},{v:'沉',label:'沉'},{v:'迟',label:'迟'},{v:'数',label:'数'},
              {v:'弦',label:'弦'},{v:'滑',label:'滑'},{v:'涩',label:'涩'},{v:'细',label:'细'},{v:'洪',label:'洪'}
            ], sizhenState.pulse, true)}
          </div>
        </div>
        <div class="tcm-form-row">
          <label class="tcm-form-label">睡眠</label>
          <div class="tcm-tag-row">
            ${renderBtns('sleep', [
              {v:'良好',label:'良好'},{v:'欠佳',label:'欠佳'},{v:'失眠',label:'失眠'},{v:'多梦',label:'多梦'}
            ], sizhenState.sleep, false)}
          </div>
        </div>
        <div class="tcm-form-row">
          <label class="tcm-form-label">大便</label>
          <div class="tcm-tag-row">
            ${renderBtns('stool', [
              {v:'正常',label:'正常'},{v:'干结',label:'干结'},{v:'稀溏',label:'稀溏'},{v:'不成形',label:'不成形'}
            ], sizhenState.stool, false)}
          </div>
        </div>
        <div class="tcm-form-row">
          <label class="tcm-form-label">小便</label>
          <div class="tcm-tag-row">
            ${renderBtns('urine', [
              {v:'正常',label:'正常'},{v:'频多',label:'频多'},{v:'短黄',label:'短黄'},{v:'夜尿多',label:'夜尿多'}
            ], sizhenState.urine, false)}
          </div>
        </div>

        <div class="tcm-section-title" style="margin-top:12px">主诉补充</div>
        <div class="tcm-form-row">
          <textarea id="tcm-sup-complaint" class="tcm-textarea" rows="2" placeholder="患者主要不适（可选）"></textarea>
        </div>

        <div class="tcm-section-title" style="margin-top:8px">生活方式</div>
        <div class="tcm-form-row">
          <label class="tcm-form-label">久坐习惯</label>
          <div class="tcm-radio-group" id="tcm-sup-sedentary">
            <label><input type="radio" name="sedentary" value="often"> 经常</label>
            <label><input type="radio" name="sedentary" value="sometimes"> 偶尔</label>
            <label><input type="radio" name="sedentary" value="rarely"> 很少</label>
          </div>
        </div>
        <div class="tcm-form-row">
          <label class="tcm-form-label">运动频率</label>
          <div class="tcm-radio-group" id="tcm-sup-exercise">
            <label><input type="radio" name="exercise" value="never"> 不运动</label>
            <label><input type="radio" name="exercise" value="occasional"> 偶尔</label>
            <label><input type="radio" name="exercise" value="regular"> 规律</label>
          </div>
        </div>

        <div style="display:flex;gap:6px;margin-top:12px">
          <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-sup-confirm-btn">确认保存</button>
          <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-sup-clear-btn">清空四诊</button>
          <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-sup-cancel-btn">关闭</button>
        </div>
        <div id="tcm-sup-result" style="margin-top:8px"></div>
      </div>
    `;

    // 初始化摘要显示
    updateSizhenSummary();

    // 四诊按钮点击（单选 / 多选）
    body.querySelectorAll('.tcm-sz-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const field = btn.dataset.field;
        const value = btn.dataset.value;
        const isMulti = btn.dataset.multi === 'true';

        if (isMulti) {
          // 多选：toggle
          const arr = sizhenState[field] || [];
          const idx = arr.indexOf(value);
          if (idx >= 0) {
            sizhenState[field] = arr.filter(v => v !== value);
          } else {
            sizhenState[field] = [...arr, value];
          }
        } else {
          // 单选：再次点击取消
          sizhenState[field] = sizhenState[field] === value ? null : value;
        }

        // 更新当前行内按钮高亮
        body.querySelectorAll(`.tcm-sz-btn[data-field="${field}"]`).forEach(b => {
          const v = b.dataset.value;
          const active = isMulti
            ? (sizhenState[field] || []).includes(v)
            : sizhenState[field] === v;
          b.classList.toggle('tcm-sz-active', active);
        });

        onSizhenChange();
      });
    });

    // 清空按钮
    document.getElementById('tcm-sup-clear-btn')?.addEventListener('click', () => {
      sizhenState = { tongue_color: null, tongue_coating: null, pulse: [], sleep: null, stool: null, urine: null };
      body.querySelectorAll('.tcm-sz-btn').forEach(b => b.classList.remove('tcm-sz-active'));
      updateSizhenSummary();
    });

    // 确认保存按钮：将四诊+主诉持久化到患者档案
    document.getElementById('tcm-sup-confirm-btn')?.addEventListener('click', async () => {
      if (!currentPatient?.archive_id) return;
      const ctx = buildSizhenContext();
      const complaint = document.getElementById('tcm-sup-complaint')?.value.trim() || '';
      const sedentary = document.querySelector('input[name="sedentary"]:checked')?.value || null;
      const exercise  = document.querySelector('input[name="exercise"]:checked')?.value || null;

      const payload = {};
      if (sizhenState.tongue_color)   payload.tongue_color   = sizhenState.tongue_color;
      if (sizhenState.tongue_coating) payload.tongue_coating = sizhenState.tongue_coating;
      if (sizhenState.pulse.length)   payload.pulse          = sizhenState.pulse.join('');
      if (sizhenState.sleep)          payload.sleep_quality  = sizhenState.sleep;
      if (sizhenState.stool)          payload.stool          = sizhenState.stool;
      if (sizhenState.urine)          payload.urine          = sizhenState.urine;
      if (complaint)                  payload.chief_complaint = complaint;
      if (sedentary)                  payload.sedentary      = sedentary;
      if (exercise)                   payload.exercise_frequency = exercise;
      if (ctx)                        payload.sizhen_summary = ctx;

      const btn = document.getElementById('tcm-sup-confirm-btn');
      if (btn) { btn.textContent = '保存中…'; btn.disabled = true; }

      const r = await msg('supplementPatient', { patient_id: currentPatient.archive_id, body: payload });

      if (!r?.success) {
        if (btn) { btn.textContent = '确认保存'; btn.disabled = false; }
        const resultEl = document.getElementById('tcm-sup-result');
        if (resultEl) resultEl.innerHTML = `<div class="tcm-hint tcm-hint-err">保存失败：${esc(r?.error || '请检查网络')}</div>`;
        return;
      }

      showToast('四诊信息已保存，AI 刷新中…', 'success');
      closeDrawer('tcm-drawer-supplement');   // 关闭抽屉，回到主面板

      if (!ctx) return;

      // 直接触发 AI 分析（跳过 debounce，立即执行）
      clearTimeout(_sizhenTimer);
      const riskResp = await msg('analyzeRiskWithContext', {
        patient_id: currentPatient.archive_id,
        extra_context: ctx,
      });
      if (riskResp?.success) {
        currentRisk = riskResp.data?.analysis || riskResp.data || null;
        currentRiskConclusions = null;
        loadBlockB();
      }

      // 生成并保存草稿
      await autoUpdateDraftPlan(ctx);
    });

    document.getElementById('tcm-sup-cancel-btn')?.addEventListener('click', () =>
      closeDrawer('tcm-drawer-supplement'));
  }

  // Block C: 方案状态
  async function loadBlockC() {
    const body = document.getElementById('tcm-block-c-body');
    if (!body) return;

    // 获取所有版本，优先展示草稿
    if (!currentPlanVersions) {
      const vResp = await msg('getPlanVersions', { patient_id: currentPatient.archive_id });
      if (vResp?.success) {
        currentPlanVersions = Array.isArray(vResp.data) ? vResp.data : (vResp.data?.items || []);
      }
    }

    // 优先草稿 > 已确认 > 已分发 > 已发布
    const priority = ['DRAFT', 'CONFIRMED', 'DISTRIBUTED', 'PUBLISHED'];
    let displayPlan = null;
    for (const status of priority) {
      displayPlan = (currentPlanVersions || []).find(v => v.status === status);
      if (displayPlan) break;
    }
    if (displayPlan) currentPlan = displayPlan;

    if (!displayPlan) {
      // 兜底：尝试获取当前生效方案
      if (!currentPlan) {
        const resp = await msg('getCurrentPlan', { patient_id: currentPatient.archive_id });
        if (resp?.success) currentPlan = resp.data?.plan || null;
        displayPlan = currentPlan;
      }
    }

    if (!displayPlan) {
      body.innerHTML = `
        <div class="tcm-c-empty">
          <span class="tcm-hint">暂无方案</span>
          <button class="tcm-btn tcm-btn-primary tcm-btn-xs tcm-c-new-btn">新建草稿</button>
        </div>`;
      body.querySelector('.tcm-c-new-btn')?.addEventListener('click', () =>
        openDrawer('tcm-drawer-plan', loadPlanDrawer));
      return;
    }

    const plan = displayPlan;
    const st = PLAN_STATES[plan.status] || { label: plan.status || '未知', color: '#9A9188', icon: '' };
    const summary = (plan.content_preview || plan.summary || '').slice(0, 80);
    const planId  = plan.plan_id || plan.id || '';
    // 草稿显示更新时间，已发布显示创建时间
    const displayDate = plan.status === 'DRAFT'
      ? (plan.updated_at || plan.created_at || '').slice(0, 16).replace('T', ' ')
      : (plan.created_at || '').slice(0, 10);

    body.innerHTML = `
      <div class="tcm-c-card" id="tcm-c-card" style="cursor:pointer" title="点击查看方案">
        <div class="tcm-c-status-row">
          <span class="tcm-c-status-dot" style="background:${st.color}"></span>
          <span class="tcm-c-status-label" style="color:${st.color}">${st.label}</span>
          <span class="tcm-c-date">${esc(displayDate)}</span>
        </div>
        <div class="tcm-c-title">${esc(plan.title || '当前方案')}</div>
        ${summary ? `<div class="tcm-c-preview">${esc(summary)}…</div>` : ''}
        <div style="margin-top:6px">
          <button class="tcm-btn tcm-btn-primary tcm-btn-xs" id="tcm-c-preview-btn">查看方案</button>
        </div>
      </div>
    `;

    // 按钮和整张卡片都可点击
    const openPreview = () => openDrawer('tcm-drawer-preview', () => loadPreviewDrawer(planId));
    document.getElementById('tcm-c-preview-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      openPreview();
    });
    document.getElementById('tcm-c-card')?.addEventListener('click', openPreview);
  }

  // Block D: 复评/召回
  async function loadBlockD() {
    const body = document.getElementById('tcm-block-d-body');
    if (!body) return;

    const [tasksResp, recallResp] = await Promise.all([
      msg('listFollowupTasks',    { patient_id: currentPatient.archive_id }),
      msg('getRecallSuggestions', { patient_id: currentPatient.archive_id }),
    ]);

    const tasks  = tasksResp?.success
      ? (Array.isArray(tasksResp.data) ? tasksResp.data : (tasksResp.data?.items || []))
      : [];
    const recalls = recallResp?.success ? (recallResp.data?.total || 0) : 0;

    // 下一次待随访
    const pending = tasks.filter(t => !t.completed_at && !t.is_overdue);
    const next    = pending[0];
    const overdue = tasks.filter(t => t.is_overdue).length;

    body.innerHTML = `
      <div class="tcm-d-row">
        ${ICONS.clock}
        <span>${next
          ? `下次随访：<strong>${esc((next.scheduled_date || next.plan_date || '').slice(0,10))}</strong>`
          : '暂无待随访任务'}</span>
      </div>
      ${overdue > 0
        ? `<div class="tcm-d-row tcm-d-warn">${ICONS.warning}<span>已逾期 <strong>${overdue}</strong> 条</span></div>`
        : ''}
      <div class="tcm-d-row">
        ${ICONS.bell}
        <span>召回建议：<strong style="color:${recalls > 0 ? '#D95C4A' : '#4E7A61'}">${recalls}</strong> 条待处理</span>
      </div>
    `;
  }

  // ─── 加载超时包装 ─────────────────────────────────────────────────────────
  const MSG_TIMEOUT_MS = 20000; // 20s 总超时

  function sendMsgWithTimeout(action, payload, onSuccess, onError) {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      onError('响应超时（服务器未启动或网络异常）\n请确认：① 已启动治未病平台服务 ② 已刷新页面 ③ 检查插件设置中的服务器地址');
    }, MSG_TIMEOUT_MS);

    chrome.runtime.sendMessage({ action, ...payload }, (response) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (chrome.runtime.lastError) {
        onError('插件内部通信失败，请刷新页面或重新加载插件');
        return;
      }
      if (!response) { onError('未收到后台响应，请刷新页面重试'); return; }
      onSuccess(response);
    });
  }

  // ─── 加载状态 & 错误 ────────────────────────────────────────────────────────
  function renderLoading(patientId) {
    const dash = document.getElementById('tcm-dashboard');
    if (!dash) return;
    dash.innerHTML = `<div class="tcm-loading"><div class="tcm-spinner"></div><p>正在识别 <strong>${esc(patientId)}</strong></p><p class="tcm-hint">加载患者数据…</p><p class="tcm-hint tcm-hint-sm" style="margin-top:8px;opacity:.6">若长时间等待，请确认服务器已启动并刷新页面</p></div>`;
    const dock = document.getElementById('tcm-ai-dock');
    if (dock) dock.style.display = 'none';
  }

  function renderError(message) {
    const dash = document.getElementById('tcm-dashboard');
    if (!dash) return;
    // 支持换行符显示为多行
    const lines = String(message).split('\n').map(l => `<p class="tcm-error-line">${esc(l)}</p>`).join('');
    dash.innerHTML = `<div class="tcm-error"><div class="tcm-error-icon">${ICONS.warning}</div>${lines}<button class="tcm-btn tcm-btn-retry" id="tcm-retry-btn">重新检测</button></div>`;
    document.getElementById('tcm-retry-btn')?.addEventListener('click', () => { currentPatientId = null; checkUrl(); });
  }

  // ─── 抽屉内容加载器 ─────────────────────────────────────────────────────────

  // 临床摘要抽屉（原患者 Tab）
  async function loadClinicalDrawer() {
    const body = document.getElementById('tcm-drawer-clinical-body');
    if (!body) return;
    body.innerHTML = '<div class="tcm-loading-sm">加载中…</div>';

    // 并行加载所有数据
    const loads = [];
    if (!currentProfile || !currentRiskTags) {
      loads.push(
        msg('getPatientProfile', { patient_id: currentPatient.archive_id }),
        msg('getRiskTags',       { patient_id: currentPatient.archive_id }),
      );
    }
    if (!currentMetrics) {
      loads.push(msg('getPatientMetrics', { patient_id: currentPatient.archive_id, range: 90 }));
    }
    const results = await Promise.all(loads);
    let ri = 0;
    if (!currentProfile || !currentRiskTags) {
      if (results[ri]?.success) currentProfile  = results[ri].data; ri++;
      if (results[ri]?.success) currentRiskTags = results[ri].data; ri++;
    }
    if (!currentMetrics && results[ri]?.success) currentMetrics = results[ri].data;

    const p  = currentProfile || {};
    const ka = currentRiskTags?.key_alerts || {};

    // ── 工具函数 ─────────────────────────────────────────────────────────────
    function kdSection(icon, title, cls, content) {
      return `
        <div class="tcm-kd-section tcm-kd-section-${cls}">
          <div class="tcm-kd-header">
            <span class="tcm-kd-icon">${icon}</span>
            <span class="tcm-kd-title">${title}</span>
          </div>
          <div class="tcm-kd-body">${content}</div>
        </div>`;
    }
    function kdEmpty(msg2) {
      return `<span class="tcm-kd-empty">${msg2}</span>`;
    }
    function uniq(arr, keyFn) {
      const seen = new Set();
      return arr.filter(item => {
        const k = keyFn(item);
        if (seen.has(k)) return false;
        seen.add(k); return true;
      });
    }

    // ── §1 过敏史 ─────────────────────────────────────────────────────────────
    const rawAllergy = Array.isArray(p.allergy_history)
      ? p.allergy_history
      : (p.allergy_history && p.allergy_history !== '无' ? [p.allergy_history] : []);
    const kaAllergy = ka.allergy || [];
    const allergyAll = uniq([...kaAllergy, ...rawAllergy].filter(Boolean), s => s.trim().toLowerCase());
    const allergyHtml = allergyAll.length
      ? allergyAll.map(a => `<div class="tcm-kd-tag tcm-kd-tag-danger">${esc(a)}</div>`).join('')
      : kdEmpty('无已知过敏史');

    // ── §2 用药禁忌 ──────────────────────────────────────────────────────────
    const contraRaw = ka.contraindications || [];
    const contraUniq = uniq(contraRaw.filter(c => c.item), c => c.item.slice(0, 15).toLowerCase());
    // 按疾病分组
    const contraGroups = {};
    contraUniq.forEach(c => {
      const d = c.disease || '通用';
      (contraGroups[d] = contraGroups[d] || []).push(c.item);
    });
    function parseContraItem(item) {
      const idx = item.indexOf('—');
      if (idx > -1) return { drug: item.slice(0, idx).trim(), reason: item.slice(idx + 1).trim() };
      const idx2 = item.indexOf('，');
      if (idx2 > -1) return { drug: item.slice(0, idx2).trim(), reason: item.slice(idx2 + 1).trim() };
      return { drug: item, reason: '' };
    }
    const contraHtml = Object.keys(contraGroups).length
      ? Object.entries(contraGroups).map(([disease, items]) => `
          <div class="tcm-kd-group">
            <div class="tcm-kd-group-label">【${esc(disease)}】</div>
            ${items.map(item => {
              const { drug, reason } = parseContraItem(item);
              return `<div class="tcm-kd-contra-item">
                <span class="tcm-kd-contra-drug">${esc(drug)}</span>
                ${reason ? `<span class="tcm-kd-contra-reason">${esc(reason)}</span>` : ''}
              </div>`;
            }).join('')}
          </div>`).join('')
      : kdEmpty('暂无用药禁忌记录');

    // ── §3 共病 / 并发症 ─────────────────────────────────────────────────────
    const comorbRaw = ka.comorbidities || [];
    const comorbUniq = uniq(comorbRaw, c => `${c.disease}|${c.complication}`);
    // 优先级：高危并发症（含"病变""肾病""视网膜"等关键词）靠前
    const comorbSorted = [...comorbUniq].sort((a, b) => {
      const danger = /病变|肾病|视网膜|心肌|脑|坏疽|溃疡/;
      return (danger.test(b.complication) ? 1 : 0) - (danger.test(a.complication) ? 1 : 0);
    });
    const comorbHtml = comorbSorted.length
      ? `<table class="tcm-kd-table">
          <thead><tr><th>慢病</th><th>并发症 / 合并症</th></tr></thead>
          <tbody>${comorbSorted.map(c => `
            <tr>
              <td>${esc(c.disease)}</td>
              <td class="tcm-kd-td-compl">${esc(c.complication)}</td>
            </tr>`).join('')}
          </tbody>
        </table>`
      : kdEmpty('暂无并发症记录');

    // ── §4 健康指标（带数值）────────────────────────────────────────────────
    const m = currentMetrics || {};
    const indicators = Array.isArray(m.indicators) ? m.indicators : (Array.isArray(m) ? m : []);
    // 合并 alert_tags 中的指标信息，优先显示异常项
    const indFromAlerts = (ka.indicator_alerts || currentRiskTags?.alert_tags || []).map(a => ({
      name: (a.factor || a.name || '').trim(),
      value: a.value || '',
      unit:  a.unit  || '',
      reference: a.reference || '',
      abnormal: a.severity !== 'LOW',
      date: a.date || '',
      severity: a.severity || 'LOW',
      message: (a.message || '').replace(/^⚠️\s*[危急提示：]*/u, '').trim(),
    })).filter(i => i.name || i.message);
    // indicators 从 metrics API
    const indFromMetrics = indicators.map(ind => ({
      name: ind.name || ind.indicator_name || '',
      value: String(ind.latest_value ?? ind.value ?? ''),
      unit:  ind.unit || '',
      reference: ind.reference_range || '',
      abnormal: !!ind.abnormal,
      date: (ind.date || ind.measured_at || '').slice(0, 10),
      severity: ind.abnormal ? 'HIGH' : 'LOW',
      message: '',
    })).filter(i => i.name);
    // 合并：以 name 去重，alert 优先
    const indMerged = [...indFromAlerts];
    const indAlertNames = new Set(indFromAlerts.map(i => i.name.toLowerCase()));
    indFromMetrics.forEach(i => { if (!indAlertNames.has(i.name.toLowerCase())) indMerged.push(i); });
    // 排序：HIGH → MEDIUM → LOW，同级按日期倒序
    const sevOrder = { HIGH: 0, MEDIUM: 1, LOW: 2 };
    indMerged.sort((a, b) => {
      const so = (sevOrder[a.severity] ?? 2) - (sevOrder[b.severity] ?? 2);
      if (so !== 0) return so;
      return (b.date || '').localeCompare(a.date || '');
    });
    const indicatorsHtml = indMerged.length
      ? indMerged.slice(0, 10).map(ind => {
          const hasVal = ind.value && ind.value !== 'null' && ind.value !== '';
          const sevCls = ind.severity === 'HIGH' ? 'high' : (ind.severity === 'MEDIUM' ? 'med' : 'ok');
          return `
            <div class="tcm-kd-metric-row tcm-kd-metric-${ind.abnormal ? 'abnormal' : 'normal'}">
              <div class="tcm-kd-metric-name">${esc(ind.name || ind.message.slice(0, 20))}</div>
              <div class="tcm-kd-metric-right">
                ${hasVal ? `<span class="tcm-kd-value tcm-kd-value-${sevCls}">${esc(ind.value)}${ind.unit ? ' <small>'+esc(ind.unit)+'</small>' : ''}</span>` : ''}
                ${ind.reference ? `<span class="tcm-kd-ref">${esc(ind.reference)}</span>` : ''}
                ${ind.abnormal ? `<span class="tcm-kd-badge-ab">异常</span>` : ''}
              </div>
              ${ind.date ? `<div class="tcm-kd-metric-date">${esc(ind.date)}</div>` : ''}
              ${!hasVal && ind.message ? `<div class="tcm-kd-metric-note">${esc(ind.message)}</div>` : ''}
            </div>`;
        }).join('')
      : kdEmpty('近90天暂无指标数据');

    // ── §5 中医特征 ──────────────────────────────────────────────────────────
    const constMain   = p.constitution?.main_type_cn || p.constitution_type || '';
    const constSec    = p.constitution?.secondary_types || [];
    const assessDate  = p.constitution?.assessed_at ? p.constitution.assessed_at.slice(0, 10) : '';
    const chronicDiseaseCn = (p.chronic_diseases || []).map(d =>
      typeof d === 'object' ? (d.disease_cn || d.disease_type || '') : d).filter(Boolean);
    const tcmHtml = constMain ? `
      <div class="tcm-kd-tcm-block">
        <div class="tcm-kd-tcm-row">
          <span class="tcm-kd-tcm-label">主体质</span>
          <span class="tcm-const-label tcm-const-label-main">${esc(constMain)}</span>
          ${assessDate ? `<span class="tcm-kd-tcm-date">（${assessDate} 评估）</span>` : ''}
        </div>
        ${constSec.length ? `
        <div class="tcm-kd-tcm-row">
          <span class="tcm-kd-tcm-label">兼夹体质</span>
          <span class="tcm-kd-tcm-secs">${constSec.map(s => `<span class="tcm-const-label tcm-const-label-sec">${esc(s.type_cn || s.type)}</span>`).join('')}</span>
        </div>` : ''}
        ${chronicDiseaseCn.length ? `
        <div class="tcm-kd-tcm-row">
          <span class="tcm-kd-tcm-label">慢病诊断</span>
          <span>${chronicDiseaseCn.map(d => `<span class="tcm-mini-tag">${esc(d)}</span>`).join('')}</span>
        </div>` : ''}
        ${p.health_profile?.bmi ? `
        <div class="tcm-kd-tcm-row">
          <span class="tcm-kd-tcm-label">BMI</span>
          <span class="tcm-kd-value ${p.health_profile.bmi > 28 || p.health_profile.bmi < 18.5 ? 'tcm-kd-value-high' : 'tcm-kd-value-ok'}">${esc(String(p.health_profile.bmi))}</span>
          <span class="tcm-kd-ref">参考 18.5–28.0</span>
        </div>` : ''}
      </div>` : kdEmpty('暂无中医体质评估记录');

    // ── §6 依从性 ─────────────────────────────────────────────────────────────
    const adh = ka.adherence;
    let adhHtml = kdEmpty('暂无随访打卡记录');
    if (adh) {
      const rate = adh.rate_pct ?? 0;
      const { cls: adhCls, text: adhText } = getRiskBadge(adh.risk_level);
      adhHtml = `
        <div class="tcm-kd-adh-row">
          <span class="tcm-kd-adh-label">近30天完成率</span>
          <span class="tcm-kd-value tcm-kd-value-${adh.risk_level === 'HIGH' ? 'high' : (adh.risk_level === 'MEDIUM' ? 'med' : 'ok')}">${rate}%</span>
          <span class="tcm-badge ${adhCls}">${adhText}</span>
        </div>
        <div class="tcm-kd-adh-bar-track">
          <div class="tcm-kd-adh-bar-fill" style="width:${rate}%;background:${adh.risk_level === 'HIGH' ? '#D95C4A' : (adh.risk_level === 'MEDIUM' ? '#B8885E' : '#4E7A61')}"></div>
        </div>
        <div class="tcm-kd-adh-detail">已完成 ${adh.done_count} 次，共 ${adh.total_count} 次计划任务</div>`;
    }

    // ── 渲染 ─────────────────────────────────────────────────────────────────
    body.innerHTML = [
      kdSection('⚠', '过敏史',      'danger', allergyHtml),
      kdSection('⊘', '用药禁忌',    'danger', contraHtml),
      kdSection('◉', '共病 / 并发症', 'warn',  comorbHtml),
      kdSection('↑', '健康指标',    'info',  indicatorsHtml),
      kdSection('☯', '中医特征',    'tcm',   tcmHtml),
      kdSection('⊡', '依从性',      adh?.risk_level === 'HIGH' ? 'danger' : (adh?.risk_level === 'MEDIUM' ? 'warn' : 'ok'), adhHtml),
    ].join('') + `
      <div class="tcm-actions">
        <a class="tcm-btn tcm-btn-secondary tcm-btn-sm" href="${serverUrl}/gui/admin/archives" target="_blank">完整档案 ↗</a>
      </div>`;
  }

  // 风险证据链抽屉（原风险 Tab）
  function loadEvidenceDrawer() {
    const body = document.getElementById('tcm-drawer-evidence-body');
    if (!body) return;

    const risk = currentRisk;
    if (!risk) {
      body.innerHTML = '<p class="tcm-hint" style="padding:16px">暂无风险评估数据</p>';
      return;
    }

    const { cls, text } = getRiskBadge(risk.risk_level);
    const evidence = risk.risk_evidence || [];
    const factors  = risk.risk_factors  || [];
    const summary  = (risk.raw_summary || '').slice(0, 200);

    const evidenceHtml = evidence.length > 0
      ? evidence.map((ev, i) => `
          <div class="tcm-ev-item">
            <div class="tcm-ev-header" onclick="(function(el){el.classList.toggle('tcm-ev-open')})(document.getElementById('tcm-evd-${i}'))">
              <span class="tcm-ev-dot" style="background:${getSevColor(ev.severity)}"></span>
              <span class="tcm-ev-factor">${esc(ev.factor)}</span>
              <span class="tcm-ev-arrow">▾</span>
            </div>
            <div class="tcm-ev-body" id="tcm-evd-${i}">
              <table class="tcm-ev-table">
                <tr><td>检测值</td><td><strong>${esc(ev.value)}</strong></td></tr>
                <tr><td>参考范围</td><td>${esc(ev.reference)}</td></tr>
                <tr><td>来源</td><td>${esc(ev.source)}</td></tr>
                ${ev.date ? `<tr><td>日期</td><td>${esc(ev.date)}</td></tr>` : ''}
              </table>
            </div>
          </div>`)
        .join('')
      : factors.map(f => `<div class="tcm-factor-plain">• ${esc(f)}</div>`).join('');

    body.innerHTML = `
      <div style="padding:12px 14px 8px;">
        <span class="tcm-badge ${cls}">${text}</span>
        ${risk.risk_topic ? `<span style="margin-left:6px;color:#6A6258;font-size:11px">${esc(risk.risk_topic)}</span>` : ''}
      </div>
      <div class="tcm-section">
        <div class="tcm-section-title">风险证据 <span class="tcm-hint">点击展开溯源</span></div>
        <div class="tcm-ev-list">${evidenceHtml || '<p class="tcm-hint">暂无证据数据</p>'}</div>
      </div>
      ${summary ? `<div class="tcm-section"><div class="tcm-section-title">AI摘要</div><div class="tcm-summary">${esc(summary)}</div></div>` : ''}
      ${risk.patient_talk_track ? `<div class="tcm-section"><div class="tcm-section-title">沟通话术</div><div class="tcm-summary tcm-talk-track">${esc(risk.patient_talk_track)}</div></div>` : ''}
      <div class="tcm-actions" style="padding:0 14px 14px;">
        <button class="tcm-btn tcm-btn-primary" id="tcm-evidence-goto-plan-btn">
          ${ICONS.bolt} 前往制定方案
        </button>
        <a class="tcm-btn tcm-btn-secondary" href="${serverUrl}/gui/admin/risk/plan" target="_blank">完整分析↗</a>
      </div>`;

    document.getElementById('tcm-evidence-goto-plan-btn')?.addEventListener('click', () => {
      openDrawer('tcm-drawer-plan', loadPlanDrawer, 'tcm-drawer-evidence');
    });
  }

  // 方案管理抽屉（原方案 Tab）
  async function loadPlanDrawer() {
    const body = document.getElementById('tcm-drawer-plan-body');
    if (!body) return;
    body.innerHTML = '<div class="tcm-loading-sm">加载方案版本…</div>';

    const [currentResp, versionsResp] = await Promise.all([
      msg('getCurrentPlan',  { patient_id: currentPatient.archive_id }),
      msg('getPlanVersions', { patient_id: currentPatient.archive_id }),
    ]);

    const versions = versionsResp?.success
      ? (Array.isArray(versionsResp.data) ? versionsResp.data : (versionsResp.data?.items || []))
      : [];
    currentPlanVersions = versions;
    currentPlan = currentResp?.success ? (currentResp.data?.plan || null) : currentPlan;

    const currentPlanHtml = currentPlan ? `
      <div class="tcm-current-plan-card">
        <div class="tcm-current-plan-label">${ICONS.pin} 当前生效方案</div>
        <div class="tcm-current-plan-title">${esc(currentPlan.title)}</div>
        <div class="tcm-current-plan-preview">${esc((currentPlan.content_preview || '').slice(0, 100))}</div>
        <div class="tcm-current-plan-meta">发布于 ${esc((currentPlan.created_at || '').slice(0, 10))}</div>
      </div>` : '';

    const versionsHtml = versions.length
      ? versions.map((v, i) => {
          const st = PLAN_STATES[v.status] || { label: v.status || '未知', color: '#9A9188', icon: '' };
          return `
            <div class="tcm-plan-card">
              <div class="tcm-plan-card-header">
                <span style="color:${st.color};font-size:12px">${st.icon} ${st.label}</span>
                <span class="tcm-plan-date">${esc((v.created_at||v.updated_at||'').slice(0,10))}</span>
              </div>
              <div class="tcm-plan-title">${esc(v.title || `方案 v${i+1}`)}</div>
              <div class="tcm-plan-preview">${esc((v.content_preview || v.summary || '').slice(0,80))}</div>
              <div class="tcm-plan-actions">
                ${v.status === 'DRAFT' ? `
                  <button class="tcm-state-btn tcm-state-btn-preview" data-preview-id="${esc(v.plan_id||v.id)}">预览方案</button>
                  <button class="tcm-state-btn" data-publish-id="${esc(v.plan_id||v.id)}">发布</button>` : ''}
                ${v.status === 'CONFIRMED' ? `<button class="tcm-state-btn tcm-state-btn-preview" data-preview-id="${esc(v.plan_id||v.id)}">预览/分发</button>` : ''}
                <button class="tcm-state-btn tcm-state-btn-alt" data-summary-id="${esc(v.plan_id||v.id)}">摘要</button>
                ${i > 0 ? `<button class="tcm-state-btn tcm-state-btn-alt" data-diff-a="${esc(versions[i-1].plan_id||versions[i-1].id)}" data-diff-b="${esc(v.plan_id||v.id)}">与上版对比</button>` : ''}
              </div>
            </div>`;
        }).join('')
      : '<div class="tcm-empty"><p>暂无方案记录</p></div>';

    body.innerHTML = `
      ${currentPlanHtml}
      <div class="tcm-plan-actions-bar">
        <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-new-draft-btn">+ 新建草稿</button>
        <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-pick-template-btn">模板库</button>
      </div>
      <div id="tcm-draft-form" style="display:none;" class="tcm-section">
        <div class="tcm-section-title">新建草稿（结构化录入）</div>
        <input type="text" id="tcm-draft-title" class="tcm-input" placeholder="方案标题" />
        <div class="tcm-module-grid">
          <div class="tcm-module-card">
            <div class="tcm-module-label">作息建议</div>
            <textarea class="tcm-textarea tcm-module-ta" id="tcm-mod-rest" rows="2" placeholder="睡眠、起居规律建议…"></textarea>
          </div>
          <div class="tcm-module-card">
            <div class="tcm-module-label">饮食/食疗</div>
            <textarea class="tcm-textarea tcm-module-ta" id="tcm-mod-diet" rows="2" placeholder="饮食原则、推荐食材…"></textarea>
          </div>
          <div class="tcm-module-card">
            <div class="tcm-module-label">运动建议</div>
            <textarea class="tcm-textarea tcm-module-ta" id="tcm-mod-exercise" rows="2" placeholder="运动方式、频率…"></textarea>
          </div>
          <div class="tcm-module-card">
            <div class="tcm-module-label">情志建议</div>
            <textarea class="tcm-textarea tcm-module-ta" id="tcm-mod-emotion" rows="2" placeholder="情绪调节、心理建议…"></textarea>
          </div>
          <div class="tcm-module-card">
            <div class="tcm-module-label">穴位/艾灸</div>
            <textarea class="tcm-textarea tcm-module-ta" id="tcm-mod-acupoint" rows="2" placeholder="推荐穴位、外治方法…"></textarea>
          </div>
          <div class="tcm-module-card">
            <div class="tcm-module-label">到院项目</div>
            <textarea class="tcm-textarea tcm-module-ta" id="tcm-mod-visit" rows="2" placeholder="建议到院诊疗项目…"></textarea>
          </div>
          <div class="tcm-module-card tcm-module-card-wide">
            <div class="tcm-module-label">复评节点</div>
            <div style="display:flex;gap:6px;align-items:center">
              <input type="number" id="tcm-mod-days" class="tcm-input" style="width:70px" placeholder="天数" min="1" max="365" />
              <span class="tcm-form-label">天后复评</span>
            </div>
            <textarea class="tcm-textarea tcm-module-ta" id="tcm-mod-goal" rows="1" placeholder="复评目标…" style="margin-top:4px"></textarea>
          </div>
        </div>
        <div style="display:flex;gap:6px;margin-top:8px">
          <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-save-draft-btn">保存草稿</button>
          <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-cancel-draft-btn">取消</button>
        </div>
      </div>
      <div id="tcm-template-panel" style="display:none;" class="tcm-section"></div>
      <div id="tcm-diff-panel"     style="display:none;" class="tcm-section"></div>
      <div id="tcm-summary-panel"  style="display:none;" class="tcm-section"></div>
      <div class="tcm-plan-list">${versionsHtml}</div>
    `;

    // 绑定事件
    document.getElementById('tcm-new-draft-btn')?.addEventListener('click', () => {
      const f = document.getElementById('tcm-draft-form');
      if (f) f.style.display = f.style.display === 'none' ? 'block' : 'none';
    });
    document.getElementById('tcm-cancel-draft-btn')?.addEventListener('click', () => {
      const f = document.getElementById('tcm-draft-form');
      if (f) f.style.display = 'none';
    });
    document.getElementById('tcm-save-draft-btn')?.addEventListener('click', async () => {
      const title = document.getElementById('tcm-draft-title')?.value.trim();
      if (!title) { showToast('请填写方案标题', 'error'); return; }

      // 收集各模块内容
      const modules = [
        { key: 'rest',     label: '作息建议',   id: 'tcm-mod-rest' },
        { key: 'diet',     label: '饮食/食疗',  id: 'tcm-mod-diet' },
        { key: 'exercise', label: '运动建议',   id: 'tcm-mod-exercise' },
        { key: 'emotion',  label: '情志建议',   id: 'tcm-mod-emotion' },
        { key: 'acupoint', label: '穴位/艾灸',  id: 'tcm-mod-acupoint' },
        { key: 'visit',    label: '到院项目',   id: 'tcm-mod-visit' },
      ];
      const days = document.getElementById('tcm-mod-days')?.value.trim();
      const goal = document.getElementById('tcm-mod-goal')?.value.trim();

      // 合并为 Markdown 内容
      const parts = modules
        .map(m => {
          const val = document.getElementById(m.id)?.value.trim();
          return val ? `## ${m.label}\n${val}` : '';
        })
        .filter(Boolean);

      if (days || goal) {
        parts.push(`## 复评节点\n${days ? `复评时间：${days}天后` : ''}${goal ? `\n目标：${goal}` : ''}`);
      }

      if (!parts.length) { showToast('请至少填写一个模块内容', 'error'); return; }
      const content = `# ${title}\n\n${parts.join('\n\n')}`;

      const btn = document.getElementById('tcm-save-draft-btn');
      if (btn) { btn.textContent = '保存中…'; btn.disabled = true; }
      const r = await msg('createDraft', { body: { patient_id: currentPatient.archive_id, title, content } });
      if (btn) { btn.textContent = '保存草稿'; btn.disabled = false; }
      if (r?.success) {
        showToast('草稿已保存', 'success');
        currentPlan = null; currentPlanVersions = null;
        loadPlanDrawer();
        loadBlockC();
      } else showToast(`保存失败：${r?.error || ''}`, 'error');
    });
    document.getElementById('tcm-pick-template-btn')?.addEventListener('click', loadTemplatePanel);

    body.querySelectorAll('[data-publish-id]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const r = await msg('publishPlan', { plan_id: btn.dataset.publishId });
        if (r?.success) { showToast('已发布', 'success'); currentPlan = null; loadPlanDrawer(); loadBlockC(); }
        else showToast(`发布失败：${r?.error || ''}`, 'error');
      });
    });
    body.querySelectorAll('[data-summary-id]').forEach(btn => {
      btn.addEventListener('click', () => loadSummaryPanel(btn.dataset.summaryId));
    });
    body.querySelectorAll('[data-diff-a]').forEach(btn => {
      btn.addEventListener('click', () => loadDiffPanel(btn.dataset.diffA, btn.dataset.diffB));
    });
    body.querySelectorAll('[data-preview-id]').forEach(btn => {
      btn.addEventListener('click', () => openDrawer('tcm-drawer-preview', () => loadPreviewDrawer(btn.dataset.previewId), 'tcm-drawer-plan'));
    });
  }

  // ── 预览与分发抽屉 ────────────────────────────────────────────────────────
  async function loadPreviewDrawer(plan_id) {
    const body = document.getElementById('tcm-drawer-preview-body');
    if (!body) return;
    body.innerHTML = '<div class="tcm-loading-sm">加载预览…</div>';

    const r = await msg('getPlanPreview', { plan_id });
    if (!r?.success) {
      body.innerHTML = `<p class="tcm-hint tcm-hint-err">${esc(r?.error || '加载失败')}</p>`;
      return;
    }
    const d = r.data;
    const isConfirmed   = d.status === 'CONFIRMED';
    const isDistributed = d.status === 'DISTRIBUTED';
    const isDraft       = d.status === 'DRAFT';

    const tabsHtml = `
      <div class="tcm-tab-bar" id="tcm-preview-tabs">
        <button class="tcm-tab tcm-tab-active" data-tab="his">HIS版</button>
        <button class="tcm-tab" data-tab="h5">患者H5版</button>
        <button class="tcm-tab" data-tab="mgmt">管理端</button>
        <button class="tcm-tab" data-tab="change">变更清单</button>
      </div>
      <div id="tcm-preview-panel-his" class="tcm-tab-panel">
        <div class="tcm-preview-label">HIS 病历可直接粘贴此文本：</div>
        <textarea class="tcm-textarea tcm-preview-textarea" rows="8" readonly>${esc(d.his_text)}</textarea>
        <button class="tcm-btn tcm-btn-secondary tcm-btn-xs" id="tcm-copy-his-btn">复制</button>
      </div>
      <div id="tcm-preview-panel-h5" class="tcm-tab-panel" style="display:none">
        <div class="tcm-preview-label">患者 H5 端显示版本：</div>
        <div class="tcm-preview-h5-content">${esc(d.patient_h5).replace(/\n/g, '<br>')}</div>
      </div>
      <div id="tcm-preview-panel-mgmt" class="tcm-tab-panel" style="display:none">
        <div class="tcm-preview-label">管理端结构化字段：</div>
        <div class="tcm-mgmt-field"><span class="tcm-mgmt-key">证候：</span><span>${esc(d.management.syndrome)}</span></div>
        <div class="tcm-mgmt-field"><span class="tcm-mgmt-key">风险：</span><span>${esc(d.management.risk_level)}</span></div>
        <div class="tcm-mgmt-field"><span class="tcm-mgmt-key">随访间隔：</span><span>${d.management.followup_days} 天</span></div>
        <div class="tcm-mgmt-field"><span class="tcm-mgmt-key">方案模块：</span><span>${esc((d.management.modules||[]).join('、') || '—')}</span></div>
      </div>
      <div id="tcm-preview-panel-change" class="tcm-tab-panel" style="display:none">
        <div class="tcm-preview-label">分发将执行以下变更：</div>
        <ul class="tcm-change-list">
          ${(d.change_list||[]).map(item => `<li>${esc(item)}</li>`).join('')}
        </ul>
      </div>
      <div class="tcm-preview-actions">
        ${isDraft ? `<button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-preview-confirm-btn">✓ 确认方案</button>` : ''}
        ${isConfirmed ? `<button class="tcm-btn tcm-btn-distribute tcm-btn-sm" id="tcm-preview-distribute-btn">🚀 一键分发</button>` : ''}
        ${isDistributed ? `<div class="tcm-distributed-badge">✓ 已分发</div>` : ''}
      </div>
      <div id="tcm-distribute-result" style="display:none"></div>
    `;

    body.innerHTML = tabsHtml;

    // Tab 切换
    body.querySelectorAll('.tcm-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        body.querySelectorAll('.tcm-tab').forEach(t => t.classList.remove('tcm-tab-active'));
        body.querySelectorAll('.tcm-tab-panel').forEach(p => p.style.display = 'none');
        tab.classList.add('tcm-tab-active');
        const panelId = `tcm-preview-panel-${tab.dataset.tab}`;
        const panel = document.getElementById(panelId);
        if (panel) panel.style.display = 'block';
      });
    });

    // 复制 HIS 文本
    document.getElementById('tcm-copy-his-btn')?.addEventListener('click', () => {
      const ta = body.querySelector('.tcm-preview-textarea');
      if (ta) {
        navigator.clipboard.writeText(ta.value)
          .then(() => showToast('已复制到剪贴板', 'success'))
          .catch(() => { ta.select(); document.execCommand('copy'); showToast('已复制到剪贴板', 'success'); });
      }
    });

    // 确认方案
    document.getElementById('tcm-preview-confirm-btn')?.addEventListener('click', async () => {
      const btn = document.getElementById('tcm-preview-confirm-btn');
      if (btn) { btn.textContent = '确认中…'; btn.disabled = true; }
      const r2 = await msg('confirmPlan', { plan_id });
      if (r2?.success) {
        showToast('方案已确认', 'success');
        loadPreviewDrawer(plan_id);
        loadBlockC();
      } else {
        showToast(`确认失败：${r2?.error || ''}`, 'error');
        if (btn) { btn.textContent = '✓ 确认方案'; btn.disabled = false; }
      }
    });

    // 一键分发
    document.getElementById('tcm-preview-distribute-btn')?.addEventListener('click', () => doDistribute(plan_id));
  }

  async function doDistribute(plan_id) {
    const resultEl = document.getElementById('tcm-distribute-result');
    const btn      = document.getElementById('tcm-preview-distribute-btn');
    if (resultEl) { resultEl.style.display = 'block'; resultEl.innerHTML = '<div class="tcm-loading-sm">分发中…</div>'; }
    if (btn)      { btn.disabled = true; btn.textContent = '分发中…'; }

    const r = await msg('distributePlan', { plan_id, auto_followup_days: 7 });
    if (!r?.success) {
      if (resultEl) resultEl.innerHTML = `<p class="tcm-hint tcm-hint-err">分发失败：${esc(r?.error || '')}</p>`;
      if (btn)      { btn.disabled = false; btn.textContent = '🚀 一键分发'; }
      return;
    }

    const d = r.data;
    const resultsHtml = Object.entries(d.results || {}).map(([target, res]) => {
      const label = { his: 'HIS端', patient_h5: '患者H5端', management: '管理端' }[target] || target;
      const icon  = res.ok ? '✓' : '✗';
      const cls   = res.ok ? 'tcm-dist-ok' : 'tcm-dist-fail';
      const detail = res.summary || res.message || res.intervention_id || (res.ok ? '成功' : '失败');
      return `<div class="tcm-distribute-result-row ${cls}"><span>${icon} ${label}</span><span class="tcm-dist-detail">${esc(detail)}</span></div>`;
    }).join('');

    const followupHtml = d.followup_created
      ? `<div class="tcm-dist-followup">✓ 随访计划已创建（ID: ${esc(d.followup_plan_id || '')}）</div>`
      : '';

    if (resultEl) {
      resultEl.innerHTML = `
        <div class="tcm-distribute-result">
          <div class="tcm-dist-title">分发结果</div>
          ${resultsHtml}
          ${followupHtml}
        </div>`;
    }
    if (btn) btn.remove();

    showToast('方案已成功分发', 'success');
    loadBlockC();
    loadBlockD();

    // 分发成功后弹出套餐推荐
    showPackageRecommendation(currentPatient.archive_id);
  }

  async function showPackageRecommendation(patient_id) {
    const r = await msg('getPackageRecommendation', { patient_id });
    if (!r?.success) return;
    const d = r.data;

    // 找推荐套餐
    const recommended = (d.packages || []).find(p => p.recommended) || d.packages?.[0];
    if (!recommended) return;

    // 在预览抽屉结果区插入套餐推荐卡
    const resultEl = document.getElementById('tcm-distribute-result');
    if (!resultEl) return;

    const pkgHtml = `
      <div class="tcm-package-card">
        <div class="tcm-package-header">
          <span class="tcm-package-badge">推荐套餐</span>
          <span class="tcm-package-name">${esc(recommended.name)}</span>
          <span class="tcm-package-cycle">${esc(recommended.cycle)}</span>
        </div>
        <div class="tcm-package-reason">${esc(recommended.reason)}</div>
        <div class="tcm-package-script">"${esc(recommended.script)}"</div>
        <ul class="tcm-package-items">
          ${(recommended.items || []).map(item => `<li>${esc(item)}</li>`).join('')}
        </ul>
        <div class="tcm-package-actions">
          <button class="tcm-btn tcm-btn-primary tcm-btn-xs" id="tcm-pkg-confirm-btn">确认开通</button>
          <button class="tcm-btn tcm-btn-secondary tcm-btn-xs" id="tcm-pkg-dismiss-btn">暂不处理</button>
        </div>
      </div>`;

    resultEl.insertAdjacentHTML('beforeend', pkgHtml);

    document.getElementById('tcm-pkg-confirm-btn')?.addEventListener('click', () => {
      showToast(`已确认开通「${recommended.name}」`, 'success');
      document.querySelector('.tcm-package-card')?.remove();
    });
    document.getElementById('tcm-pkg-dismiss-btn')?.addEventListener('click', () => {
      document.querySelector('.tcm-package-card')?.remove();
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
    if (!templates.length) { panel.innerHTML = '<div class="tcm-section-title">模板库</div><p class="tcm-hint">暂无模板</p>'; return; }
    panel.innerHTML = `
      <div class="tcm-section-title">模板库 <button class="tcm-close-panel" data-panel="tcm-template-panel">×</button></div>
      ${templates.slice(0, 10).map(t => `
        <div class="tcm-template-item">
          <div class="tcm-template-name">${esc(t.name)}</div>
          <div class="tcm-template-cat">${esc(t.category || t.guidance_type || '')}</div>
          <button class="tcm-state-btn" data-use-tpl-id="${esc(t.template_id || t.id)}">使用此模板</button>
        </div>`).join('')}`;
    panel.querySelector('.tcm-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });
    panel.querySelectorAll('[data-use-tpl-id]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!currentPatient?.archive_id) { showToast('请先选择患者', 'error'); return; }
        btn.textContent = '创建中…'; btn.disabled = true;
        const tResp = await msg('getTemplate', { template_id: btn.dataset.useTplId });
        if (!tResp?.success) {
          btn.textContent = '使用此模板'; btn.disabled = false;
          showToast(`模板加载失败：${tResp?.error || ''}`, 'error');
          return;
        }
        const tpl = tResp.data;
        const r = await msg('createDraft', {
          body: {
            patient_id: currentPatient.archive_id,
            source: 'template',
            title: tpl.name || '方案模板',
            content: tpl.content || '',
          }
        });
        btn.textContent = '使用此模板'; btn.disabled = false;
        if (r?.success) {
          panel.style.display = 'none';
          currentPlanVersions = null;
          loadPlanDrawer();
          loadBlockC();
          showToast('已从模板创建草稿', 'success');
        } else showToast(`创建失败：${r?.error || ''}`, 'error');
      });
    });
  }

  async function loadDiffPanel(idA, idB) {
    const panel = document.getElementById('tcm-diff-panel');
    if (!panel) return;
    panel.style.display = 'block';
    panel.innerHTML = '<div class="tcm-section-title">版本对比</div><div class="tcm-loading-sm">对比中…</div>';
    const r = await msg('diffPlans', { plan_id_a: idA, plan_id_b: idB });
    const lines = r?.success ? (r.data?.diff_lines || r.data?.lines || []) : [];
    const linesHtml = lines.map(line => {
      const s = typeof line === 'string' ? line : (line.text || line.content || '');
      if (s.startsWith('+++') || s.startsWith('---')) return '';          // skip file headers
      if (s.startsWith('@@'))  return `<div class="tcm-diff-ctx" style="color:var(--tcm-text-muted);font-style:italic">${esc(s)}</div>`;
      if (s.startsWith('+'))   return `<div class="tcm-diff-add">+ ${esc(s.slice(1))}</div>`;
      if (s.startsWith('-'))   return `<div class="tcm-diff-del">- ${esc(s.slice(1))}</div>`;
      return `<div class="tcm-diff-ctx">  ${esc(s.startsWith(' ') ? s.slice(1) : s)}</div>`;
    }).join('');
    panel.innerHTML = `
      <div class="tcm-section-title">版本对比 <button class="tcm-close-panel" data-panel="tcm-diff-panel">×</button></div>
      <div class="tcm-diff-box">${linesHtml || '<p class="tcm-hint">两版本内容相同</p>'}</div>`;
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
    const text = r.data.his_text || r.data.patient_text || r.data.content || JSON.stringify(r.data);
    panel.innerHTML = `
      <div class="tcm-section-title">方案摘要（HIS格式）<button class="tcm-close-panel" data-panel="tcm-summary-panel">×</button></div>
      <div class="tcm-summary-text">${esc(text)}</div>
      <button class="tcm-btn tcm-btn-secondary tcm-btn-sm" id="tcm-copy-summary-btn">复制到剪贴板</button>`;
    panel.querySelector('.tcm-close-panel')?.addEventListener('click', () => { panel.style.display = 'none'; });
    document.getElementById('tcm-copy-summary-btn')?.addEventListener('click', () => {
      navigator.clipboard.writeText(text).then(() => showToast('已复制', 'success')).catch(() => showToast('复制失败', 'error'));
    });
  }

  // 随访管理抽屉（原随访 Tab）
  async function loadFollowupDrawer() {
    const body = document.getElementById('tcm-drawer-followup-body');
    if (!body) return;
    body.innerHTML = '<div class="tcm-loading-sm">加载随访任务…</div>';

    const [tasksResp, statsResp, feedbackResp] = await Promise.all([
      msg('listFollowupTasks',  { patient_id: currentPatient.archive_id }),
      msg('getRiskStats', {}),
      msg('getPatientFeedback', { patient_id: currentPatient.archive_id, limit: 5 }),
    ]);

    const tasks = tasksResp?.success
      ? (Array.isArray(tasksResp.data) ? tasksResp.data : (tasksResp.data?.items || []))
      : [];

    const tasksHtml = tasks.length
      ? tasks.map(t => `
          <div class="tcm-plan-card">
            <div class="tcm-plan-card-header">
              <span style="color:${t.completed_at ? '#4E7A61' : (t.is_overdue ? '#D95C4A' : '#B8885E')};font-size:12px">
                ${t.completed_at ? `${ICONS.checkCircle} 已完成` : (t.is_overdue ? `${ICONS.warning} 已逾期` : `${ICONS.clock} 待随访`)}
              </span>
              <span class="tcm-plan-date">${esc((t.scheduled_date || t.plan_date || '').slice(0,10))}</span>
            </div>
            <div class="tcm-plan-title">${esc(t.title || t.name || '随访任务')}</div>
            ${t.note || t.content ? `<div class="tcm-plan-preview">${esc((t.note || t.content || '').slice(0,60))}</div>` : ''}
          </div>`).join('')
      : '<div class="tcm-empty"><p>暂无随访任务</p></div>';

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

    const feedbackItems = feedbackResp?.success ? (feedbackResp.data?.items || []) : [];
    const STATUS_CN = { DONE: '已完成', PENDING: '待打卡', SKIPPED: '已跳过', MISSED: '已错过' };
    const feedbackHtml = feedbackItems.length
      ? `<div class="tcm-section"><div class="tcm-section-title">患者反馈摘要</div>${
          feedbackItems.map(fb => `
            <div class="tcm-feedback-item">
              <div class="tcm-feedback-header">
                <span class="tcm-feedback-status tcm-feedback-${(fb.status||'').toLowerCase()}">${STATUS_CN[fb.status] || fb.status || '-'}</span>
                <span class="tcm-feedback-date">${esc((fb.checked_at || fb.created_at || '').slice(0, 10))}</span>
              </div>
              ${fb.note ? `<div class="tcm-feedback-note">备注：${esc(fb.note)}</div>` : ''}
            </div>`).join('')
        }</div>`
      : `<div class="tcm-section"><div class="tcm-section-title">患者反馈摘要</div><p class="tcm-hint">暂无打卡反馈</p></div>`;

    body.innerHTML = `
      <div class="tcm-plan-actions-bar">
        <button class="tcm-btn tcm-btn-primary tcm-btn-sm" id="tcm-create-fw-btn">+ 新建随访</button>
      </div>
      <div id="tcm-followup-create-section" style="display:none;" class="tcm-section">
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
      <div class="tcm-section">
        <div class="tcm-section-title">随访任务（${tasks.length}条）</div>
        ${tasksHtml}
      </div>
      ${feedbackHtml}
      ${statsHtml}
    `;

    document.getElementById('tcm-create-fw-btn')?.addEventListener('click', () => {
      const s = document.getElementById('tcm-followup-create-section');
      if (s) s.style.display = s.style.display === 'none' ? 'block' : 'none';
    });
    document.getElementById('tcm-fw-cancel-btn')?.addEventListener('click', () => {
      const s = document.getElementById('tcm-followup-create-section');
      if (s) s.style.display = 'none';
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
        patient_id: currentPatient.archive_id, title, scheduled_date: dateStr,
      }});
      if (btn) { btn.textContent = '创建'; btn.disabled = false; }
      if (r?.success) { showToast('随访已创建', 'success'); loadFollowupDrawer(); loadBlockD(); }
      else showToast(`创建失败：${r?.error || ''}`, 'error');
    });
  }

  // 召回建议抽屉
  async function loadRecallDrawer() {
    const body = document.getElementById('tcm-drawer-recall-body');
    if (!body) return;
    body.innerHTML = '<div class="tcm-loading-sm">加载召回建议…</div>';

    const resp  = await msg('getRecallSuggestions', { patient_id: currentPatient.archive_id });
    const items = resp?.success ? (resp.data?.items || []) : [];

    const SEV_COLOR = { HIGH: '#D95C4A', MEDIUM: '#B8885E', LOW: '#4E7A61' };
    const SEV_CN    = { HIGH: '高风险',  MEDIUM: '中风险',  LOW: '低风险' };
    const STATUS_CN = { OPEN: '待处理',  ACKED: '已确认',   CLOSED: '已关闭' };

    const itemsHtml = items.length
      ? items.map(item => `
          <div class="tcm-recall-card" data-alert-id="${esc(item.recall_id)}">
            <div class="tcm-recall-header">
              <span class="tcm-recall-sev" style="color:${SEV_COLOR[item.severity]||'#6b7280'}">${SEV_CN[item.severity]||item.severity}</span>
              <span class="tcm-recall-status">${STATUS_CN[item.current_status]||item.current_status}</span>
              <span class="tcm-recall-date">${esc((item.triggered_at||'').slice(0,10))}</span>
            </div>
            <div class="tcm-recall-reason"><strong>触发：</strong>${esc(item.trigger_reason)}</div>
            <div class="tcm-recall-recommend"><strong>建议：</strong>${esc(item.recommendation)}</div>
            ${item.current_status === 'OPEN' ? `
            <div class="tcm-recall-actions">
              <input type="text" class="tcm-input tcm-recall-note-input" placeholder="备注（可选）" style="font-size:11px;padding:5px 8px;margin-bottom:4px;" />
              <div style="display:flex;gap:4px;flex-wrap:wrap;">
                <button class="tcm-btn tcm-btn-primary tcm-btn-xs tcm-recall-accept-btn">${ICONS.check} 接受召回</button>
                <button class="tcm-btn tcm-btn-secondary tcm-btn-xs tcm-recall-plan-btn">${ICONS.pen} 调整方案</button>
                <button class="tcm-btn tcm-btn-secondary tcm-btn-xs tcm-recall-visit-btn">${ICONS.phone} 建议回院</button>
                <button class="tcm-btn tcm-btn-secondary tcm-btn-xs tcm-recall-ignore-btn">${ICONS.xMark} 忽略</button>
              </div>
            </div>` : ''}
          </div>`).join('')
      : '<div class="tcm-empty"><p>当前无待处理召回建议</p></div>';

    body.innerHTML = `<div class="tcm-recall-list">${itemsHtml}</div>`;

    body.querySelectorAll('.tcm-recall-card').forEach(card => {
      const alertId   = card.dataset.alertId;
      const noteInput = card.querySelector('.tcm-recall-note-input');

      card.querySelector('.tcm-recall-accept-btn')?.addEventListener('click', async () => {
        const note = noteInput?.value.trim() || '';
        const r = await msg('handleRecallAction', { alert_id: alertId, recall_action: 'accept', note });
        if (r?.success) { showToast('已接受召回建议', 'success'); loadRecallDrawer(); loadBlockD(); }
        else showToast(`操作失败：${r?.error || ''}`, 'error');
      });
      card.querySelector('.tcm-recall-ignore-btn')?.addEventListener('click', async () => {
        const note = noteInput?.value.trim() || '';
        const r = await msg('handleRecallAction', { alert_id: alertId, recall_action: 'ignore', note });
        if (r?.success) { showToast('已忽略', 'success'); loadRecallDrawer(); loadBlockD(); }
        else showToast(`操作失败：${r?.error || ''}`, 'error');
      });
      card.querySelector('.tcm-recall-plan-btn')?.addEventListener('click', () => {
        openDrawer('tcm-drawer-plan', loadPlanDrawer, 'tcm-drawer-recall');
      });
      card.querySelector('.tcm-recall-visit-btn')?.addEventListener('click', async () => {
        const note = noteInput?.value.trim() || '建议回院就诊';
        const r = await msg('handleRecallAction', { alert_id: alertId, recall_action: 'suggest_visit', note });
        if (r?.success) showToast('已标记建议回院', 'success');
        else showToast(`操作失败：${r?.error || ''}`, 'error');
      });
    });
  }

  // 工作台抽屉（含当前患者召回 + 全局工作台）
  async function loadWorkbenchDrawer() {
    const body = document.getElementById('tcm-drawer-workbench-body');
    if (!body) return;
    body.innerHTML = '<div class="tcm-loading-sm">加载工作台…</div>';

    // 并行加载：当前患者召回 + 工作台全局数据
    const promises = [msg('getWorkbenchPending', {})];
    if (currentPatient?.archive_id) {
      promises.push(msg('getRecallSuggestions', { patient_id: currentPatient.archive_id }));
    }
    const [wbResp, recallResp] = await Promise.all(promises);

    const data = wbResp?.success ? wbResp.data : null;
    const recallItems = recallResp?.success ? (recallResp.data?.items || []) : [];

    function patientListHtml(list, emptyText) {
      if (!list || !list.length) return `<p class="tcm-hint">${emptyText}</p>`;
      return list.map(p => `
        <div class="tcm-wb-patient-card" data-archive-id="${esc(p.archive_id)}">
          <div class="tcm-wb-patient-name">${esc(p.patient_name)}</div>
          <div class="tcm-wb-patient-meta">
            <span class="tcm-wb-risk-tag tcm-wb-tag-${(p.risk_tag||'').toLowerCase()}">${esc(p.risk_tag||'-')}</span>
            <span class="tcm-wb-date">${esc(p.recent_visit_at||'-')}</span>
          </div>
          <div class="tcm-wb-action">${esc(p.pending_action||'')}</div>
          <div style="display:flex;gap:4px;margin-top:6px;flex-wrap:wrap;">
            <button class="tcm-btn tcm-btn-primary tcm-btn-xs tcm-wb-enter-btn">进入患者→</button>
            <button class="tcm-btn tcm-btn-secondary tcm-btn-xs tcm-wb-recall-btn">召回建议</button>
          </div>
        </div>`).join('');
    }

    const SEV_COLOR = { HIGH: '#D95C4A', MEDIUM: '#B8885E', LOW: '#4E7A61' };
    const SEV_CN    = { HIGH: '高风险',  MEDIUM: '中风险',  LOW: '低风险' };

    // 当前患者召回区
    const currentRecallHtml = currentPatient ? `
      <div class="tcm-wb-section">
        <div class="tcm-wb-section-title">${ICONS.warning} 当前患者召回 — ${esc(currentPatient.name)}
          <span class="tcm-wb-badge tcm-wb-badge-red">${recallItems.length}</span>
        </div>
        ${recallItems.length ? recallItems.map(item => `
          <div class="tcm-recall-card" data-alert-id="${esc(item.recall_id)}">
            <div class="tcm-recall-header">
              <span class="tcm-recall-sev" style="color:${SEV_COLOR[item.severity]||'#6b7280'}">${SEV_CN[item.severity]||item.severity}</span>
              <span class="tcm-recall-date">${esc((item.triggered_at||item.evidence_summary||'').slice(0,10))}</span>
            </div>
            <div class="tcm-recall-reason">${esc(item.trigger_reason||item.evidence_summary||item.recommendation||'')}</div>
            ${item.current_status === 'OPEN' ? `
            <div style="display:flex;gap:4px;margin-top:4px;flex-wrap:wrap;">
              <button class="tcm-btn tcm-btn-primary tcm-btn-xs tcm-recall-accept-btn" data-alert-id="${esc(item.recall_id)}">${ICONS.check} 接受</button>
              <button class="tcm-btn tcm-btn-secondary tcm-btn-xs tcm-recall-ignore-btn" data-alert-id="${esc(item.recall_id)}">${ICONS.xMark} 忽略</button>
            </div>` : ''}
          </div>`).join('')
        : '<p class="tcm-hint">当前患者无待处理召回</p>'}
      </div>` : '';

    const counts = data?.counts || {};
    body.innerHTML = `
      ${currentRecallHtml}
      <div class="tcm-wb-section">
        <div class="tcm-wb-section-title">${ICONS.clock} 今日待复评 <span class="tcm-wb-badge">${counts.reassess_today||0}</span></div>
        ${patientListHtml(data?.reassess_today, '今日无待复评患者')}
      </div>
      <div class="tcm-wb-section">
        <div class="tcm-wb-section-title">${ICONS.bell} 已触发召回 <span class="tcm-wb-badge tcm-wb-badge-red">${counts.recall_triggered||0}</span></div>
        ${patientListHtml(data?.recall_triggered, '当前无召回待处理')}
      </div>
      <div class="tcm-wb-section">
        <div class="tcm-wb-section-title">${ICONS.warning} 随访异常 <span class="tcm-wb-badge tcm-wb-badge-orange">${counts.followup_abnormal||0}</span></div>
        ${patientListHtml(data?.followup_abnormal, '无随访异常患者')}
      </div>
    `;

    // 当前患者召回操作绑定
    body.querySelectorAll('.tcm-recall-accept-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const r = await msg('handleRecallAction', { alert_id: btn.dataset.alertId, recall_action: 'accept', note: '' });
        if (r?.success) { showToast('已接受召回建议', 'success'); loadWorkbenchDrawer(); loadBlockD(); }
        else showToast(`操作失败：${r?.error || ''}`, 'error');
      });
    });
    body.querySelectorAll('.tcm-recall-ignore-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const r = await msg('handleRecallAction', { alert_id: btn.dataset.alertId, recall_action: 'ignore', note: '' });
        if (r?.success) { showToast('已忽略', 'success'); loadWorkbenchDrawer(); loadBlockD(); }
        else showToast(`操作失败：${r?.error || ''}`, 'error');
      });
    });

    body.querySelectorAll('.tcm-wb-patient-card').forEach(card => {
      const archiveId = card.dataset.archiveId;
      card.querySelector('.tcm-wb-enter-btn')?.addEventListener('click', () => {
        closeDrawer('tcm-drawer-workbench');
        currentPatientId = archiveId;
        renderLoading(archiveId);
        sendMsgWithTimeout(
          'patientDetected', { patientId: archiveId },
          (response) => {
            if (response.error) { renderError(response.error); return; }
            renderResult(response.patient, response.context, response.risk, response.warning);
          },
          (errMsg) => renderError(errMsg)
        );
      });
      card.querySelector('.tcm-wb-recall-btn')?.addEventListener('click', () => {
        openDrawer('tcm-drawer-recall', loadRecallDrawer, 'tcm-drawer-workbench');
      });
    });
  }

  // 患者列表抽屉（搜索 + 切换患者）
  async function loadPatientListDrawer() {
    const body = document.getElementById('tcm-drawer-patients-body');
    if (!body) return;

    body.innerHTML = `
      <div class="tcm-patient-list-search">
        <input type="text" id="tcm-pl-search-input" class="tcm-input" placeholder="搜索姓名、手机号、证件号…" autocomplete="off" />
      </div>
      <div id="tcm-pl-list"><div class="tcm-loading-sm">加载患者列表…</div></div>
    `;

    let allPatients = [];
    let searchTimer = null;

    function renderPatientList(list) {
      const listEl = document.getElementById('tcm-pl-list');
      if (!listEl) return;
      if (!list.length) {
        listEl.innerHTML = '<p class="tcm-hint">未找到匹配患者</p>';
        return;
      }
      listEl.innerHTML = list.slice(0, 30).map(p => `
        <div class="tcm-pl-card" data-archive-id="${esc(p.patient_id||p.archive_id)}" data-name="${esc(p.name)}">
          <div class="tcm-pl-name">${esc(p.name)}
            ${p.archive_type ? `<span class="tcm-pl-type">${esc(p.archive_type)}</span>` : ''}
            ${(p.patient_id||p.archive_id) === currentPatient?.archive_id ? '<span class="tcm-pl-current">当前</span>' : ''}
          </div>
          <div class="tcm-pl-meta">
            ${p.gender ? `<span>${p.gender === 'male' ? '男' : '女'}</span>` : ''}
            ${p.age ? `<span>${p.age}岁</span>` : ''}
            ${p.phone ? `<span>${esc(p.phone)}</span>` : ''}
          </div>
        </div>`).join('');

      listEl.querySelectorAll('.tcm-pl-card').forEach(card => {
        card.addEventListener('click', () => {
          const archiveId = card.dataset.archiveId;
          if (!archiveId) return;
          closeDrawer('tcm-drawer-patients');
          currentPatientId = archiveId;
          renderLoading(archiveId);
          sendMsgWithTimeout(
            'patientDetected', { patientId: archiveId },
            (response) => {
              if (response.error) { renderError(response.error); return; }
              renderResult(response.patient, response.context, response.risk, response.warning);
            },
            (errMsg) => renderError(errMsg)
          );
        });
      });
    }

    // 首次加载全部患者
    const initResp = await msg('patientSearch', { keyword: '', pageSize: 50 });
    if (initResp?.success && initResp.data?.items) {
      allPatients = initResp.data.items;
      renderPatientList(allPatients);
    } else {
      const listEl = document.getElementById('tcm-pl-list');
      if (listEl) listEl.innerHTML = '<p class="tcm-hint">加载失败，请确认已登录</p>';
    }

    // 搜索输入防抖
    document.getElementById('tcm-pl-search-input')?.addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      const q = e.target.value.trim();
      if (!q) {
        renderPatientList(allPatients);
        return;
      }
      searchTimer = setTimeout(async () => {
        const listEl = document.getElementById('tcm-pl-list');
        if (listEl) listEl.innerHTML = '<div class="tcm-loading-sm">搜索中…</div>';
        // 先本地过滤
        const local = allPatients.filter(p =>
          p.name?.includes(q) || p.phone?.includes(q) || p.id_number?.includes(q)
        );
        if (local.length) { renderPatientList(local); return; }
        // 远程搜索
        const sr = await msg('patientSearch', { keyword: q, pageSize: 20 });
        renderPatientList(sr?.data?.items || []);
      }, 300);
    });
  }

  // ─── AI Dock ───────────────────────────────────────────────────────────────

  // 当前待发送的图片数据 { mediaType, data }
  let _pendingImage = null;

  function handleChip(chip) {
    const input = document.getElementById('tcm-ai-input');
    const presets = {
      risk:     '请分析当前患者的风险评估结果，给出中医调理建议',
      plan:     '请查看并汇总当前患者的干预方案状态',
      followup: '请查询当前患者的随访任务安排',
      recall:   '请查看当前患者的召回建议',
      summary:  '请生成当前患者的临床摘要',
    };
    if (input) { input.value = presets[chip] || ''; input.focus(); }
  }

  function handleAiSend() {
    const input   = document.getElementById('tcm-ai-input');
    const text    = input?.value.trim();
    if (!text) return;
    if (input) input.value = '';

    const resp = document.getElementById('tcm-ai-response');
    if (!resp) return;

    // 展示问题 + 思考状态
    resp.style.display = 'block';
    resp.innerHTML = `
      <div class="tcm-ai-card">
        <div class="tcm-ai-card-q">${esc(text)}</div>
        <div id="tcm-agent-progress"></div>
      </div>`;
    _showThinking();

    // 禁用输入
    const sendBtn = document.getElementById('tcm-ai-send-btn');
    if (sendBtn) { sendBtn.disabled = true; sendBtn.style.opacity = '0.5'; }

    // 构建患者上下文
    const patientCtx = currentPatient ? {
      id:   currentPatientId,
      name: currentPatient.name,
      age:  currentPatient.age,
      gender: currentPatient.gender,
    } : null;

    // 传递图片 OCR 数据
    const imageData = _pendingImage || null;
    _clearImagePreview();

    // 发送给 background 执行 Agent 循环
    chrome.runtime.sendMessage({
      action:         'agentChat',
      message:        text,
      patientContext: patientCtx,
      imageData:      imageData,
    }, (response) => {
      if (chrome.runtime.lastError) {
        _appendAgentError('无法连接扩展后台：' + chrome.runtime.lastError.message);
        _enableSend();
      }
      // runAgentLoop 完成时也会触发 agentProgress done/error，此处不再处理
    });
  }

  // 处理来自 background 的 agentProgress 消息
  function handleAgentProgress(msg) {
    switch (msg.type) {
      case 'thinking':
        _showThinking();
        break;
      case 'tool_call': {
        const label = TOOL_LABELS[msg.toolName] || msg.toolName;
        _appendStep(msg.toolName, `调用：${label}`, 'tcm-step-calling');
        break;
      }
      case 'tool_done': {
        const label = TOOL_LABELS[msg.toolName] || msg.toolName;
        _updateStep(msg.toolName, `✓ ${label}`, 'tcm-step-done');
        break;
      }
      case 'tool_error': {
        const label = TOOL_LABELS[msg.toolName] || msg.toolName;
        _updateStep(msg.toolName, `✗ ${label}：${msg.error}`, 'tcm-step-error');
        break;
      }
      case 'done':
        _clearThinking();
        _appendAnswer(msg.text);
        _enableSend();
        break;
      case 'error':
        _clearThinking();
        _appendAgentError(msg.text);
        _enableSend();
        break;
    }
  }

  // ── Agent 进度 UI 辅助 ──────────────────────────────────────────────────────

  function _progressEl() {
    return document.getElementById('tcm-agent-progress');
  }

  function _showThinking() {
    const p = _progressEl();
    if (!p) return;
    const existing = p.querySelector('.tcm-agent-thinking');
    if (existing) return; // 已有则不重复
    const el = document.createElement('div');
    el.className = 'tcm-agent-thinking';
    el.innerHTML = `<div class="tcm-dots"><span></span><span></span><span></span></div><span>AI 推理中…</span>`;
    p.appendChild(el);
  }

  function _clearThinking() {
    const p = _progressEl();
    if (!p) return;
    const t = p.querySelector('.tcm-agent-thinking');
    if (t) t.remove();
  }

  function _appendStep(toolName, text, cls) {
    const p = _progressEl();
    if (!p) return;
    const el = document.createElement('div');
    el.className = `tcm-agent-step ${cls}`;
    el.dataset.tool = toolName;
    el.textContent = text;
    p.appendChild(el);
  }

  function _updateStep(toolName, text, cls) {
    const p = _progressEl();
    if (!p) return;
    const el = p.querySelector(`[data-tool="${toolName}"].tcm-agent-step`);
    if (el) {
      el.textContent = text;
      el.className = `tcm-agent-step ${cls}`;
    } else {
      _appendStep(toolName, text, cls);
    }
  }

  function _appendAnswer(text) {
    const p = _progressEl();
    if (!p) return;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
      <div class="tcm-agent-answer">${esc(text)}</div>
      <button class="tcm-tts-btn" title="朗读回答">
        ${ICONS.volume}<span>朗读</span>
      </button>`;
    wrapper.querySelector('.tcm-tts-btn').addEventListener('click', () => speakText(text));
    p.appendChild(wrapper);
    // 滚动到底部
    const respEl = document.getElementById('tcm-ai-response');
    if (respEl) respEl.scrollTop = respEl.scrollHeight;
  }

  function _appendAgentError(text) {
    const p = _progressEl();
    if (!p) return;
    const el = document.createElement('div');
    el.className = 'tcm-agent-error';
    el.textContent = '⚠ ' + text;
    p.appendChild(el);
  }

  function _enableSend() {
    const sendBtn = document.getElementById('tcm-ai-send-btn');
    if (sendBtn) { sendBtn.disabled = false; sendBtn.style.opacity = ''; }
  }

  // ── 语音输入（ASR）──────────────────────────────────────────────────────────
  let _recognition = null;

  function startVoiceInput() {
    const micBtn = document.getElementById('tcm-ai-mic-btn');
    if (!micBtn) return;

    // 若正在录音则停止
    if (_recognition) {
      _recognition.stop();
      _recognition = null;
      micBtn.classList.remove('tcm-active');
      micBtn.title = '语音输入';
      return;
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      showToast('当前浏览器不支持语音输入', 'error');
      return;
    }

    _recognition = new SR();
    _recognition.lang = 'zh-CN';
    _recognition.interimResults = false;
    _recognition.maxAlternatives = 1;

    micBtn.classList.add('tcm-active');
    micBtn.title = '点击停止录音';

    _recognition.onresult = (e) => {
      const transcript = e.results[0][0].transcript;
      const input = document.getElementById('tcm-ai-input');
      if (input) input.value = (input.value ? input.value + ' ' : '') + transcript;
    };
    _recognition.onend = () => {
      _recognition = null;
      micBtn.classList.remove('tcm-active');
      micBtn.title = '语音输入';
    };
    _recognition.onerror = (e) => {
      _recognition = null;
      micBtn.classList.remove('tcm-active');
      micBtn.title = '语音输入';
      if (e.error !== 'no-speech') showToast('语音识别失败：' + e.error, 'error');
    };
    _recognition.start();
  }

  // ── 图片上传 / OCR ──────────────────────────────────────────────────────────

  function handleImageUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) { showToast('请选择图片文件', 'error'); return; }
    // 重置 input 以便同一图片可重复选
    e.target.value = '';

    const reader = new FileReader();
    reader.onload = (re) => {
      const dataUrl = re.result;               // data:image/xxx;base64,...
      const base64  = dataUrl.split(',')[1];
      const mediaType = file.type;
      _pendingImage = { mediaType, data: base64 };

      // 显示缩略图预览
      const previewRow = document.getElementById('tcm-ai-img-preview-row');
      if (previewRow) {
        previewRow.style.display = 'flex';
        previewRow.innerHTML = `
          <div class="tcm-ai-img-preview">
            <img src="${dataUrl}" alt="待发图片" />
            <span>${esc(file.name)}</span>
            <span class="tcm-ai-img-rm" id="tcm-ai-img-rm" title="移除">✕</span>
          </div>`;
        previewRow.querySelector('#tcm-ai-img-rm').addEventListener('click', _clearImagePreview);
      }
    };
    reader.readAsDataURL(file);
  }

  function _clearImagePreview() {
    _pendingImage = null;
    const previewRow = document.getElementById('tcm-ai-img-preview-row');
    if (previewRow) { previewRow.style.display = 'none'; previewRow.innerHTML = ''; }
  }

  // ── TTS ────────────────────────────────────────────────────────────────────

  function speakText(text) {
    if (!window.speechSynthesis) { showToast('当前浏览器不支持语音合成', 'error'); return; }
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang = 'zh-CN';
    utt.rate = 1.0;
    window.speechSynthesis.speak(utt);
  }

  // ─── Toast ─────────────────────────────────────────────────────────────────
  function showToast(text, type) {
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (!sidebar) return;
    const t = document.createElement('div');
    t.className = `tcm-toast tcm-toast-${type}`;
    t.textContent = text;
    sidebar.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  // ─── 渲染入口 ──────────────────────────────────────────────────────────────
  function renderResult(patient, context, risk, warning) {
    currentPatient  = patient;
    currentContext  = context || null;
    currentRisk     = risk;
    // 清除旧缓存
    currentProfile          = null;
    currentMetrics          = null;
    currentRiskTags         = null;
    currentRiskConclusions  = null;
    currentPlan             = null;
    currentPlanVersions     = null;

    createSidebar();
    if (warning) showToast(warning, 'error');

    // 关闭所有抽屉，渲染主面板
    document.querySelectorAll('#' + SIDEBAR_ID + ' .tcm-drawer-overlay').forEach(el => {
      el.style.display = 'none';
    });
    renderDashboard();
  }

  // ─── URL 检测 ───────────────────────────────────────────────────────────────
  async function checkUrl() {
    const config    = await getConfig();
    const patientId = extractPatientId(config.paramNames);

    if (!patientId) {
      if (currentPatientId !== null) {
        currentPatientId = null; currentPatient = null; currentRisk = null;
        currentProfile = null; currentMetrics = null; currentRiskTags = null;
        currentRiskConclusions = null; currentPlan = null;
        const dash = document.getElementById('tcm-dashboard');
        if (dash) dash.innerHTML = `<div class="tcm-idle" id="tcm-idle-state"><div class="tcm-idle-icon">${ICONS.search}</div><p>等待检测患者信息…</p><p class="tcm-hint">当前页面未检测到患者ID参数</p></div>`;
        const dock = document.getElementById('tcm-ai-dock');
        if (dock) dock.style.display = 'none';
        const nameElClear = document.getElementById('tcm-header-patient-name');
        if (nameElClear) nameElClear.textContent = '';
      }
      return;
    }
    if (patientId === currentPatientId) return;
    currentPatientId = patientId;

    createSidebar();
    // 检测到新患者时自动展开侧边栏
    isCollapsed = false;
    const sidebar = document.getElementById(SIDEBAR_ID);
    if (sidebar) sidebar.classList.remove('tcm-collapsed');
    chrome.storage.local.set({ sidebarCollapsed: false });
    renderLoading(patientId);

    sendMsgWithTimeout(
      'patientDetected', { patientId },
      (response) => {
        if (response.error) { renderError(response.error); return; }
        renderResult(response.patient, response.context, response.risk, response.warning);
      },
      (errMsg) => renderError(errMsg)
    );
  }

  function debouncedCheck() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(checkUrl, DEBOUNCE_MS);
  }

  // ─── 手动搜索监听 ───────────────────────────────────────────────────────────
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    // Agent 进度更新
    if (message.action === 'agentProgress') {
      handleAgentProgress(message);
      sendResponse({ ok: true });
      return;
    }

    if (message.action !== 'manualSearch') return;
    const keyword = message.keyword?.trim();
    if (!keyword) { sendResponse({ ok: false, error: '请输入患者姓名或档案号' }); return; }

    createSidebar();
    isCollapsed = false;
    document.getElementById(SIDEBAR_ID)?.classList.remove('tcm-collapsed');
    currentPatientId = keyword;
    renderLoading(keyword);

    sendMsgWithTimeout(
      'patientDetected', { patientId: keyword },
      (response) => {
        if (response.error) { renderError(response.error); return; }
        renderResult(response.patient, response.context, response.risk, response.warning);
      },
      (errMsg) => renderError(errMsg)
    );
    sendResponse({ ok: true });
  });

  // ─── History API 拦截 ───────────────────────────────────────────────────────
  const _push    = history.pushState.bind(history);
  const _replace = history.replaceState.bind(history);
  history.pushState    = (...args) => { _push(...args);    debouncedCheck(); };
  history.replaceState = (...args) => { _replace(...args); debouncedCheck(); };
  window.addEventListener('popstate',   debouncedCheck);
  window.addEventListener('hashchange', debouncedCheck);

  // ─── 页面消息监听（穿透 isolated world）─────────────────────────────────────
  window.addEventListener('message', (e) => {
    if (!e.data || e.data.__tcm !== true) return;

    // 立即展开指令
    if (e.data.type === 'expand') {
      isCollapsed = false;
      const sidebar = document.getElementById(SIDEBAR_ID);
      if (sidebar) sidebar.classList.remove('tcm-collapsed');
      chrome.storage.local.set({ sidebarCollapsed: false });
    }

    // 展开 + 立即切换患者（不等 debounce）
    if (e.data.type === 'patient-select' && e.data.patientId) {
      isCollapsed = false;
      createSidebar();
      const sidebar = document.getElementById(SIDEBAR_ID);
      if (sidebar) sidebar.classList.remove('tcm-collapsed');
      chrome.storage.local.set({ sidebarCollapsed: false });

      if (e.data.patientId !== currentPatientId) {
        currentPatientId = e.data.patientId;
        renderLoading(e.data.patientId);
        sendMsgWithTimeout(
          'patientDetected', { patientId: e.data.patientId },
          (response) => {
            if (response.error) { renderError(response.error); return; }
            renderResult(response.patient, response.context, response.risk, response.warning);
          },
          (errMsg) => renderError(errMsg)
        );
      }
    }
  });

  // ─── 初始化 ────────────────────────────────────────────────────────────────
  async function init() {
    const config = await getConfig();
    isCollapsed  = config.sidebarCollapsed === true;
    createSidebar();
    if (isCollapsed) {
      const s = document.getElementById(SIDEBAR_ID);
      if (s) {
        s.classList.add('tcm-collapsed');
        s.style.setProperty('top', '50%', 'important');
        s.style.setProperty('height', '92px', 'important');
        s.style.setProperty('transform', 'translateY(-50%)', 'important');
        s.style.setProperty('width', '36px', 'important');
      }
    }

    // 吸附/浮动模式初始化
    if (isDocked) enterDockedMode();
    else          enterFloatingMode();
    updateDockToggleIcon();
    bindResizeHandle();

    checkUrl();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

})();
