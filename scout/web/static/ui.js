/* 线索雷达 · 前后台共用：接口、登录守卫、路由、外壳、表格、弹出层、标签、图表 */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
export const fmt = n => n == null || n === '' ? '-' : Number(n).toLocaleString('zh-CN');
export const pct = (a, b) => b ? `${(100 * a / b).toFixed(1)}%` : '-';
export function compact(n) {
  if (n == null) return '-';
  if (n >= 1e8) return (n / 1e8).toFixed(1) + ' 亿';
  if (n >= 1e4) return (n / 1e4).toFixed(1) + ' 万';
  return fmt(n);
}
function toDate(iso) { return new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z'); }
export function ago(iso) {
  if (!iso) return '-';
  const t = toDate(iso), s = (Date.now() - t) / 1000;
  if (s < 60) return '刚刚';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} 天前`;
  return dateStr(iso);
}
export function dateStr(iso) {
  if (!iso) return '-';
  const t = toDate(iso);
  const p = n => String(n).padStart(2, '0');
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())} ${p(t.getHours())}:${p(t.getMinutes())}`;
}

/* ---------- 图标（16px 线性） ---------- */
const P = {
  table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
  board: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  plug: '<path d="M9 7V2M15 7V2M6 7h12v4a6 6 0 0 1-12 0zM12 17v5"/>',
  pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  radio: '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4M19.1 4.9a10 10 0 0 1 0 14.2M4.9 19.1a10 10 0 0 1 0-14.2"/>',
  db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  users: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  coin: '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9 9.5c0-1.4 1.3-2.5 3-2.5s3 1.1 3 2.5-1.3 2-3 2.5-3 1.1-3 2.5 1.3 2.5 3 2.5 3-1.1 3-2.5"/>',
  team: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  sort: '<path d="M7 4v16M3 16l4 4 4-4M17 20V4M13 8l4-4 4 4"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M4 20h16"/>',
  upload: '<path d="M12 20V9M7 14l5-5 5 5M4 4h16"/>',
  star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
  starfill: '<path fill="currentColor" d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.3-4.3L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.3L20 16M20 20v-4h-4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  right: '<path d="m9 6 6 6-6 6"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  warn: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r=".8" fill="currentColor"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5"/>',
  logout: '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  swap: '<path d="M4 8h14l-4-4M20 16H6l4 4"/>',
};
export const icon = name =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;

/* ---------- 接口 ---------- */
export class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }
export async function api(path, opts = {}) {
  const init = {credentials: 'same-origin', ...opts, headers: {...(opts.body ? {'Content-Type': 'application/json'} : {}), ...(opts.headers || {})}};
  if (opts.body && typeof opts.body !== 'string') init.body = JSON.stringify(opts.body);
  const r = await fetch(path, init);
  if (r.status === 401 && !path.startsWith('/api/auth/')) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.hash);
    throw new ApiError(401, '请先登录');
  }
  const data = (r.headers.get('content-type') || '').includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    let msg = typeof data === 'object' ? data.detail : data;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join('；');
    throw new ApiError(r.status, msg || `请求失败（${r.status}）`);
  }
  return data;
}
/** 出错时提示并返回 null */
export async function call(path, opts) {
  try { return await api(path, opts); } catch (e) { if (e.status !== 401) toast(e.message, true); return null; }
}

/* ---------- 提示 ---------- */
export function toast(msg, err = false) {
  let box = $('#toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.append(box); }
  const el = document.createElement('div');
  el.className = 'toast' + (err ? ' err' : '');
  el.innerHTML = icon(err ? 'warn' : 'check') + `<span>${esc(msg)}</span>`;
  box.append(el);
  setTimeout(() => el.remove(), err ? 4000 : 2200);
}
export async function copyText(text, label = '已复制') {
  try { await navigator.clipboard.writeText(text); toast(label); } catch { toast('复制失败，请手动选择复制', true); }
}

/* ---------- 弹出菜单 / 面板 ---------- */
let openPop = null;
export function closePop() { openPop?.remove(); openPop = null; }
document.addEventListener('mousedown', e => { if (openPop && !openPop.contains(e.target) && !e.target.closest?.('[data-pop-anchor]')) closePop(); });
/** 在 anchor 下方打开一个浮层，content 为元素或 HTML */
export function popover(anchor, content, cls = '') {
  closePop();
  const el = document.createElement('div');
  el.className = 'pop ' + cls;
  if (typeof content === 'string') el.innerHTML = content; else el.append(content);
  document.body.append(el);
  const r = anchor.getBoundingClientRect();
  const left = Math.min(r.left, innerWidth - el.offsetWidth - 8);
  const top = r.bottom + 4 + el.offsetHeight > innerHeight ? Math.max(8, r.top - el.offsetHeight - 4) : r.bottom + 4;
  el.style.left = Math.max(8, left) + 'px';
  el.style.top = top + 'px';
  openPop = el;
  return el;
}
/** 下拉菜单：items = [{label(html), value, on}]，选中后回调 */
export function menu(anchor, items, onPick) {
  const el = popover(anchor, items.map((it, i) => it.sep ? '<div class="mi-sep"></div>'
    : `<div class="mi ${it.on ? 'on' : ''}" data-i="${i}">${it.label}</div>`).join(''));
  $$('.mi', el).forEach(m => m.onclick = () => { closePop(); onPick(items[+m.dataset.i]); });
}

/* ---------- 弹窗 ---------- */
export function closeModal() { $('#modal')?.remove(); $('#modal-mask')?.remove(); }
export function modal({title, body, actions = [], width}) {
  closeModal();
  const mask = document.createElement('div');
  mask.className = 'mask'; mask.id = 'modal-mask'; mask.onclick = closeModal;
  const m = document.createElement('div');
  m.className = 'modal'; m.id = 'modal';
  if (width) m.style.width = `min(${width}px, calc(100vw - 32px))`;
  m.innerHTML = `<div class="modal-h"><h2>${esc(title)}</h2><button class="btn text icon" data-x>${icon('x')}</button></div>
    <div class="modal-b"></div><div class="modal-f"></div>`;
  const b = $('.modal-b', m);
  if (typeof body === 'string') b.innerHTML = body; else if (body) b.append(body);
  const f = $('.modal-f', m);
  if (!actions.length) f.remove();
  for (const a of actions) {
    const btn = document.createElement('button');
    btn.className = 'btn' + (a.primary ? ' pri' : '') + (a.danger ? ' danger pri' : '');
    btn.textContent = a.label;
    btn.onclick = async () => {
      if (!a.onClick) return closeModal();
      btn.disabled = true;
      const keep = await a.onClick(m);
      btn.disabled = false;
      if (keep !== false) closeModal();
    };
    f.append(btn);
  }
  $('[data-x]', m).onclick = closeModal;
  document.body.append(mask, m);
  setTimeout(() => $('input:not([type=checkbox]),textarea', m)?.focus(), 30);
  return m;
}
export function confirmBox(title, text, {danger = false, ok = '确定'} = {}) {
  return new Promise(res => modal({title, body: `<p class="t2">${esc(text)}</p>`, actions: [
    {label: '取消', onClick: () => res(false)},
    {label: ok, primary: !danger, danger, onClick: () => res(true)},
  ]}));
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') { if ($('#modal')) closeModal(); else closePop(); } });

/* ---------- 主题 ---------- */
export function initTheme() {
  try { const t = localStorage.getItem('scout_theme'); if (t) document.documentElement.dataset.theme = t; } catch {}
}
export function toggleTheme() {
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('scout_theme', next); } catch {}
}

/* ---------- 路由（hash） ---------- */
export function parseHash() {
  const [path, query = ''] = location.hash.replace(/^#/, '').split('?');
  return {path: path || '/', params: Object.fromEntries(new URLSearchParams(query))};
}
export function hashFor(path, params) {
  const q = params ? new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null && v !== false)).toString() : '';
  return '#' + path + (q ? '?' + q : '');
}
export function go(path, params) { location.hash = hashFor(path, params); }
/** 只更新地址栏，不触发重新渲染（用于记录当前打开的记录等） */
export function replaceHash(path, params) { history.replaceState(null, '', hashFor(path, params)); }
export function startRouter(routes, render) {
  const run = () => {
    const {path, params} = parseHash();
    const key = Object.keys(routes).includes(path) ? path : Object.keys(routes)[0];
    render(key, routes[key], params);
  };
  addEventListener('hashchange', run);
  run();
}

/* ---------- 外壳 ---------- */
export function shell({product, nav, user, switchLink}) {
  document.body.innerHTML = `
  <div class="app">
    <aside class="side" id="side">
      <div class="side-head"><span class="logo">${icon('target')}</span><span>线索雷达</span>${product ? `<span class="side-tag">${esc(product)}</span>` : ''}</div>
      <nav class="nav" id="nav">${nav.map(n => n.group ? `<div class="nav-group">${esc(n.group)}</div>` :
        `<a href="#${n.path}" data-path="${n.path}">${icon(n.icon)}<span>${esc(n.label)}</span><span class="cnt" data-count="${n.path}"></span></a>`).join('')}</nav>
      <div class="side-foot">
        ${switchLink ? `<div class="nav" style="padding:0 0 4px"><a href="${switchLink.href}">${icon('swap')}<span>${esc(switchLink.label)}</span></a></div>` : ''}
        <div class="me" id="me" data-pop-anchor><span class="avatar">${esc(initial(user))}</span>
          <span class="grow ell">${esc(user.display_name || user.username)}</span>${icon('up')}</div>
      </div>
    </aside>
    <main class="main"><div id="page"></div></main>
  </div><div id="tip"></div>`;
  $('#me').onclick = e => userMenu(e.currentTarget, user);
  document.addEventListener('click', e => {
    if (e.target.closest('[data-menu]')) $('#side').classList.toggle('open');
    else if (e.target.closest('#nav a')) $('#side').classList.remove('open');
  });
}
export const initial = u => (u.display_name || u.username || '?').slice(0, 1).toUpperCase();
export function setActiveNav(path) { $$('#nav a[data-path]').forEach(a => a.classList.toggle('on', a.dataset.path === path)); }
export function setNavCount(path, n) { const el = $(`[data-count="${path}"]`); if (el) el.textContent = n ? n : ''; }

/** 页面标题栏 */
export function pageHead(title, right = '') {
  return `<div class="ph"><button class="btn text icon menu-btn" data-menu>${icon('menu')}</button><h1>${esc(title)}</h1><div class="grow"></div>${right}</div>`;
}
/** 设置页面模式：fill = 表格类页面（内部滚动），否则整页滚动 */
export function setPage(html, {fill = false} = {}) {
  const p = $('#page');
  p.className = fill ? 'fill' : '';
  p.innerHTML = html;
  p.scrollTop = 0;
  return p;
}

function userMenu(anchor, user) {
  const el = popover(anchor, `
    <div style="padding:8px 8px 10px;display:flex;gap:10px;align-items:center"><span class="avatar lg">${esc(initial(user))}</span>
      <div><div style="font-weight:500">${esc(user.display_name || user.username)}</div><div class="sm t3">${esc(user.username)} · ${user.role === 'admin' ? '管理员' : '成员'}</div></div></div>
    <div class="mi-sep"></div>
    <div class="mi" data-a="pw">${icon('key')}修改密码</div>
    <div class="mi" data-a="theme">${icon('moon')}切换深色 / 浅色</div>
    <div class="mi-sep"></div>
    <div class="mi" data-a="out">${icon('logout')}退出登录</div>`);
  el.style.width = '220px';
  el.style.top = Math.max(8, anchor.getBoundingClientRect().top - el.offsetHeight - 4) + 'px';
  $$('.mi', el).forEach(m => m.onclick = async () => {
    closePop();
    if (m.dataset.a === 'theme') return toggleTheme();
    if (m.dataset.a === 'out') { await call('/api/auth/logout', {method: 'POST'}); location.href = '/login'; return; }
    const f = document.createElement('form');
    f.className = 'col';
    f.style.gap = '12px';
    f.innerHTML = `<label class="field">当前密码<input class="input" type="password" name="old" required></label>
      <label class="field">新密码<input class="input" type="password" name="new" minlength="8" required><span class="hint">至少 8 位</span></label>`;
    modal({title: '修改密码', body: f, actions: [{label: '取消'}, {label: '保存', primary: true, onClick: async () => {
      if (!f.reportValidity()) return false;
      const r = await call('/api/auth/password', {method: 'POST', body: {old_password: f.old.value, new_password: f.new.value}});
      if (!r) return false;
      toast('密码已修改');
    }}]});
  });
}

/** 登录守卫：返回当前用户；requireAdmin 时普通用户跳转前台 */
export async function guard(requireAdmin = false) {
  initTheme();
  let me;
  try { me = await api('/api/auth/me'); } catch { location.href = '/login?next=' + encodeURIComponent(location.pathname + location.hash); return null; }
  if (requireAdmin && me.role !== 'admin') { location.href = '/app'; return null; }
  return me;
}

/* ---------- 多维表格 ----------
   columns: [{key, title, width, render(row) -> html, align:'r', sticky:true, cls}]
   opts: {rows, startIndex, selectable, selected:Set, currentId, onRow(row, tr), onSelect(ids)} */
export function renderTable(el, columns, opts) {
  const {rows, startIndex = 0, selectable = false, selected = new Set(), currentId = null} = opts;
  let left = 0;
  const lead = selectable ? {key: '__sel', width: 48, cls: 'idx'} : {key: '__idx', width: 48, cls: 'idx'};
  const cols = [lead, ...columns].map((c, i, arr) => {
    const sticky = i === 0 || c.sticky;
    const out = {...c, sticky, left};
    if (sticky) left += c.width;
    out.last = sticky && !(arr[i + 1]?.sticky);
    return out;
  });
  const total = cols.reduce((s, c) => s + c.width, 0);
  const stickyStyle = c => c.sticky ? `left:${c.left}px` : '';
  const cellCls = c => [c.cls, c.sticky ? 'sticky' : '', c.last ? 'sticky-last' : '', c.align === 'r' ? 'r' : ''].filter(Boolean).join(' ');
  const head = cols.map(c => `<th class="${cellCls(c)}" style="width:${c.width}px;${stickyStyle(c)}">${
    c.key === '__sel' ? '<input type="checkbox" data-all>' : esc(c.title || '')}</th>`).join('');
  const body = rows.map((r, i) => `<tr data-id="${r.id}" class="${selected.has(r.id) ? 'sel' : ''} ${r.id === currentId ? 'cur' : ''}">${cols.map(c => {
    let v;
    if (c.key === '__idx') v = startIndex + i + 1;
    else if (c.key === '__sel') v = `<input type="checkbox" data-sel="${r.id}" ${selected.has(r.id) ? 'checked' : ''}>`;
    else v = c.render ? c.render(r) : esc(r[c.key] ?? '');
    return `<td class="${cellCls(c)}" style="${stickyStyle(c)}">${v}</td>`;
  }).join('')}</tr>`).join('');
  el.innerHTML = `<table class="bt" style="width:${total}px"><colgroup>${cols.map(c => `<col style="width:${c.width}px">`).join('')}</colgroup>
    <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${rows.length ? '' : `<div class="empty">${esc(opts.empty || '没有记录')}</div>`}`;
  $$('tbody tr', el).forEach(tr => tr.onclick = e => {
    if (e.target.closest('input,a,[data-stop]')) return;
    opts.onRow?.(rows.find(r => String(r.id) === tr.dataset.id), tr);
  });
  if (selectable) {
    const sync = () => {
      $$('[data-sel]', el).forEach(c => { c.checked = selected.has(+c.dataset.sel); c.closest('tr').classList.toggle('sel', c.checked); });
      const all = $('[data-all]', el);
      all.checked = rows.length > 0 && rows.every(r => selected.has(r.id));
      opts.onSelect?.(selected);
    };
    $$('[data-sel]', el).forEach(c => c.onchange = () => { c.checked ? selected.add(+c.dataset.sel) : selected.delete(+c.dataset.sel); sync(); });
    $('[data-all]', el).onchange = e => { rows.forEach(r => e.target.checked ? selected.add(r.id) : selected.delete(r.id)); sync(); };
  }
}
export function markCurrent(el, id) {
  $$('tbody tr', el).forEach(tr => tr.classList.toggle('cur', tr.dataset.id === String(id)));
  $(`tbody tr[data-id="${id}"]`, el)?.scrollIntoView({block: 'nearest'});
}

/* ---------- 标签 ---------- */
export const tag = (text, color = '') => text ? `<span class="tag ${color}" title="${esc(text)}">${esc(text)}</span>` : '';
const GRADE_COLOR = {A: 'green', B: 'blue', C: 'orange', D: ''};
export const gradeTag = g => g ? `<span class="tag grade ${GRADE_COLOR[g]}">${g}</span>` : '<span class="t3">-</span>';
const CN_COLOR = {'在美华人': 'blue', '国内跨境卖家': 'purple', '港澳台': 'teal', '非华人': '', '无法判断': ''};
export const cnTag = t => t ? tag(t, CN_COLOR[t] ?? '') : '';
export const OUTREACH_COLOR = {'未联系': '', '已联系': 'blue', '有回复': 'teal', '洽谈中': 'orange', '已合作': 'green', '不合适': 'red'};
export const outreachTag = s => tag(s || '未联系', OUTREACH_COLOR[s] ?? '');
export const STATUS_LABEL = {
  new: '待采集', crawling: '采集中', crawled: '待打分', scoring: '打分中', scored: '已打分', alias: '跳转别名',
  not_store: '非店铺', not_target: '非目标国家', dead: '已关闭', blocked: '禁止访问', failed: '采集失败', score_failed: '打分失败',
};
const STATUS_COLOR = {scored: 'green', new: 'blue', crawling: 'blue', crawled: 'orange', scoring: 'orange', failed: 'red', score_failed: 'red'};
export const statusTag = s => tag(STATUS_LABEL[s] || s, STATUS_COLOR[s] || '');
export const tagList = (arr, max = 3) => {
  const a = (Array.isArray(arr) ? arr : String(arr || '').split('、')).filter(Boolean);
  return a.slice(0, max).map(x => tag(x)).join('') + (a.length > max ? `<span class="sm t3" style="margin-left:4px">+${a.length - max}</span>` : '');
};
export const emptyState = text => `<div class="empty">${esc(text)}</div>`;

/* ---------- 图表 ---------- */
export function showTip(e, html) {
  const t = $('#tip'); if (!t) return;
  t.innerHTML = html; t.classList.add('on');
  t.style.left = Math.min(e.clientX + 12, innerWidth - t.offsetWidth - 8) + 'px';
  t.style.top = Math.max(8, e.clientY - t.offsetHeight - 8) + 'px';
}
export function hideTip() { $('#tip')?.classList.remove('on'); }

/** 横向条形图（单一系列，数值直接标注） */
export function barList(el, items, {onClick, empty = '暂无数据'} = {}) {
  if (!items?.length || !items.some(i => i.value)) { el.innerHTML = `<div class="empty" style="padding:32px 0">${empty}</div>`; return; }
  const max = Math.max(...items.map(i => i.value), 1), total = items.reduce((s, i) => s + i.value, 0);
  el.innerHTML = `<div class="bars">${items.map((it, i) => `<div class="bar-row ${onClick && !it.other ? 'click' : ''} ${it.other ? 'other' : ''}" data-i="${i}">
    <div class="lbl" title="${esc(it.label)}">${esc(it.label)}</div>
    <div><div class="bar-fill" style="width:${(100 * it.value / max).toFixed(1)}%"></div></div>
    <div class="val">${fmt(it.value)}</div></div>`).join('')}</div>`;
  $$('.bar-row', el).forEach(row => {
    const it = items[+row.dataset.i];
    row.onmousemove = e => showTip(e, `${esc(it.label)}：${fmt(it.value)}（${pct(it.value, total)}）`);
    row.onmouseleave = hideTip;
    if (onClick && !it.other) row.onclick = () => { hideTip(); onClick(it); };
  });
}
function niceMax(v) {
  if (v <= 4) return 4;
  if (v <= 20) return Math.ceil(v / 2) * 2;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return v;
}
/** 按天柱状图（单一系列） */
export function columnChart(el, series, {height = 180, unit = ''} = {}) {
  const cs = getComputedStyle(el);
  const inner = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const w = Math.max(inner || 300, 240), h = height, padL = 36, padB = 22, padT = 8;
  const max = niceMax(Math.max(...series.map(s => s.value), 0));
  const n = series.length, gap = 3, bw = Math.max(2, (w - padL) / n - gap);
  const y = v => padT + (h - padT - padB) * (1 - v / max);
  const every = Math.ceil(n / 7);
  let svg = `<svg class="col-chart" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">`;
  for (const t of [0, max / 2, max]) svg += `<line class="gridline" x1="${padL}" x2="${w}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${padL - 8}" y="${y(t) + 4}" text-anchor="end">${compact(t)}</text>`;
  series.forEach((s, i) => {
    const x = padL + i * (bw + gap), top = y(s.value), bh = h - padB - top, r = Math.min(3, bh, bw / 2);
    svg += `<g class="c" data-i="${i}"><rect class="hit" x="${x - gap / 2}" y="${padT}" width="${bw + gap}" height="${h - padT - padB}"/>`;
    if (s.value) svg += `<path d="M${x},${h - padB}V${top + r}q0,-${r} ${r},-${r}h${bw - 2 * r}q${r},0 ${r},${r}V${h - padB}z" style="fill:var(--series-1)"/>`;
    svg += '</g>';
    if (i % every === 0 || i === n - 1) svg += `<text class="axis" x="${x + bw / 2}" y="${h - 5}" text-anchor="middle">${s.day.slice(5).replace('-', '/')}</text>`;
  });
  svg += `<line class="baseline" x1="${padL}" x2="${w}" y1="${h - padB}" y2="${h - padB}"/></svg>`;
  el.innerHTML = svg;
  $$('g.c', el).forEach(g => {
    const s = series[+g.dataset.i];
    g.onmousemove = e => showTip(e, `${s.day}　${fmt(s.value)}${unit}`);
    g.onmouseleave = hideTip;
  });
}
/** 漏斗：数量 + 相对上一阶段的转化率 */
export function funnel(el, steps) {
  if (!steps?.length || !steps[0].value) { el.innerHTML = '<div class="empty" style="padding:32px 0">还没有已打分的线索</div>'; return; }
  const max = steps[0].value;
  el.innerHTML = steps.map((s, i) => `<div class="funnel-row"><span class="t2">${esc(s.label)}</span>
    <div><div class="bar-fill" style="width:${Math.max(0.8, 100 * s.value / max).toFixed(1)}%"></div></div>
    <span class="num">${fmt(s.value)}${i ? `<span class="sm t3"> · ${pct(s.value, steps[i - 1].value)}</span>` : ''}</span></div>`).join('');
}
