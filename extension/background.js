// 后台：统一负责与线索服务器通信，并在工具栏图标上显示识别结果。
try { importScripts('config.js'); } catch (e) { /* 手动安装时可能没有预置配置 */ }

const DEFAULTS = {server: 'http://localhost:8000', token: '', user: '', autoReport: true, autoExtract: true, annotate: true};

async function config() {
  return {...DEFAULTS, ...(await chrome.storage.sync.get(Object.keys(DEFAULTS)))};
}

// 首次安装或升级时，写入服务器下发的预置配置（不覆盖用户已填写的令牌）
async function applyPreset() {
  const preset = self.SCOUT_PRESET;
  if (!preset || !preset.token) return;
  const cur = await chrome.storage.sync.get(['token', 'presetToken']);
  if (!cur.token || cur.presetToken !== preset.token) {
    await chrome.storage.sync.set({server: preset.server, token: preset.token, user: preset.user || '', presetToken: preset.token});
  }
}
chrome.runtime.onInstalled.addListener(applyPreset);
chrome.runtime.onStartup.addListener(applyPreset);

async function api(path, opts = {}) {
  const cfg = await config();
  if (!cfg.token) throw new Error('请先在插件设置中填写服务器地址和个人令牌');
  const r = await fetch(cfg.server.replace(/\/$/, '') + path, {
    ...opts,
    headers: {'Content-Type': 'application/json', 'X-Token': cfg.token, ...(opts.headers || {})},
  });
  if (r.status === 401) throw new Error('令牌无效或已过期，请在前台“浏览器插件”页面重新下载或生成令牌');
  if (!r.ok) throw new Error(`服务器返回 ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

// 本次浏览器会话的统计与去重
const session = {submitted: new Set(), added: 0, looked: new Map()};

async function ingest(domains, source, context, priority = 8) {
  const fresh = domains.filter(d => !session.submitted.has(d));
  if (!fresh.length) return {received: 0, added: 0};
  fresh.forEach(d => session.submitted.add(d));
  const r = await api('/api/ingest', {method: 'POST', body: JSON.stringify({domains: fresh, source, context, priority})});
  session.added += r.added || 0;
  return r;
}

async function lookupBatch(domains) {
  const need = domains.filter(d => !session.looked.has(d)).slice(0, 300);
  if (need.length) {
    const found = await api('/api/lookup_batch', {method: 'POST', body: JSON.stringify({domains: need})});
    need.forEach(d => session.looked.set(d, found[d] || null));
  }
  return Object.fromEntries(domains.filter(d => session.looked.get(d)).map(d => [d, session.looked.get(d)]));
}

function setBadge(tabId, text, color) {
  chrome.action.setBadgeText({tabId, text});
  if (color) chrome.action.setBadgeBackgroundColor({tabId, color});
}
const GRADE_COLORS = {A: '#16a34a', B: '#2563eb', C: '#d97706', D: '#9ca3af'};

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      const cfg = await config();
      const tabId = sender.tab?.id;
      switch (msg.type) {
        case 'settings':
          return reply(cfg);
        case 'visited': {
          if (!msg.platform || tabId == null) return reply({});
          setBadge(tabId, msg.platform.slice(0, 4), '#64748b');
          if (!cfg.token) return reply({});
          const host = msg.host.replace(/^www\./, '');
          let info = await api('/api/lookup?domain=' + encodeURIComponent(host));
          if (!info.exists && cfg.autoReport) {
            await ingest([host], 'extension-visit', msg.url, 8);
            info = {exists: true, status: 'new'};
          }
          if (info.grade) setBadge(tabId, info.grade, GRADE_COLORS[info.grade]);
          else if (info.exists) setBadge(tabId, '已入', '#64748b');
          return reply(info);
        }
        case 'autoExtract': {
          if (!cfg.token || !cfg.autoExtract) return reply({skipped: true});
          const r = await ingest(msg.domains, 'extension-auto', msg.url, 7);
          if (tabId != null && r.added) setBadge(tabId, '+' + Math.min(r.added, 999), '#2563eb');
          return reply(r);
        }
        case 'lookupBatch':
          if (!cfg.token || !cfg.annotate) return reply({});
          return reply(await lookupBatch(msg.domains));
        case 'lookup':
          return reply(await api('/api/lookup?domain=' + encodeURIComponent(msg.host)));
        case 'ingest':
          session.submitted.clear();   // 手动操作不去重
          return reply(await ingest(msg.domains, msg.source, msg.context, msg.priority));
        case 'ping':
          return reply(await api('/api/auth/me'));
        case 'stats':
          return reply({submitted: session.submitted.size, added: session.added, user: cfg.user, server: cfg.server, hasToken: !!cfg.token});
      }
      reply({error: '未知消息'});
    } catch (e) {
      reply({error: String(e.message || e)});
    }
  })();
  return true;
});

// 右键菜单：把链接指向的站点加入队列
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({id: 'add-link', title: '加入独立站采集队列', contexts: ['link']});
});
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== 'add-link' || !info.linkUrl) return;
  try {
    const host = new URL(info.linkUrl).hostname.replace(/^www\./, '');
    await ingest([host], 'extension-link', tab?.url, 9);
    if (tab?.id != null) setBadge(tab.id, '+1', '#2563eb');
  } catch (e) { console.warn(e); }
});
