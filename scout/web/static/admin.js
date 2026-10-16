/* 管理后台：管理员使用 */
import {
  $, $$, esc, fmt, pct, ago, compact, icon, api, call, toast, guard, shell, setActiveNav, startRouter, go,
  pageHead, setPage, closePop, renderTable, markCurrent, barList, columnChart, modal, confirmBox,
  tag, statusTag, STATUS_LABEL, emptyState,
} from '/static/ui.js';
import {setMeta, openRecord, leadColumns, bindStatusCells} from '/static/lead.js';

const me = await guard(true);
if (!me) throw new Error('跳转登录');
setMeta(await api('/api/meta'));

shell({
  user: me,
  product: '后台',
  nav: [
    {group: '运行'},
    {path: '/monitor', label: '采集监控', icon: 'pulse'},
    {path: '/stores', label: '站点管理', icon: 'db'},
    {path: '/sources', label: '发现渠道', icon: 'radio'},
    {group: '管理'},
    {path: '/users', label: '用户', icon: 'users'},
    {path: '/settings', label: '打分配置', icon: 'sliders'},
    {path: '/usage', label: 'AI 用量', icon: 'coin'},
    {path: '/team', label: '团队跟进', icon: 'team'},
  ],
  switchLink: {href: '/app', label: '前台工作台'},
});

let timer = null;
const stat = (k, v, s = '', to = '') => `<div class="stat ${to ? 'click' : ''}" ${to ? `data-to="${esc(to)}"` : ''}><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`;
const bindStats = root => $$('[data-to]', root).forEach(el => el.onclick = () => { location.hash = el.dataset.to; });
const rangeSelect = days => `<select class="select" id="days">${[7, 30, 90].map(d => `<option value="${d}" ${d === days ? 'selected' : ''}>近 ${d} 天</option>`).join('')}</select>`;

/* ================= 采集监控 ================= */
async function monitor() {
  setPage(`${pageHead('采集监控', `<span class="sm t3">每 15 秒自动刷新</span><button class="btn" id="refresh">${icon('refresh')}刷新</button>`)}
    <div class="body"><div id="worker"></div><div class="stats mt" id="stats"></div>
      <div class="grid g2 mt">
        <div class="blk"><div class="blk-h"><h3>站点状态</h3><a class="sm" href="#/stores">站点管理</a></div><div class="blk-b" id="status"></div></div>
        <div class="blk"><div class="blk-h"><h3>发现渠道</h3><a class="sm" href="#/sources">渠道管理</a></div><div class="blk-b flush tb-scroll" id="srcs"></div></div>
      </div>
      <div class="grid g2 mt">
        <div class="blk"><div class="blk-h"><h3>最近处理</h3></div><div class="blk-b flush tb-scroll" id="recent"></div></div>
        <div class="blk"><div class="blk-h"><h3>最近错误</h3><span class="sm t3">失败后按 1、4、9 小时重试</span></div><div class="blk-b flush tb-scroll" id="errors"></div></div>
      </div></div>`);
  $('#refresh').onclick = load;
  async function load() {
    const m = await call('/api/admin/monitor');
    if (!m) return;
    const running = m.workers.filter(w => w.running), w = running[0] || m.workers[0];
    $('#worker').innerHTML = `<div class="blk"><div class="blk-b row wrap" style="gap:16px;padding-top:14px;padding-bottom:14px">
      <span class="dot ${running.length ? 'ok' : 'bad'}" style="width:8px;height:8px"></span>
      <div class="grow" style="flex-basis:260px"><b>${running.length ? `自动采集运行中${running.length > 1 ? `（${running.length} 个进程）` : ''}` : '自动采集未运行'}</b>
        <div class="sm t3">${w ? `${esc(w.name)} · 启动于 ${ago(w.started_at)} · 最近心跳 ${ago(w.beat_at)}` : '还没有采集进程启动过'}</div></div>
      ${w ? `<div class="row sm t2" style="gap:16px">
        <span>本次采集 <b class="num" style="color:var(--text)">${fmt(w.info.crawled)}</b></span>
        <span>打分 <b class="num" style="color:var(--text)">${fmt(w.info.scored)}</b></span>
        <span>失败 <b class="num" style="color:var(--text)">${fmt((w.info.crawl_failed || 0) + (w.info.score_failed || 0))}</b></span>
        <span>AI 打分 ${m.llm_enabled ? tag('已启用', 'green') : tag('未配置 Key', 'red')}</span></div>` : ''}
      </div>${running.length ? '' : `<div class="blk-b" style="padding-top:0"><div class="notice warn">在服务器上运行 <code>python -m scout start</code>；Docker 部署时用 <code>docker compose ps</code> 确认 worker 容器在运行。</div></div>`}</div>`;
    const q = m.queue, t = m.throughput;
    $('#stats').innerHTML = [
      stat('待采集', fmt(q.ready), `等待重试 ${fmt(q.waiting_retry)}`, '#/stores?view=new'),
      stat('待打分', fmt(q.to_score), `打分中 ${fmt(q.scoring)}`, '#/stores?view=crawled'),
      stat('近 1 小时采集', fmt(t.crawled_1h), `打分 ${fmt(t.scored_1h)} · 新发现 ${fmt(t.discovered_1h)}`),
      stat('近 24 小时采集', fmt(t.crawled_24h), `打分 ${fmt(t.scored_24h)} · 新发现 ${fmt(t.discovered_24h)}`),
      stat('今日 AI 调用', fmt(m.llm_today.calls), `${compact(m.llm_today.prompt_tokens + m.llm_today.completion_tokens)} tokens · 失败 ${m.llm_today.errors}`, '#/usage'),
    ].join('');
    bindStats($('#stats'));
    barList($('#status'), Object.entries(m.status).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({label: STATUS_LABEL[k] || k, value: v, key: k})),
      {onClick: it => go('/stores', {status: it.key})});
    $('#srcs').innerHTML = `<table class="tb"><thead><tr><th>渠道</th><th>状态</th><th>上次运行</th></tr></thead><tbody>${m.sources.filter(s => s.scheduled).map(s => `
      <tr><td>${esc(s.label)}<div class="sm t3" style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.last_result || '')}</div></td>
      <td><span class="row" style="gap:6px"><span class="dot ${s.enabled ? 'ok' : ''}"></span>${s.enabled ? '启用' : '关闭'}</span></td>
      <td class="t2">${s.last_run ? ago(s.last_run) : '从未'}</td></tr>`).join('')}</tbody></table>`;
    $('#recent').innerHTML = m.recent.length ? `<table class="tb"><tbody>${m.recent.map(r => `<tr class="click" data-id="${r.id}">
      <td style="font-weight:500">${esc(r.domain)}</td><td>${statusTag(r.status)}</td><td class="num">${r.grade ? `${r.grade} · ${r.total_score}` : ''}</td><td class="r t3 num">${ago(r.at)}</td></tr>`).join('')}</tbody></table>` : emptyState('暂无记录');
    $('#errors').innerHTML = m.errors.length ? `<table class="tb"><tbody>${m.errors.map(r => `<tr class="click" data-id="${r.id}">
      <td style="font-weight:500">${esc(r.domain)}<div class="sm t3">${STATUS_LABEL[r.status] || r.status} · 失败 ${r.fail_count} 次</div></td>
      <td class="sm" style="color:var(--t-red);max-width:260px">${esc(r.error)}</td><td class="r t3 num">${ago(r.at)}</td></tr>`).join('')}</tbody></table>` : emptyState('没有错误');
    $$('#recent tr[data-id], #errors tr[data-id]').forEach(tr => tr.onclick = () => openRecord(+tr.dataset.id));
  }
  await load();
  timer = setInterval(load, 15000);
}

/* ================= 站点管理 ================= */
const STORE_VIEWS = [
  ['all', '全部', 'all'], ['new', '待采集', 'new'], ['crawled', '待打分', 'crawled'], ['scored', '已打分', 'scored'],
  ['failed', '失败', 'failed,score_failed'], ['excluded', '已排除', 'not_store,not_target,dead,blocked,alias'],
];
async function stores(params) {
  const view = params.status ? 'custom' : (params.view || 'all');
  const status = params.status || STORE_VIEWS.find(v => v[0] === view)?.[2] || 'all';
  const q = params.q || '', pageNo = +(params.page || 1), PAGE = 50;
  const selected = new Set();
  setPage(`${pageHead('站点管理', `<button class="btn pri" id="import">${icon('plus')}导入站点</button>`)}
    <div class="views">${STORE_VIEWS.map(([v, l]) => `<button data-v="${v}" class="${v === view ? 'on' : ''}">${l}</button>`).join('')}
      ${view === 'custom' ? `<button class="on">${esc(STATUS_LABEL[status] || status)}</button>` : ''}</div>
    <div class="toolbar">
      <div class="search">${icon('search')}<input class="input" id="q" placeholder="搜索域名、店名" value="${esc(q)}"></div>
      <span class="grow"></span>
      <div class="row hidden" id="bulk"><span class="sm t2" id="sel-n"></span>
        <button class="btn sm" data-bulk="recrawl">${icon('refresh')}重新采集</button>
        <button class="btn sm" data-bulk="rescore">重新打分</button>
        <button class="btn sm danger" data-bulk="delete">${icon('trash')}删除</button></div>
    </div>
    <div class="split"><div class="bt-col"><div class="bt-wrap" id="tbl"><div class="empty"><span class="spin"></span></div></div>
      <div class="tbl-foot"><span id="total"></span><span class="grow"></span>
        <button class="btn text sm" id="prev">上一页</button><span id="pno" class="num"></span><button class="btn text sm" id="next">下一页</button></div></div>
      <aside class="rec hidden" id="rec"></aside></div>`, {fill: true});
  $$('.views button[data-v]').forEach(b => b.onclick = () => go('/stores', {view: b.dataset.v, q}));
  $('#q').onkeydown = e => { if (e.key === 'Enter') go('/stores', {view: params.view, status: params.status, q: e.target.value.trim()}); };
  $('#import').onclick = importModal;
  const d = await call('/api/stores?' + new URLSearchParams({status, q, sort: 'updated', page: pageNo, size: PAGE}));
  if (!d) return;
  const pages = Math.max(1, Math.ceil(d.total / PAGE));
  $('#total').textContent = `共 ${fmt(d.total)} 个站点`;
  $('#pno').textContent = `${pageNo} / ${pages}`;
  $('#prev').disabled = pageNo <= 1; $('#next').disabled = pageNo >= pages;
  $('#prev').onclick = () => go('/stores', {view: params.view, status: params.status, q, page: pageNo - 1});
  $('#next').onclick = () => go('/stores', {view: params.view, status: params.status, q, page: pageNo + 1});
  const tbl = $('#tbl'), rec = $('#rec');
  const syncBulk = () => { $('#bulk').classList.toggle('hidden', !selected.size); $('#sel-n').textContent = `已选 ${selected.size} 个`; };
  renderTable(tbl, leadColumns({showStatus: true}), {
    rows: d.items, startIndex: (pageNo - 1) * PAGE, selectable: true, selected, onSelect: syncBulk, empty: '没有站点',
    onRow: r => { markCurrent(tbl, r.id); openRecord(r.id, {container: rec, onChange: () => stores(params), onClose: () => markCurrent(tbl, null)}); },
  });
  bindStatusCells(tbl, d.items, () => stores(params));
  $$('[data-bulk]').forEach(b => b.onclick = async () => {
    const act = b.dataset.bulk;
    const text = {recrawl: '重新采集', rescore: '重新打分（会产生 AI 调用费用）', delete: '永久删除（含跟进记录）'}[act];
    if (!await confirmBox('批量操作', `对选中的 ${selected.size} 个站点${text}？`, {danger: act === 'delete'})) return;
    const r = await call('/api/admin/stores/bulk', {method: 'POST', body: {ids: [...selected], action: act}});
    if (r) { toast(`已处理 ${r.affected} 个站点`); stores(params); }
  });
}

function importModal() {
  const body = document.createElement('div');
  body.className = 'col';
  body.style.gap = '12px';
  body.innerHTML = `<label class="field">网址或域名<textarea class="input" rows="8" id="imp-text" placeholder="每行一个，也可以直接粘贴包含网址的文本"></textarea>
      <span class="hint" id="imp-n">识别到 0 个域名</span></label>
    <div class="row"><label class="btn sm">${icon('upload')}从 CSV / TXT 读取<input type="file" accept=".csv,.txt" id="imp-file" hidden></label></div>
    <label class="field">优先级<select class="select" id="imp-pri"><option value="10">高（优先采集）</option><option value="5">普通</option><option value="0">低</option></select></label>`;
  const extract = () => [...new Set(($('#imp-text', body).value.match(/(?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,}/gi) || []).map(s => s.toLowerCase()))];
  const count = () => { $('#imp-n', body).textContent = `识别到 ${extract().length} 个域名`; };
  modal({title: '导入站点', body, width: 520, actions: [{label: '取消'}, {label: '加入队列', primary: true, onClick: async () => {
    const domains = extract();
    if (!domains.length) { toast('没有识别到域名', true); return false; }
    const r = await call('/api/admin/stores/import', {method: 'POST', body: {domains, priority: +$('#imp-pri', body).value}});
    if (!r) return false;
    toast(`新增 ${r.added} 个；已存在或在黑名单中的 ${r.received - r.added} 个已跳过`);
    go('/stores', {view: 'new'});
  }}]});
  $('#imp-text', body).oninput = count;
  $('#imp-file', body).onchange = async e => { const f = e.target.files[0]; if (f) { $('#imp-text', body).value = await f.text(); count(); } };
}

/* ================= 发现渠道 ================= */
async function sources() {
  setPage(`${pageHead('发现渠道')}<div class="body">
    <p class="t2" style="margin-bottom:16px">开关和“立即运行”对采集进程实时生效。命中率 = A/B 级线索 ÷ 已处理站点，用来判断哪个渠道值得多投入。</p>
    <div class="blk"><div class="blk-b flush tb-scroll" id="list" style="padding-top:0"></div></div></div>`);
  const list = await call('/api/admin/sources');
  if (!list) return;
  const rows = [...list.filter(s => s.scheduled), ...list.filter(s => !s.scheduled).sort((a, b) => b.effect.total - a.effect.total)];
  $('#list').innerHTML = `<table class="tb"><thead><tr><th>渠道</th><th>启用</th><th>上次运行</th><th class="r">发现</th><th class="r">已处理</th><th class="r">A/B</th><th class="r">华人卖家</th><th class="r">命中率</th><th></th></tr></thead><tbody>
    ${rows.map(s => { const e = s.effect || {}; return `<tr>
      <td style="min-width:240px"><div style="font-weight:500">${esc(s.label)}</div><div class="sm t3">${esc(s.desc)}</div></td>
      <td>${s.scheduled ? `<label class="switch"><input type="checkbox" data-toggle="${s.name}" ${s.enabled ? 'checked' : ''}><span></span></label>` : '<span class="sm t3">随用随提交</span>'}</td>
      <td style="min-width:180px">${s.scheduled ? `<div class="t2">${s.last_run ? ago(s.last_run) : '从未'}${s.interval ? `<span class="t3"> · 每 ${s.interval} 分钟</span>` : ''}</div><div class="sm t3" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(s.last_result || '')}">${esc(s.last_result || '')}</div>` : ''}</td>
      <td class="r num">${fmt(e.total || 0)}</td><td class="r num">${fmt(e.processed || 0)}</td><td class="r num">${fmt(e.ab || 0)}</td>
      <td class="r num">${fmt(e.chinese || 0)}</td><td class="r num">${e.hit_rate != null ? e.hit_rate + '%' : '-'}</td>
      <td class="r">${s.scheduled ? `<button class="btn sm" data-run="${s.name}">${icon('play')}立即运行</button>` : ''}</td></tr>`; }).join('')}</tbody></table>`;
  $$('[data-toggle]').forEach(i => i.onchange = async () => {
    if (i.dataset.toggle === 'search' && i.checked && !await confirmBox('启用搜索引擎渠道', '自动抓取搜索结果页违反 Google、Bing、DuckDuckGo 的使用条款，可能导致服务器 IP 被封。程序会低频运行、遇到验证码立即停止。确定启用吗？', {ok: '启用'})) { i.checked = false; return; }
    if (await call(`/api/admin/sources/${i.dataset.toggle}/toggle?enabled=${i.checked}`, {method: 'POST'})) toast(i.checked ? '已启用' : '已关闭');
  });
  $$('[data-run]').forEach(b => b.onclick = async () => { const r = await call(`/api/admin/sources/${b.dataset.run}/run`, {method: 'POST'}); if (r) toast(r.message); });
}

/* ================= 用户 ================= */
async function users() {
  setPage(`${pageHead('用户', `<button class="btn pri" id="add">${icon('plus')}添加用户</button>`)}
    <div class="body"><p class="t2" style="margin-bottom:16px">成员可以使用前台工作台和浏览器插件；管理员还可以进入后台。</p>
    <div class="blk"><div class="blk-b flush tb-scroll" id="list" style="padding-top:0"></div></div></div>`);
  $('#add').onclick = () => userForm();
  const list = await call('/api/admin/users');
  if (!list) return;
  $('#list').innerHTML = `<table class="tb"><thead><tr><th>用户</th><th>角色</th><th>状态</th><th class="r">负责线索</th><th>插件令牌</th><th>最近登录</th><th></th></tr></thead><tbody>
    ${list.map(u => `<tr><td><div class="row"><span class="avatar">${esc((u.display_name || u.username).slice(0, 1).toUpperCase())}</span>
      <div><div>${esc(u.display_name || u.username)}</div><div class="sm t3">${esc(u.username)}</div></div></div></td>
      <td>${u.role === 'admin' ? tag('管理员', 'blue') : tag('成员')}</td>
      <td><span class="row" style="gap:6px"><span class="dot ${u.active ? 'ok' : 'bad'}"></span>${u.active ? '正常' : '已停用'}</span></td>
      <td class="r num">${fmt(u.owned)}</td><td class="t2">${u.has_token ? '已生成' : '-'}</td>
      <td class="t2">${u.last_login ? ago(u.last_login) : '从未登录'}</td>
      <td class="r"><button class="btn text sm" data-edit="${u.id}">编辑</button></td></tr>`).join('')}</tbody></table>`;
  $$('[data-edit]').forEach(b => b.onclick = () => userForm(list.find(u => u.id === +b.dataset.edit)));
}
function userForm(u) {
  const f = document.createElement('form');
  f.className = 'col';
  f.style.gap = '12px';
  f.innerHTML = `${u ? '' : `<label class="field">用户名<input class="input" name="username" required><span class="hint">登录用，字母或数字，创建后不能修改</span></label>`}
    <label class="field">显示名称<input class="input" name="display_name" value="${esc(u?.display_name || '')}" placeholder="例如：李四"></label>
    <label class="field">角色<select class="select" name="role"><option value="user" ${u?.role !== 'admin' ? 'selected' : ''}>成员（运营 / 招商）</option><option value="admin" ${u?.role === 'admin' ? 'selected' : ''}>管理员</option></select></label>
    <label class="field">${u ? '重置密码' : '初始密码'}<input class="input" name="password" autocomplete="off" ${u ? '' : 'required minlength="8"'}>
      <span class="hint">${u ? '留空则不修改；重置后该用户需要重新登录' : '至少 8 位'}</span></label>
    ${u ? `<label class="check"><span class="switch"><input type="checkbox" name="active" ${u.active ? 'checked' : ''}><span></span></span>账号可用<span class="sm t3">停用后立即退出登录，插件令牌失效</span></label>` : ''}`;
  modal({title: u ? '编辑用户' : '添加用户', body: f, actions: [{label: '取消'}, {label: '保存', primary: true, onClick: async () => {
    if (!f.reportValidity()) return false;
    const body = {display_name: f.display_name.value, role: f.role.value};
    if (f.password.value) body.password = f.password.value;
    const r = u ? await call('/api/admin/users/' + u.id, {method: 'PATCH', body: {...body, active: f.active.checked}})
      : await call('/api/admin/users', {method: 'POST', body: {...body, username: f.username.value}});
    if (!r) return false;
    toast('已保存'); users();
  }}]});
}

/* ================= 打分配置 ================= */
async function settings() {
  const s = await call('/api/admin/settings');
  if (!s) return;
  const c = s.company.value || {}, sc = s.scoring.value || {};
  const src = (x, key) => x.source === 'db' ? `<span class="sm t3">${esc(x.updated_by || '')} 修改于 ${ago(x.updated_at)} · <button type="button" class="btn link sm" data-reset="${key}">恢复默认</button></span>` : '<span class="sm t3">使用配置文件默认值</span>';
  const lines = a => (a || []).join('\n');
  setPage(`${pageHead('打分配置', `<button class="btn" id="preview">查看提示词</button>`)}
    <div class="body narrow">
      <p class="t2">AI 按这里的公司画像和打分规则评估每个站点。保存后约 30 秒对新的打分生效；已打分的线索可在站点管理中批量重新打分。</p>
      <form id="company" class="form-sec">
        <div class="row"><h3 class="grow">公司画像</h3>${src(s.company, 'company')}</div>
        <div class="fr"><label>公司名称</label><input class="input" name="name" value="${esc(c.name || '')}"></div>
        <div class="fr"><label>公司介绍</label><div><textarea class="input" name="description" rows="3" style="width:100%">${esc(c.description || '')}</textarea><div class="hint">我们是谁、能提供什么服务</div></div></div>
        <div class="fr"><label>美国仓库</label><div><div class="col" id="wh"></div><button type="button" class="btn sm" id="wh-add" style="margin-top:8px">${icon('plus')}添加仓库</button></div></div>
        <div class="fr"><label>可上架品类</label><div><textarea class="input" name="product_categories" rows="5" style="width:100%">${esc(lines(c.product_categories))}</textarea><div class="hint">每行一个，越具体越好，AI 据此判断选品契合度</div></div></div>
        <div class="fr"><label>合作类型</label><div><textarea class="input" name="partnership_types" rows="2" style="width:100%">${esc(lines(c.partnership_types))}</textarea><div class="hint">每行一个</div></div></div>
        <div class="fr"><label>合作偏好</label><div><textarea class="input" name="preferences" rows="4" style="width:100%">${esc(lines(c.preferences))}</textarea><div class="hint">每行一条，会写进提示词</div></div></div>
        <div class="fr"><span></span><div><button class="btn pri">保存公司画像</button></div></div>
      </form>
      <form id="scoring" class="form-sec">
        <div class="row"><h3 class="grow">打分维度</h3>${src(s.scoring, 'scoring')}</div>
        <p class="desc">每个维度由 AI 打 0–100 分，按权重加权得到总分，权重会自动换算成占比。</p>
        <div class="tb-scroll"><table class="tb" id="dims"><thead><tr><th style="width:140px">维度</th><th>评分说明</th><th style="width:170px">权重</th><th class="r" style="width:60px">占比</th></tr></thead><tbody></tbody></table></div>
        <div class="fr" style="margin-top:12px"><label>等级线</label><div class="row wrap">${['A', 'B', 'C'].map(g => `<span class="row" style="gap:6px">${tag(g, {A: 'green', B: 'blue', C: 'orange'}[g])} ≥ <input class="input num" type="number" min="0" max="100" name="grade_${g}" value="${(sc.grades || {})[g] ?? ''}" style="width:72px"></span>`).join('<span class="t3" style="margin:0 4px">·</span>')}<span class="sm t3">其余为 D</span></div></div>
        <div class="fr"><span></span><div><button class="btn pri">保存打分配置</button></div></div>
      </form>
      <div class="form-sec">
        <h3>运行参数</h3><p class="desc">在服务器 <code>config/settings.yaml</code> 或 <code>.env</code> 中修改，重启后生效。</p>
        <dl class="kv" style="grid-template-columns:140px minmax(0,1fr)">${Object.entries({llm_model: '初筛模型', review_model: '复核模型', review_threshold: '复核分数线', target_countries: '目标国家', concurrency: '采集并发', recrawl_days: '重新采集周期（天）'})
          .map(([k, l]) => `<dt>${l}</dt><dd class="mono">${esc(Array.isArray(s.runtime[k]) ? s.runtime[k].join(', ') : s.runtime[k] ?? '-')}</dd>`).join('')}</dl>
      </div>
    </div>`);

  const wh = $('#wh');
  const addWh = (w = {}) => {
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<input class="input" placeholder="位置，如 Ontario, CA" value="${esc(w.location || '')}" data-loc style="width:200px">
      <input class="input grow" placeholder="服务，用逗号分隔" value="${esc((w.services || []).join(', '))}" data-svc>
      <button type="button" class="btn text sm icon" title="删除">${icon('x')}</button>`;
    $('button', row).onclick = () => row.remove();
    wh.append(row);
  };
  (c.warehouses || []).forEach(addWh);
  $('#wh-add').onclick = () => addWh();
  const split = v => v.split('\n').map(x => x.trim()).filter(Boolean);
  $('#company').onsubmit = async e => {
    e.preventDefault();
    const f = e.target;
    const value = {...c, name: f.name.value.trim(), description: f.description.value.trim(),
      warehouses: $$('#wh .row').map(r => ({location: $('[data-loc]', r).value.trim(), services: $('[data-svc]', r).value.split(/[,，、]/).map(x => x.trim()).filter(Boolean)})).filter(w => w.location),
      product_categories: split(f.product_categories.value), partnership_types: split(f.partnership_types.value), preferences: split(f.preferences.value)};
    if (await call('/api/admin/settings/company', {method: 'PUT', body: {value}})) { toast('公司画像已保存'); settings(); }
  };

  const dims = Object.entries(sc.dimensions || {});
  $('#dims tbody').innerHTML = dims.map(([k, d]) => `<tr data-dim="${k}">
    <td><input class="input" data-label value="${esc(d.label || k)}" style="width:120px"></td>
    <td><textarea class="input" data-desc rows="2" style="width:100%;min-width:200px;font-size:13px">${esc(d.desc || '')}</textarea></td>
    <td><div class="row"><input type="range" min="0" max="1" step="0.05" value="${d.weight}" data-wr style="width:84px"><input class="input num" type="number" min="0" step="0.05" value="${d.weight}" data-w style="width:66px"></div></td>
    <td class="r num t2" data-share></td></tr>`).join('');
  const share = () => {
    const ws = $$('[data-w]').map(i => +i.value || 0), sum = ws.reduce((a, b) => a + b, 0) || 1;
    $$('[data-share]').forEach((el, i) => { el.textContent = `${(100 * ws[i] / sum).toFixed(0)}%`; });
  };
  $$('[data-dim]').forEach(row => {
    const r = $('[data-wr]', row), n = $('[data-w]', row);
    r.oninput = () => { n.value = r.value; share(); };
    n.oninput = () => { r.value = n.value; share(); };
  });
  share();
  $('#scoring').onsubmit = async e => {
    e.preventDefault();
    const f = e.target;
    const value = {...sc, dimensions: Object.fromEntries($$('[data-dim]').map(row => [row.dataset.dim,
      {label: $('[data-label]', row).value.trim(), weight: +$('[data-w]', row).value, desc: $('[data-desc]', row).value.trim()}])),
      grades: {A: +f.grade_A.value, B: +f.grade_B.value, C: +f.grade_C.value, D: 0}};
    if (await call('/api/admin/settings/scoring', {method: 'PUT', body: {value}})) { toast('打分配置已保存'); settings(); }
  };
  $$('[data-reset]').forEach(b => b.onclick = async () => {
    if (!await confirmBox('恢复默认', '恢复为服务器配置文件中的默认值，后台的修改会被清除。', {ok: '恢复'})) return;
    if (await call('/api/admin/settings/' + b.dataset.reset, {method: 'DELETE'})) { toast('已恢复默认'); settings(); }
  });
  $('#preview').onclick = async () => {
    const p = await call('/api/admin/prompt-preview');
    if (p) modal({title: '当前系统提示词', width: 760, body: `<pre class="mono quote-box" style="white-space:pre-wrap;margin:0">${esc(p.system_prompt)}</pre>`});
  };
}

/* ================= AI 用量 ================= */
async function usage(params) {
  const days = +(params.days || 30);
  setPage(`${pageHead('AI 用量', rangeSelect(days))}
    <div class="body"><div class="stats" id="stats"></div>
      <div class="blk mt"><div class="blk-h"><h3>每天消耗的 tokens</h3><span class="sm t3">输入 + 输出，费用以 DeepSeek 账单为准</span></div><div class="blk-b" id="chart"></div></div>
      <div class="blk mt"><div class="blk-h"><h3>明细</h3></div><div class="blk-b flush tb-scroll" id="rows"></div></div></div>`);
  $('#days').onchange = e => go('/usage', {days: e.target.value});
  const u = await call('/api/admin/usage?days=' + days);
  if (!u) return;
  const t = u.totals;
  $('#stats').innerHTML = [
    stat('调用次数', fmt(t.calls), `失败 ${fmt(t.errors)} 次`),
    stat('输入 tokens', compact(t.prompt_tokens), `缓存命中 ${pct(t.cache_hit_tokens, t.prompt_tokens)}`),
    stat('输出 tokens', compact(t.completion_tokens), t.calls ? `平均每次 ${fmt(Math.round(t.completion_tokens / t.calls))}` : '-'),
    stat('平均每次调用', t.calls ? compact(Math.round((t.prompt_tokens + t.completion_tokens) / t.calls)) : '-', 'tokens'),
  ].join('');
  columnChart($('#chart'), u.trend, {unit: ' tokens', height: 200});
  $('#rows').innerHTML = u.rows.length ? `<table class="tb"><thead><tr><th>日期</th><th>模型</th><th class="r">调用</th><th class="r">输入</th><th class="r">缓存命中</th><th class="r">输出</th><th class="r">失败</th></tr></thead><tbody>
    ${u.rows.slice().reverse().map(r => `<tr><td class="num">${r.day}</td><td class="mono">${esc(r.model)}</td><td class="r num">${fmt(r.calls)}</td><td class="r num">${fmt(r.prompt_tokens)}</td>
    <td class="r num">${pct(r.cache_hit_tokens, r.prompt_tokens)}</td><td class="r num">${fmt(r.completion_tokens)}</td><td class="r num">${fmt(r.errors)}</td></tr>`).join('')}</tbody></table>`
    : emptyState('这段时间没有 AI 调用');
}

/* ================= 团队跟进 ================= */
async function team(params) {
  const days = +(params.days || 30);
  setPage(`${pageHead('团队跟进', rangeSelect(days))}
    <div class="body"><div class="blk"><div class="blk-b flush tb-scroll" id="list" style="padding-top:0"></div></div></div>`);
  $('#days').onchange = e => go('/team', {days: e.target.value});
  const rows = await call('/api/admin/team?days=' + days);
  if (!rows) return;
  $('#list').innerHTML = rows.length ? `<table class="tb"><thead><tr><th>成员</th><th class="r">负责线索</th><th class="r">跟进记录（${days} 天）</th><th class="r">已合作</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${esc(r.user)}</td><td class="r num">${fmt(r.owned)}</td><td class="r num">${fmt(r.followups)}</td><td class="r num">${fmt(r.won)}</td></tr>`).join('')}</tbody></table>`
    : emptyState('还没有成员认领线索');
}

// 放在文件末尾：所有页面函数和常量定义完成后再启动路由
const routes = {'/monitor': monitor, '/stores': stores, '/sources': sources, '/users': users, '/settings': settings, '/usage': usage, '/team': team};
startRouter(routes, (path, fn, params) => { clearInterval(timer); closePop(); $('#rec-float')?.remove(); setActiveNav(path); fn(params); });
