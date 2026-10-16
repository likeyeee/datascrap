const $ = id => document.getElementById(id);
const esc = s => (s ?? '').toString().replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const COLORS = {A: '#16a34a', B: '#2563eb', C: '#d97706', D: '#9ca3af'};
let tab, detected, cfg;

const send = msg => chrome.runtime.sendMessage(msg);
const toTab = msg => chrome.tabs.sendMessage(tab.id, msg);
const show = text => { $('msg').textContent = text; };

async function refreshStats() {
  const s = await send({type: 'stats'});
  $('s-sub').textContent = s.submitted || 0;
  $('s-add').textContent = s.added || 0;
  $('who').textContent = s.user || '';
}

async function init() {
  cfg = await send({type: 'settings'});
  document.querySelectorAll('[data-k]').forEach(i => {
    i.checked = !!cfg[i.dataset.k];
    i.onchange = () => chrome.storage.sync.set({[i.dataset.k]: i.checked});
  });
  refreshStats();
  if (!cfg.token) {
    $('site').innerHTML = '还没有配置令牌。请在线索工作台的“浏览器插件”页面下载插件包，或在<a href="options.html" target="_blank">设置</a>中填写。';
    $('add').disabled = $('extract').disabled = true;
    return;
  }
  [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  try {
    detected = await toTab({type: 'detect'});
  } catch (e) {
    $('site').innerHTML = '<span class="muted">此页面无法识别（浏览器内部页面，或需要刷新页面）</span>';
    $('add').disabled = $('extract').disabled = true;
    return;
  }
  const host = detected.host.replace(/^www\./, '');
  if (detected.listing) $('add').disabled = true;
  const info = detected.listing ? null : await send({type: 'lookup', host});
  let html = `<div class="site"><div class="grade" style="background:${COLORS[info?.grade] || '#9ca3af'}">${esc(info?.grade || '–')}</div><div style="min-width:0">
    <b>${esc(host)}</b><div class="muted">${detected.listing ? '列表页：自动提取已' + (cfg.autoExtract ? '开启' : '关闭') : '平台：' + esc(detected.platform || '未识别为店铺')}</div>`;
  if (info?.error) html += `<div class="muted" style="color:#dc2626">${esc(info.error)}</div>`;
  else if (info?.exists) {
    html += info.grade
      ? `<div>${info.total_score} 分 ${info.chinese_type ? `<span class="badge">${esc(info.chinese_type)}</span>` : ''}</div><div class="muted">${esc(info.main_products || '')}</div>`
      : `<div class="muted">已在库中，等待${info.status === 'new' ? '采集' : '处理'}</div>`;
    $('add').textContent = '重新加入队列';
  }
  $('site').innerHTML = html + '</div></div>';
}

$('add').onclick = async () => {
  const r = await send({type: 'ingest', domains: [detected.host], source: 'extension', context: tab.url, priority: 10});
  show(r.error ? r.error : (r.added ? '已加入采集队列，稍后可在工作台查看评分' : '站点已在库中'));
  refreshStats();
};

$('extract').onclick = async () => {
  const {domains, url} = await toTab({type: 'extract'});
  if (!domains.length) return show('本页没有找到外部站点链接');
  const r = await send({type: 'ingest', domains, source: 'extension-page', context: url, priority: 7});
  show(r.error ? r.error : `提取 ${domains.length} 个域名，新增 ${r.added} 个（平台、社媒等已自动过滤）`);
  refreshStats();
};

$('dash').onclick = e => {
  e.preventDefault();
  chrome.tabs.create({url: (cfg?.server || 'http://localhost:8000') + '/app'});
};

init();
