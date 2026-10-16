/* 前台：运营、招商人员使用 */
import {
  $, $$, esc, fmt, pct, icon, api, call, toast, guard, shell, setActiveNav, setNavCount, startRouter, go, replaceHash,
  pageHead, setPage, popover, closePop, menu, renderTable, markCurrent, barList, columnChart, funnel,
  tag, gradeTag, cnTag, outreachTag, emptyState, copyText, confirmBox,
} from '/static/ui.js';
import {setMeta, openRecord, leadColumns, bindStatusCells, statusMenu} from '/static/lead.js';

const me = await guard();
if (!me) throw new Error('跳转登录');
const META = await api('/api/meta');
setMeta(META);

shell({
  user: me,
  nav: [
    {path: '/leads', label: '线索库', icon: 'table'},
    {path: '/mine', label: '我的跟进', icon: 'board'},
    {path: '/overview', label: '数据概览', icon: 'chart'},
    {group: '工具'},
    {path: '/extension', label: '浏览器插件', icon: 'plug'},
  ],
  switchLink: me.role === 'admin' ? {href: '/admin', label: '管理后台'} : null,
});

let cleanup = () => {};
const onKey = fn => { document.addEventListener('keydown', fn); cleanup = () => document.removeEventListener('keydown', fn); };
const typing = e => e.target.closest?.('input,textarea,select,[contenteditable]');

/* ================= 线索库 ================= */
const VIEWS = [['', '全部线索'], ['unowned', '未认领'], ['mine', '我负责的'], ['starred', '星标']];
const SORTS = [['score', '总分从高到低'], ['scored', '最近打分'], ['updated', '最近更新'], ['cn', '华人信号从强到弱']];
const FILTER_KEYS = ['grade', 'chinese_type', 'outreach_status', 'platform', 'category', 'min_score'];
const FILTER_LABEL = {grade: '等级', chinese_type: '华人类型', outreach_status: '跟进状态', platform: '平台', category: '品类', min_score: '最低分'};
const PAGE = 50;

async function leads(params) {
  const st = {...params, sort: params.sort || 'score', page: +(params.page || 1)};
  const nav = patch => go('/leads', {...st, ...patch, page: patch.page || '', open: ''});
  const active = FILTER_KEYS.filter(k => st[k]);
  setPage(`
    ${pageHead('线索库', `<button class="btn" id="export">${icon('download')}导出</button>`)}
    <div class="views">${VIEWS.map(([v, l]) => `<button data-v="${v}" class="${(st.scope || '') === v ? 'on' : ''}">${l}</button>`).join('')}</div>
    <div class="toolbar">
      <button class="btn text ${active.length ? 'on' : ''}" id="f-btn" data-pop-anchor>${icon('filter')}筛选${active.length ? ` <span class="badge-n">${active.length}</span>` : ''}</button>
      <button class="btn text" id="s-btn" data-pop-anchor>${icon('sort')}${SORTS.find(s => s[0] === st.sort)?.[1] || '排序'}</button>
      <span class="sep"></span>
      <div class="search">${icon('search')}<input class="input" id="q" placeholder="搜索域名、店名、主营产品" value="${esc(st.q || '')}"></div>
      <div class="row wrap grow" id="chips" style="gap:6px;margin-left:8px">${active.map(k => `<span class="tag blue" style="height:24px">${FILTER_LABEL[k]}：${esc(st[k])}
        <span data-rm="${k}" style="margin-left:4px;cursor:pointer">✕</span></span>`).join('')}
        ${active.length ? '<button class="btn link sm" data-clear>清除</button>' : ''}</div>
    </div>
    <div class="split">
      <div class="bt-col"><div class="bt-wrap" id="tbl"><div class="empty"><span class="spin"></span></div></div>
        <div class="tbl-foot"><span id="total"></span><span class="grow"></span>
          <button class="btn text sm icon" id="prev" title="上一页">${icon('right').replace('<path', '<path transform="rotate(180 12 12)"')}</button>
          <span id="pno" class="num"></span>
          <button class="btn text sm icon" id="next" title="下一页">${icon('right')}</button></div></div>
      <aside class="rec hidden" id="rec"></aside>
    </div>`, {fill: true});

  $$('.views button').forEach(b => b.onclick = () => nav({scope: b.dataset.v}));
  $('#q').onkeydown = e => { if (e.key === 'Enter') nav({q: e.target.value.trim()}); };
  $$('[data-rm]').forEach(x => x.onclick = () => nav({[x.dataset.rm]: ''}));
  $('[data-clear]')?.addEventListener('click', () => nav(Object.fromEntries(FILTER_KEYS.map(k => [k, '']))));
  $('#s-btn').onclick = e => menu(e.currentTarget, SORTS.map(([v, l]) => ({label: l, value: v, on: v === st.sort})), it => nav({sort: it.value}));
  $('#f-btn').onclick = e => filterPanel(e.currentTarget, st, nav);
  $('#export').onclick = () => {
    const q = new URLSearchParams(Object.entries({...st, fmt: 'xlsx', page: '', open: ''}).filter(([, v]) => v)).toString();
    location.href = '/api/export?' + q;
  };

  let rows = [], current = st.open ? +st.open : null;
  const tbl = $('#tbl'), rec = $('#rec');
  const load = async () => {
    const q = new URLSearchParams(Object.entries({...st, open: '', size: PAGE}).filter(([, v]) => v !== '' && v != null)).toString();
    const d = await call('/api/stores?' + q);
    if (!d) return;
    rows = d.items;
    const pages = Math.max(1, Math.ceil(d.total / PAGE));
    $('#total').textContent = `共 ${fmt(d.total)} 条`;
    $('#pno').textContent = `${st.page} / ${pages}`;
    $('#prev').disabled = st.page <= 1;
    $('#next').disabled = st.page >= pages;
    $('#prev').onclick = () => nav({page: st.page - 1});
    $('#next').onclick = () => nav({page: st.page + 1});
    renderTable(tbl, leadColumns(), {
      rows, startIndex: (st.page - 1) * PAGE, currentId: current,
      empty: st.scope === 'mine' ? '你还没有负责的线索，在“未认领”中挑选后点击认领' : '没有符合条件的线索，试试调整筛选条件',
      onRow: r => open(r.id),
    });
    bindStatusCells(tbl, rows, () => load());
  };
  const open = id => {
    current = id;
    markCurrent(tbl, id);
    replaceHash('/leads', {...st, page: st.page > 1 ? st.page : '', open: id});
    openRecord(id, {container: rec, onChange: () => load(), onClose: () => { current = null; markCurrent(tbl, null); replaceHash('/leads', {...st, page: st.page > 1 ? st.page : '', open: ''}); }});
  };
  await load();
  if (current) open(current);

  onKey(e => {
    if (typing(e) || $('#modal')) return;
    if (e.key === 'Escape' && current) { $('[data-close]', rec)?.click(); return; }
    if (!['ArrowDown', 'ArrowUp', 'j', 'k'].includes(e.key) || !rows.length) return;
    e.preventDefault();
    const i = rows.findIndex(r => r.id === current);
    const next = e.key === 'ArrowDown' || e.key === 'j' ? Math.min(rows.length - 1, i + 1) : Math.max(0, i - 1);
    open(rows[i < 0 ? 0 : next].id);
  });
}

function filterPanel(anchor, st, nav) {
  const grades = new Set((st.grade || '').split(',').filter(Boolean));
  const cns = new Set((st.chinese_type || '').split(',').filter(Boolean));
  const el = document.createElement('form');
  el.innerHTML = `
    <div class="filter-row"><span>等级</span><div class="chk-tags">${['A', 'B', 'C', 'D'].map(g => `<label><input type="checkbox" name="grade" value="${g}" ${grades.has(g) ? 'checked' : ''}>${gradeTag(g)}</label>`).join('')}</div></div>
    <div class="filter-row" style="align-items:start"><span style="padding-top:2px">华人类型</span><div class="chk-tags">${META.chinese_types.map(t => `<label><input type="checkbox" name="cn" value="${t}" ${cns.has(t) ? 'checked' : ''}>${cnTag(t)}</label>`).join('')}</div></div>
    <div class="filter-row"><span>跟进状态</span><select class="select" name="outreach_status"><option value="">不限</option>${META.outreach_statuses.map(s => `<option ${s === st.outreach_status ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
    <div class="filter-row"><span>平台</span><select class="select" name="platform"><option value="">不限</option>${META.platforms.map(s => `<option ${s === st.platform ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
    <div class="filter-row"><span>品类</span><input class="input" name="category" placeholder="包含关键词，如 宠物" value="${esc(st.category || '')}"></div>
    <div class="filter-row"><span>最低分</span><input class="input" name="min_score" type="number" min="0" max="100" placeholder="0–100" value="${esc(st.min_score || '')}"></div>
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button type="button" class="btn" data-reset>重置</button><button class="btn pri">确定</button></div>`;
  popover(anchor, el, 'panel');
  const pick = name => $$(`[name=${name}]:checked`, el).map(i => i.value).join(',');
  el.onsubmit = e => {
    e.preventDefault(); closePop();
    nav({grade: pick('grade'), chinese_type: pick('cn'), outreach_status: el.outreach_status.value, platform: el.platform.value,
      category: el.category.value.trim(), min_score: el.min_score.value});
  };
  $('[data-reset]', el).onclick = () => { closePop(); nav(Object.fromEntries(FILTER_KEYS.map(k => [k, '']))); };
}

/* ================= 我的跟进（看板） ================= */
async function mine() {
  setPage(`${pageHead('我的跟进', `<a class="btn" href="#/leads?scope=unowned&grade=A,B">认领新线索</a>`)}
    <div class="kanban" id="board"><span class="spin"></span></div>`, {fill: true});
  const d = await call('/api/stores?scope=mine&size=200&sort=updated');
  if (!d) return;
  setNavCount('/mine', d.total);
  const by = Object.fromEntries(META.outreach_statuses.map(l => [l, []]));
  d.items.forEach(r => (by[r.outreach_status] || by['未联系']).push(r));
  const board = $('#board');
  if (!d.total) { board.innerHTML = `<div style="width:100%">${emptyState('你还没有负责的线索。到线索库的“未认领”视图挑选店铺，点击认领后会出现在这里。')}</div>`; return; }
  board.innerHTML = META.outreach_statuses.map(l => `<div class="lane" data-lane="${l}">
    <div class="lane-h">${outreachTag(l)}<span class="sm t3">${by[l].length}</span></div>
    <div class="lane-b">${by[l].map(r => `<div class="kc" draggable="true" data-id="${r.id}">
      <div class="row">${gradeTag(r.grade)}<span class="ell" style="font-weight:500">${esc(r.domain)}</span></div>
      <div class="l2">${esc(r.main_products || '')}</div>
      <div class="row" style="margin-top:8px">${cnTag(r.chinese_type)}<span class="grow"></span><span class="sm t3 num">${r.total_score ?? ''}</span></div>
    </div>`).join('')}</div></div>`).join('');
  let dragId = null;
  $$('.kc', board).forEach(c => {
    c.onclick = () => openRecord(+c.dataset.id, {onChange: () => mine()});
    c.ondragstart = e => { dragId = c.dataset.id; c.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; };
    c.ondragend = () => c.classList.remove('dragging');
  });
  $$('.lane', board).forEach(l => {
    l.ondragover = e => { e.preventDefault(); l.classList.add('drop'); };
    l.ondragleave = () => l.classList.remove('drop');
    l.ondrop = async e => {
      e.preventDefault(); l.classList.remove('drop');
      const row = d.items.find(r => String(r.id) === dragId);
      if (row && row.outreach_status !== l.dataset.lane &&
          await call('/api/stores/' + row.id, {method: 'PATCH', body: {outreach_status: l.dataset.lane}})) mine();
    };
  });
}

/* ================= 数据概览 ================= */
async function overview(params) {
  const days = +(params.days || 30);
  setPage(`${pageHead('数据概览', `<select class="select" id="days">${[7, 30, 90].map(d => `<option value="${d}" ${d === days ? 'selected' : ''}>近 ${d} 天</option>`).join('')}</select>`)}
    <div class="body">
      <div class="stats" id="stats">${'<div class="stat"><div class="skel" style="width:60%"></div><div class="skel" style="height:28px;margin-top:10px;width:40%"></div></div>'.repeat(4)}</div>
      <div class="grid g21 mt">
        <div class="blk"><div class="blk-h"><h3>待联系的优质线索</h3><a class="sm" href="#/leads?scope=unowned&grade=A,B">查看全部</a></div><div class="blk-b flush tb-scroll" id="top"></div></div>
        <div class="blk"><div class="blk-h"><h3>跟进转化</h3></div><div class="blk-b" id="funnel"></div></div>
      </div>
      <div class="blk mt"><div class="blk-h"><h3>线索增长</h3>
        <select class="select" id="metric" style="height:28px"><option value="scored">完成 AI 打分</option><option value="discovered">新发现站点</option><option value="crawled">完成采集</option></select></div>
        <div class="blk-b" id="trend"></div></div>
      <div class="grid g3 mt">
        <div class="blk"><div class="blk-h"><h3>主营品类</h3></div><div class="blk-b" id="d-cat"></div></div>
        <div class="blk"><div class="blk-h"><h3>华人类型</h3></div><div class="blk-b" id="d-cn"></div></div>
        <div class="blk"><div class="blk-h"><h3>推广方式</h3></div><div class="blk-b" id="d-chan"></div></div>
      </div>
    </div>`);
  $('#days').onchange = e => go('/overview', {days: e.target.value});
  const o = await call('/api/overview?days=' + days);
  if (!o) return;
  const k = o.kpi;
  const stats = [
    {k: '已打分线索', v: k.scored, s: `近 7 天新增 ${fmt(k.new_scored_7d)}`, to: ['/leads', {}]},
    {k: 'A / B 级线索', v: k.ab, s: `占 ${k.scored ? pct(k.ab, k.scored) : '-'}`, to: ['/leads', {grade: 'A,B'}]},
    {k: '华人卖家', v: k.cn_us + k.cn_china, s: `在美 ${fmt(k.cn_us)} · 国内 ${fmt(k.cn_china)}`, to: ['/leads', {chinese_type: '在美华人,国内跨境卖家'}]},
    {k: '跟进中', v: k.contacted, s: `已合作 ${fmt(k.won)} · 我负责 ${fmt(o.mine?.total || 0)}`, to: ['/mine', null]},
  ];
  $('#stats').innerHTML = stats.map((t, i) => `<div class="stat click" data-i="${i}"><div class="k">${t.k}</div><div class="v">${fmt(t.v)}</div><div class="s">${t.s}</div></div>`).join('');
  $$('#stats .stat').forEach(el => el.onclick = () => go(...stats[+el.dataset.i].to));

  $('#top').innerHTML = o.top_leads.length ? `<table class="tb"><thead><tr><th>店铺</th><th>等级</th><th>主营产品</th><th>华人类型</th><th class="r">总分</th></tr></thead><tbody>
    ${o.top_leads.map(t => `<tr class="click" data-id="${t.id}"><td style="font-weight:500">${esc(t.domain)}</td><td>${gradeTag(t.grade)}</td>
      <td class="t2" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.main_products || '')}</td><td>${cnTag(t.chinese_type)}</td><td class="r num">${t.total_score}</td></tr>`).join('')}</tbody></table>`
    : emptyState('暂时没有待认领的优质线索');
  $$('#top tr[data-id]').forEach(tr => tr.onclick = () => go('/leads', {scope: 'unowned', open: tr.dataset.id}));
  funnel($('#funnel'), o.funnel);
  const drawTrend = () => columnChart($('#trend'), o.trend[$('#metric').value], {unit: ' 个'});
  $('#metric').onchange = drawTrend;
  drawTrend();
  barList($('#d-cat'), o.categories, {onClick: it => go('/leads', {category: it.label})});
  barList($('#d-cn'), o.chinese_type, {onClick: it => go('/leads', {chinese_type: it.label})});
  barList($('#d-chan'), o.channels);
}

/* ================= 浏览器插件 ================= */
async function extension() {
  const info = await call('/api/me/summary') || {};
  setPage(`${pageHead('浏览器插件')}
    <div class="body narrow">
      <p class="t2">在 Chrome 中浏览时收集独立站：搜索结果和广告库里的站点会自动提交，已入库的站点旁边会显示评级。</p>
      <ol class="steps" style="margin-top:16px">
        <li><div><h3>下载插件</h3><p class="t2" style="margin:4px 0 10px">插件包已经带上服务器地址和你的个人令牌，不需要另外配置。</p>
          <button class="btn pri" id="dl">${icon('download')}下载插件</button>
          ${info.has_token ? '<span class="sm t3" style="margin-left:8px">重新下载会使之前安装的插件失效</span>' : ''}</div></li>
        <li><div><h3>解压到固定的文件夹</h3><p class="t2" style="margin-top:4px">例如 <code>文档\\store-scout-extension</code>。Chrome 会一直从这里读取插件，不要删除。</p></div></li>
        <li><div><h3>在 Chrome 中加载</h3><p class="t2" style="margin-top:4px">打开 <code>chrome://extensions</code>，开启右上角“开发者模式”，点“加载已解压的扩展程序”，选择刚才的文件夹。</p>
          <button class="btn sm" style="margin-top:8px" id="cp-ext">${icon('copy')}复制地址</button></div></li>
        <li><div><h3>固定到工具栏</h3><p class="t2" style="margin-top:4px">点 Chrome 右上角的拼图图标，把“独立站线索采集”固定出来。</p></div></li>
      </ol>

      <div class="form-sec" style="border-top:1px solid var(--line);margin-top:8px">
        <h3>使用方式</h3>
        <dl class="kv" style="grid-template-columns:120px minmax(0,1fr);margin-top:12px">
          <dt>浏览即收集</dt><dd>打开任意独立站，插件识别建站平台后自动加入采集队列，图标上显示评级</dd>
          <dt>自动提取</dt><dd>在 Google、Bing 搜索结果页，或 Meta、TikTok 广告库中浏览时，页面里的站点自动提交，并在链接旁标注评级</dd>
          <dt>一键提取</dt><dd>在榜单文章、Instagram 主页等页面，点插件里的“提取本页所有站点链接”</dd>
          <dt>右键加入</dt><dd>右键任意链接，选择“加入独立站采集队列”</dd>
        </dl>
      </div>

      <div class="form-sec">
        <h3>搜索示例</h3><p class="desc">按华人聚居或仓储地址搜索，命中华人卖家的概率更高。点击复制后到 Google 搜索并多翻几页。</p>
        <table class="tb"><tbody>${['"pet supplies" "City of Industry, CA"', '"kitchen" "Ontario, CA 91761" shop', '"home decor" "Walnut, CA" store', '"phone case" "Shenzhen" "free shipping" USA']
          .map(q => `<tr><td class="mono">${esc(q)}</td><td class="r"><button class="btn text sm" data-q="${esc(q)}">${icon('copy')}复制</button></td></tr>`).join('')}</tbody></table>
        <div class="row" style="margin-top:12px"><a class="btn sm" href="https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US" target="_blank" rel="noopener">${icon('open')}Meta 广告库</a>
          <a class="btn sm" href="https://library.tiktok.com/ads" target="_blank" rel="noopener">${icon('open')}TikTok 广告库</a></div>
      </div>

      <div class="form-sec">
        <h3>个人令牌</h3><p class="desc">手动安装插件时，在插件设置里填写服务器地址和令牌。令牌只显示一次，重新生成后旧令牌立即失效。</p>
        <div class="fr"><label>服务器地址</label><div class="row"><code>${esc(location.origin)}</code><button class="btn text sm icon" data-q="${esc(location.origin)}">${icon('copy')}</button></div></div>
        <div class="fr"><label>令牌</label><div id="tk">${info.has_token ? '<span class="tag green">已生成</span>' : '<span class="tag">未生成</span>'}
          <button class="btn sm" id="gen" style="margin-left:8px">${info.has_token ? '重新生成' : '生成令牌'}</button></div></div>
      </div>
    </div>`);
  $$('[data-q]').forEach(b => b.onclick = () => copyText(b.dataset.q));
  $('#cp-ext').onclick = () => copyText('chrome://extensions');
  $('#dl').onclick = async () => {
    if (info.has_token && !await confirmBox('下载插件', '下载会生成新的个人令牌，之前安装的插件需要换成新下载的版本。', {ok: '下载'})) return;
    location.href = '/api/extension.zip';
    info.has_token = true;
  };
  $('#gen').onclick = async () => {
    if (info.has_token && !await confirmBox('重新生成令牌', '旧令牌会立即失效，已安装的插件需要填写新令牌。', {ok: '重新生成'})) return;
    const r = await call('/api/auth/token', {method: 'POST'});
    if (!r) return;
    info.has_token = true;
    $('#tk').innerHTML = `<div class="row"><code style="word-break:break-all">${esc(r.token)}</code><button class="btn sm" id="cp-tk">${icon('copy')}复制</button></div>
      <div class="sm" style="color:var(--t-orange);margin-top:4px">离开页面后无法再次查看</div>`;
    $('#cp-tk').onclick = () => copyText(r.token, '令牌已复制');
  };
}

call('/api/stores?scope=mine&size=1').then(d => d && setNavCount('/mine', d.total));

// 放在文件末尾：所有页面函数和常量定义完成后再启动路由
const routes = {'/leads': leads, '/mine': mine, '/overview': overview, '/extension': extension};
startRouter(routes, (path, fn, params) => { cleanup(); closePop(); $('#rec-float')?.remove(); setActiveNav(path); fn(params); });
