/* 线索：表格列定义、记录详情面板、状态修改。前台线索库、我的线索与后台站点管理共用 */
import {
  $, $$, esc, fmt, ago, icon, call, toast, copyText, menu,
  gradeTag, cnTag, outreachTag, statusTag, tagList,
} from '/static/ui.js';

let META = null;
export function setMeta(m) { META = m; }
const me = () => META.user;
const canEdit = r => me().role === 'admin' || !r.owner_id || r.owner_id === me().id;

/** 修改跟进状态（推进状态会自动认领） */
export async function setStatus(row, status) {
  if (!canEdit(row)) { toast(`已由 ${row.owner || '同事'} 负责，不能修改`, true); return false; }
  const ok = await call('/api/stores/' + row.id, {method: 'PATCH', body: {outreach_status: status}});
  if (ok) toast(`已改为“${status}”`);
  return !!ok;
}
export function statusMenu(anchor, row, onDone) {
  menu(anchor, META.outreach_statuses.map(s => ({label: outreachTag(s), value: s, on: s === row.outreach_status})),
    async it => { if (it.value !== row.outreach_status && await setStatus(row, it.value)) onDone(); });
}

/** 线索库表格列 */
export function leadColumns({showStatus = false} = {}) {
  return [
    {key: 'domain', title: '店铺', width: 210, sticky: true, render: r => `<span class="domain">${esc(r.domain)}</span>${r.starred ? `<span style="color:#ffc60a;margin-left:4px">★</span>` : ''}`},
    ...(showStatus ? [{key: 'status', title: '采集状态', width: 104, render: r => statusTag(r.status)}] : []),
    {key: 'grade', title: '等级', width: 64, render: r => gradeTag(r.grade)},
    {key: 'total_score', title: '总分', width: 72, align: 'r', render: r => r.total_score != null ? `<span class="num">${r.total_score}</span>` : '<span class="t3">-</span>'},
    {key: 'main_products', title: '主营产品', width: 260, render: r => esc(r.main_products || '')},
    {key: 'main_categories', title: '品类', width: 180, render: r => tagList(r.main_categories, 2)},
    {key: 'chinese_type', title: '华人类型', width: 120, render: r => cnTag(r.chinese_type)},
    {key: 'promotion_channels', title: '推广方式', width: 220, render: r => tagList(r.promotion_channels, 2)},
    {key: 'outreach_status', title: '跟进状态', width: 104, render: r => `<span class="cell-edit" data-status data-stop>${outreachTag(r.outreach_status)}</span>`},
    {key: 'owner', title: '负责人', width: 104, render: r => r.owner ? `<span class="row" style="gap:6px"><span class="avatar" style="width:20px;height:20px;font-size:11px">${esc(r.owner.slice(0, 1))}</span>${esc(r.owner)}</span>` : ''},
    {key: 'emails', title: '邮箱', width: 220, render: r => esc((r.emails || '').split(', ')[0] || '')},
    {key: 'platform', title: '平台', width: 104, render: r => esc(r.platform || '')},
    {key: 'location', title: '所在地', width: 140, render: r => esc(r.location || '')},
    {key: 'scored_at', title: '打分时间', width: 140, render: r => `<span class="t2">${esc(r.scored_at || '')}</span>`},
  ];
}

/** 在表格中给“跟进状态”单元格绑定下拉 */
export function bindStatusCells(el, rows, onChanged) {
  $$('[data-status]', el).forEach(c => c.onclick = e => {
    e.stopPropagation();
    const row = rows.find(r => String(r.id) === c.closest('tr').dataset.id);
    statusMenu(c, row, () => onChanged(row.id));
  });
}

const ACTION = {status: '修改了跟进状态', note: '添加了记录', claim: '认领了线索', release: '释放了线索'};
const MK = {ads: '广告投放', email_sms: '邮件/短信', affiliate_influencer: '联盟/网红', reviews: '评价', analytics: '数据分析', payments: '支付', dropship: '代发工具'};

/**
 * 打开记录详情。container 为分栏中的面板元素；不传时以浮层打开。
 * onChange：数据变化后回调（刷新列表行）；onClose：关闭回调
 */
export async function openRecord(id, {container, onChange = () => {}, onClose = () => {}} = {}) {
  let panel = container;
  if (!panel) {
    panel = $('#rec-float') || Object.assign(document.createElement('aside'), {id: 'rec-float', className: 'rec float'});
    document.body.append(panel);
  }
  panel.classList.remove('hidden');
  panel.innerHTML = '<div class="rec-b" style="display:grid;place-items:center"><span class="spin"></span></div>';
  const s = await call('/api/stores/' + id);
  if (!s) { panel.classList.add('hidden'); return; }
  const r = s.llm_result || {}, out = r.outreach || {}, cn = r.chinese || {}, ful = r.fulfillment || {};
  const mine = s.owner_id && s.owner_id === me().id;
  const emails = (s.emails || '').split(', ').filter(Boolean), phones = (s.phones || '').split(', ').filter(Boolean);
  const socials = Object.entries(s.socials_map || {});
  const dims = Object.entries(s.scores_map || {});
  const close = () => { panel.classList.add('hidden'); panel.innerHTML = ''; onClose(); };
  const refresh = () => { onChange(id); openRecord(id, {container, onChange, onClose}); };

  panel.innerHTML = `
    <div class="rec-h">
      <div class="row" style="align-items:flex-start">
        <div class="grow"><div class="title ell" title="${esc(s.domain)}">${esc(s.domain)}</div>
          <div class="sm t3 ell">${[s.name, s.platform, s.location].filter(Boolean).map(esc).join(' · ')}</div></div>
        <a class="btn text icon" href="${esc(s.url)}" target="_blank" rel="noopener" title="打开网站">${icon('open')}</a>
        <button class="btn text icon" data-star title="${s.starred ? '取消星标' : '星标'}" style="${s.starred ? 'color:#ffc60a' : ''}">${icon(s.starred ? 'starfill' : 'star')}</button>
        <button class="btn text icon" data-close title="关闭（Esc）">${icon('x')}</button>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn sm" data-status-btn ${s.can_edit ? '' : 'disabled title="已由同事负责"'}>${outreachTag(s.outreach_status)}${icon('down')}</button>
        ${s.owner_id ? `<span class="sm t2">负责人：${mine ? '我' : esc(s.owner)}</span>${s.can_edit ? '<button class="btn link sm" data-release>释放</button>' : ''}`
          : '<button class="btn sm pri" data-claim>认领</button>'}
        <span class="grow"></span>
        ${container ? '<span class="sm t3 hide-n"><span class="kbd">↑</span> <span class="kbd">↓</span> 切换</span>' : ''}
      </div>
    </div>
    <div class="rec-b">
      ${s.status !== 'scored' ? `<div class="rec-sec"><div class="notice warn">${statusTag(s.status)} ${esc(s.error || '尚未完成打分')}</div></div>` : ''}
      <div class="rec-sec"><dl class="kv">
        <dt>等级</dt><dd class="row">${gradeTag(s.grade)}${s.total_score != null ? `<span class="num">${s.total_score} 分</span>` : ''}</dd>
        <dt>主营产品</dt><dd>${esc(s.main_products || '-')}</dd>
        <dt>品类</dt><dd>${tagList(s.main_categories, 6) || '-'}</dd>
        <dt>华人类型</dt><dd>${cnTag(s.chinese_type) || '-'} ${s.chinese_confidence != null ? `<span class="sm t3">置信度 ${s.chinese_confidence}</span>` : ''}</dd>
        <dt>推广方式</dt><dd>${tagList(s.promotion_channels, 8) || '-'}</dd>
        <dt>价格</dt><dd>${esc([r.price_positioning, s.price_range].filter(Boolean).join(' · ') || '-')}</dd>
        <dt>经营</dt><dd>${esc([r.business_model, r.scale, s.product_count ? `${fmt(s.product_count)} 件商品` : ''].filter(Boolean).join(' · ') || '-')}</dd>
        <dt>发货</dt><dd>${esc([ful.ships_from, ful.delivery_time].filter(Boolean).join(' · ') || '-')}${ful.pain_points ? `<div class="sm t3">${esc(ful.pain_points)}</div>` : ''}</dd>
        <dt>邮箱</dt><dd>${emails.map(e => `<div class="row"><a href="mailto:${esc(e)}" class="ell">${esc(e)}</a><button class="btn text sm icon" data-copy="${esc(e)}" title="复制">${icon('copy')}</button></div>`).join('') || '-'}</dd>
        ${phones.length ? `<dt>电话</dt><dd>${phones.map(esc).join('<br>')}</dd>` : ''}
        ${socials.length ? `<dt>社媒</dt><dd class="row wrap">${socials.map(([k, v]) => `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(k)}</a>`).join('<span class="t3">·</span>')}</dd>` : ''}
      </dl></div>

      ${out.angle ? `<div class="rec-sec"><h4>建联建议</h4><dl class="kv">
        <dt>切入点</dt><dd>${esc(out.angle)}</dd>
        <dt>推荐渠道</dt><dd>${esc(out.recommended_channel || '-')}${out.contact ? ` · <span class="mono">${esc(out.contact)}</span>` : ''}</dd></dl>
        ${out.opening_line ? `<div class="quote-box" style="margin-top:10px"><div class="row" style="align-items:flex-start"><div class="grow">${esc(out.opening_line)}</div>
          <button class="btn text sm icon" data-copy-open title="复制开场白">${icon('copy')}</button></div></div>` : ''}</div>` : ''}

      <div class="rec-sec"><h4>跟进记录</h4>
        <form data-note class="col">
          <textarea class="input" name="content" rows="2" placeholder="${s.can_edit ? '记录这次沟通，Ctrl + Enter 保存' : '已由同事负责，只能查看'}" ${s.can_edit ? '' : 'disabled'}></textarea>
          <div class="row" style="justify-content:flex-end"><button class="btn sm pri" ${s.can_edit ? '' : 'disabled'}>添加</button></div>
        </form>
        <div data-timeline><div class="sm t3" style="padding:8px 0">加载中…</div></div>
      </div>

      ${dims.length || r.reasoning ? `<div class="rec-sec"><h4>AI 评估</h4>
        ${dims.length ? `<div class="bars-mini">${dims.map(([k, v]) => `<span class="t2">${esc(META.dimensions[k] || k)}</span><div class="meter"><i style="width:${Math.min(100, +v)}%"></i></div><span class="num" style="text-align:right">${esc(v)}</span>`).join('')}</div>` : ''}
        ${r.reasoning ? `<p style="margin-top:12px">${esc(r.reasoning)}</p>` : ''}
        ${(r.red_flags || []).length ? `<div class="sm" style="margin-top:8px;color:var(--t-orange)">风险：${r.red_flags.map(esc).join('；')}</div>` : ''}
        <div class="sm t3" style="margin-top:8px">${esc(s.llm_model || '')} · ${esc(s.scored_at || '')}</div></div>` : ''}

      <div class="rec-sec"><details class="fold"><summary>${icon('right')}华人判断依据</summary><div class="fold-b">
        <div class="sm t2" style="margin-bottom:6px">规则分 ${s.cn_rule_score ?? '-'} · 推断经营地 ${esc({us: '美国', china: '中国', unknown: '未知'}[s.cn_location] || '-')}</div>
        ${(cn.evidence || []).length ? `<ul style="margin:0 0 8px;padding-left:18px">${cn.evidence.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
        ${(s.cn_signals || []).length ? `<table class="tb"><tbody>${s.cn_signals.map(x => `<tr><td>${esc(x.detail)}</td><td class="r t3 num">+${x.weight}</td></tr>`).join('')}</tbody></table>` : '<div class="sm t3">没有命中规则信号</div>'}
        ${s.domain_registration?.registrar ? `<div class="sm t3" style="margin-top:8px">域名注册：${esc(s.domain_registration.registrar)} · ${esc(s.domain_registration.created || '')} · ${esc([s.domain_registration.registrant_country, s.domain_registration.registrant_state].filter(Boolean).join(' ') || '注册人已隐藏')}</div>` : ''}
      </div></details></div>

      <div class="rec-sec"><details class="fold"><summary>${icon('right')}营销工具与商品样本</summary><div class="fold-b">
        ${Object.keys(s.marketing || {}).length ? `<dl class="kv" style="margin-bottom:12px">${Object.entries(s.marketing).map(([k, v]) => `<dt>${esc(MK[k] || k)}</dt><dd>${v.map(esc).join('、')}</dd>`).join('')}</dl>` : ''}
        ${(s.products || []).length ? `<table class="tb"><tbody>${s.products.map(p => `<tr><td>${esc(p.title)}</td><td class="r t3 num">${p.price != null ? '$' + p.price : ''}</td></tr>`).join('')}</tbody></table>` : '<div class="sm t3">没有采集到商品</div>'}
      </div></details></div>

      <div class="rec-sec"><details class="fold"><summary>${icon('right')}发现来源</summary><div class="fold-b sm t2">
        ${s.discoveries.map(d => `<div>${esc(d.at.replace('T', ' '))} · ${esc(d.source)} ${esc(d.detail || '')}</div>`).join('') || '-'}</div></details></div>
    </div>`;

  $('[data-close]', panel).onclick = close;
  $$('[data-copy]', panel).forEach(b => b.onclick = () => copyText(b.dataset.copy));
  const co = $('[data-copy-open]', panel);
  if (co) co.onclick = () => copyText(out.opening_line, '开场白已复制');
  $('[data-star]', panel).onclick = async () => { if (await call('/api/stores/' + id, {method: 'PATCH', body: {starred: !s.starred}})) refresh(); };
  const sb = $('[data-status-btn]', panel);
  sb.onclick = () => statusMenu(sb, s, refresh);
  const claim = $('[data-claim]', panel);
  if (claim) claim.onclick = async () => { if (await call(`/api/stores/${id}/claim`, {method: 'POST'})) { toast('已认领'); refresh(); } };
  const rel = $('[data-release]', panel);
  if (rel) rel.onclick = async () => { if (await call(`/api/stores/${id}/release`, {method: 'POST'})) { toast('已释放'); refresh(); } };

  const form = $('[data-note]', panel);
  const save = async () => {
    const content = form.content.value.trim();
    if (!content) return;
    if (await call(`/api/stores/${id}/followups`, {method: 'POST', body: {content}})) { form.content.value = ''; loadTimeline(); }
  };
  form.onsubmit = e => { e.preventDefault(); save(); };
  form.content.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) save(); };
  async function loadTimeline() {
    const list = await call(`/api/stores/${id}/followups`) || [];
    $('[data-timeline]', panel).innerHTML = list.length ? list.map(f => `<div class="comment"><span class="avatar">${esc(f.user.slice(0, 1))}</span>
      <div class="grow"><div class="who"><b style="font-weight:500">${esc(f.user)}</b> <span class="t3">${esc(ACTION[f.action] || f.action)} · ${ago(f.at)}</span></div>
      ${f.content ? `<div class="content">${f.action === 'status' ? f.content.split(' → ').map(x => outreachTag(x)).join(' → ') : esc(f.content)}</div>` : ''}</div></div>`).join('')
      : '<div class="sm t3" style="padding:8px 0">还没有跟进记录</div>';
  }
  loadTimeline();
  return s;
}
