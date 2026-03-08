/**
 * popup.js - 配置页面逻辑
 * 治未病·诊中助手
 */

(function () {
  'use strict';

  const DEFAULT_SERVER = 'http://localhost:8015';
  const DEFAULT_PARAMS = 'patient_id,pid,id,patientId,patient';

  // ── DOM 引用 ──────────────────────────────────────────────────────────────
  const serverInput   = document.getElementById('server-url');
  const paramInput    = document.getElementById('param-names');
  const saveBtn       = document.getElementById('save-btn');
  const connResult    = document.getElementById('conn-result');
  const searchInput   = document.getElementById('search-input');
  const searchBtn     = document.getElementById('search-btn');
  const searchResult  = document.getElementById('search-result');
  const statusDot     = document.getElementById('status-dot');
  const statusText    = document.getElementById('status-text');
  const openPlatform  = document.getElementById('open-platform');
  const apiKeyInput      = document.getElementById('api-key');
  const searchKeyInput   = document.getElementById('search-key');
  const claudeUrlInput   = document.getElementById('claude-base-url');
  const claudeModelInput = document.getElementById('claude-model');

  // ── 初始化：读取已保存配置 ────────────────────────────────────────────────
  chrome.storage.local.get(['serverUrl', 'paramNames', 'anthropicApiKey', 'braveSearchKey', 'claudeBaseUrl', 'claudeModel'], (result) => {
    let savedUrl = result.serverUrl || DEFAULT_SERVER;
    // 自动迁移旧端口到当前默认端口
    const OLD_PORTS = [':8010', ':8011', ':8012', ':8013', ':8014'];
    if (OLD_PORTS.some(p => savedUrl.includes(p))) {
      savedUrl = DEFAULT_SERVER;
      chrome.storage.local.set({ serverUrl: savedUrl });
    }
    serverInput.value = savedUrl;
    paramInput.value  = result.paramNames || DEFAULT_PARAMS;
    if (apiKeyInput)      apiKeyInput.value      = result.anthropicApiKey || '';
    if (searchKeyInput)   searchKeyInput.value   = result.braveSearchKey  || '';
    if (claudeUrlInput)   claudeUrlInput.value   = result.claudeBaseUrl   || '';
    if (claudeModelInput) claudeModelInput.value = result.claudeModel     || '';
    updatePlatformLink(serverInput.value);
    detectCurrentTab();
  });

  // ── 保存配置 ──────────────────────────────────────────────────────────────
  saveBtn.addEventListener('click', async () => {
    const serverUrl  = serverInput.value.trim().replace(/\/$/, '') || DEFAULT_SERVER;
    const paramNames = paramInput.value.trim() || DEFAULT_PARAMS;

    // 验证URL格式
    try {
      new URL(serverUrl);
    } catch (_) {
      connResult.textContent = '地址格式不正确，请输入完整URL（含 http:// 或 https://）';
      connResult.className = 'fail';
      return;
    }

    saveBtn.textContent = '保存中…';
    saveBtn.disabled = true;
    connResult.textContent = '';
    connResult.className = '';

    // 测试连接
    const ok = await testConnection(serverUrl);

    const anthropicApiKey = apiKeyInput?.value.trim() || '';
    const braveSearchKey  = searchKeyInput?.value.trim() || '';
    const claudeBaseUrl   = claudeUrlInput?.value.trim().replace(/\/$/, '') || '';
    const claudeModel     = claudeModelInput?.value.trim() || '';
    chrome.storage.local.set({ serverUrl, paramNames, anthropicApiKey, braveSearchKey, claudeBaseUrl, claudeModel }, () => {
      if (ok) {
        connResult.textContent = '连接成功，配置已保存 ✓';
        connResult.className = 'ok';
      } else {
        connResult.textContent = '配置已保存，但无法连接到服务器，请确认服务已启动并已登录';
        connResult.className = 'fail';
      }
      saveBtn.textContent = '已保存 ✓';
      saveBtn.className = 'btn btn-success';
      setTimeout(() => {
        saveBtn.textContent = '保存配置';
        saveBtn.className = 'btn btn-primary';
        saveBtn.disabled = false;
      }, 2000);

      updatePlatformLink(serverUrl);
    });
  });

  // ── 测试服务器连接 ────────────────────────────────────────────────────────
  async function testConnection(serverUrl) {
    try {
      const resp = await fetch(`${serverUrl}/tools/plugin/patient/search?q=test&page_size=1`, {
        credentials: 'include',
        signal: AbortSignal.timeout(5000)
      });
      return resp.status < 500;
    } catch (_) {
      return false;
    }
  }

  // ── 检测当前标签页状态 ────────────────────────────────────────────────────
  function detectCurrentTab() {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || tabs.length === 0) {
        setStatus('idle', '无法获取当前页面信息');
        return;
      }
      const tab = tabs[0];
      const url = tab.url || '';

      if (url.startsWith('chrome://') || url.startsWith('chrome-extension://') || url.startsWith('edge://')) {
        setStatus('idle', '当前为浏览器内置页面，无法注入');
        return;
      }

      // 读取配置中的参数名并检测URL
      chrome.storage.local.get(['paramNames'], (result) => {
        const paramNames = (result.paramNames || DEFAULT_PARAMS)
          .split(',').map(s => s.trim()).filter(Boolean);
        const detected = extractFromUrl(url, paramNames);
        if (detected) {
          setStatus('active', `已检测到患者ID：${detected}`);
        } else {
          setStatus('idle', `当前页面未检测到患者ID参数`);
        }
      });
    });
  }

  function extractFromUrl(urlStr, paramNames) {
    try {
      const url = new URL(urlStr);
      for (const name of paramNames) {
        const val = url.searchParams.get(name);
        if (val && val.trim()) return val.trim();
      }
    } catch (_) {}
    return null;
  }

  function setStatus(type, text) {
    statusText.textContent = text;
    statusDot.className = 'status-dot';
    if (type === 'active') statusDot.classList.add('active');
    if (type === 'error')  statusDot.classList.add('error');
  }

  // ── 打开治未病平台链接 ────────────────────────────────────────────────────
  function updatePlatformLink(serverUrl) {
    openPlatform.onclick = () => {
      chrome.tabs.create({ url: serverUrl || DEFAULT_SERVER });
    };
  }

  // ── 手动搜索 ──────────────────────────────────────────────────────────────
  searchBtn.addEventListener('click', doSearch);
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doSearch();
  });

  function doSearch() {
    const keyword = searchInput.value.trim();
    if (!keyword) {
      setSearchResult('请输入患者姓名或档案号', 'error');
      return;
    }

    searchBtn.disabled = true;
    searchBtn.textContent = '搜索中…';
    setSearchResult('', '');

    // 向当前页的 content.js 发送手动搜索消息
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || tabs.length === 0) {
        setSearchResult('无法获取当前页面', 'error');
        resetSearchBtn();
        return;
      }
      const tab = tabs[0];
      const url = tab.url || '';

      // 检查是否可以注入（非内置页面）
      if (url.startsWith('chrome://') || url.startsWith('chrome-extension://')) {
        setSearchResult('请在HIS系统页面中使用搜索功能', 'error');
        resetSearchBtn();
        return;
      }

      chrome.tabs.sendMessage(tab.id, { action: 'manualSearch', keyword }, (response) => {
        if (chrome.runtime.lastError) {
          // content script 可能还未注入，尝试先注入
          chrome.scripting.executeScript(
            { target: { tabId: tab.id }, files: ['content.js'] },
            () => {
              if (chrome.runtime.lastError) {
                setSearchResult('无法在当前页面注入脚本，请刷新页面重试', 'error');
                resetSearchBtn();
                return;
              }
              // 等待脚本初始化后再发送
              setTimeout(() => {
                chrome.tabs.sendMessage(tab.id, { action: 'manualSearch', keyword }, (resp2) => {
                  handleSearchResponse(resp2);
                });
              }, 500);
            }
          );
          return;
        }
        handleSearchResponse(response);
      });
    });
  }

  function handleSearchResponse(response) {
    if (!response) {
      setSearchResult('搜索超时，请确认页面已加载', 'error');
    } else if (response.ok === false) {
      setSearchResult(response.error || '搜索失败', 'error');
    } else {
      setSearchResult('正在分析，请查看右侧边栏…', 'success');
    }
    resetSearchBtn();
  }

  function setSearchResult(text, type) {
    searchResult.textContent = text;
    searchResult.className = 'search-result ' + (type || '');
  }

  function resetSearchBtn() {
    searchBtn.disabled = false;
    searchBtn.textContent = '搜索';
  }

})();
