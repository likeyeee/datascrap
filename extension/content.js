// 内容脚本：识别独立站；在搜索结果、广告库等页面自动提取站点并标注评级。

const PLATFORMS = [
  ['shoplazza', /shoplazza|myshoplaza\.com/i],
  ['shopline', /myshopline\.com|shopline\.com/i],
  ['shopyy', /shopyy/i],
  ['ueeshop', /ueeshop/i],
  ['shopify', /cdn\.shopify\.com|Shopify\.theme|myshopify\.com/i],
  ['woocommerce', /wp-content\/plugins\/woocommerce|woocommerce-/i],
  ['bigcommerce', /cdn11\.bigcommerce\.com/i],
  ['wix', /static\.wixstatic\.com.*(?:ecom|store)|wix-ecommerce/i],
  ['squarespace', /squarespace-commerce/i],
  ['magento', /mage\/cookies|Magento_/i],
];

// 列表类页面：搜索结果、广告库。在这些页面上自动提取外部站点、标注评级
const LISTING_PAGES = [
  /^https:\/\/(www\.)?google\.[a-z.]+\/search/,
  /^https:\/\/(www\.|cn\.)?bing\.com\/search/,
  /^https:\/\/(html\.)?duckduckgo\.com\//,
  /^https:\/\/(www\.)?facebook\.com\/ads\/library/,
  /^https:\/\/library\.tiktok\.com\/ads/,
  /^https:\/\/ads\.tiktok\.com\/business\/creativecenter/,
];
// 这些域名本身不是独立站，提取时直接跳过，减少无效提交
const SKIP_HOSTS = /(^|\.)(aka|yellowpages|google|gstatic|googleusercontent|youtube|bing|microsoft|msn|live|duckduckgo|facebook|fbcdn|instagram|tiktok|tiktokcdn|twitter|x|linkedin|pinterest|reddit|wikipedia|amazon|ebay|etsy|walmart|apple|yelp|shopify|w3|schema|cloudflare|akamaihd)\.[a-z.]+$/i;

function pageSignature() {
  const parts = [];
  document.querySelectorAll('script[src],link[href]').forEach(el => parts.push(el.src || el.href));
  document.querySelectorAll('meta[name=generator]').forEach(el => parts.push(el.content));
  document.querySelectorAll('script:not([src])').forEach((el, i) => { if (i < 40) parts.push(el.textContent.slice(0, 2000)); });
  return parts.join('\n');
}

function detectPlatform() {
  const sig = pageSignature();
  for (const [name, rx] of PLATFORMS) if (rx.test(sig)) return name;
  const body = (document.body?.innerText || '').toLowerCase();
  const hints = ['add to cart', 'checkout', 'buy now', 'shopping bag'].filter(h => body.includes(h)).length;
  return hints >= 2 ? 'custom' : null;
}

// 跳转链接解码：Google /url?q=、Facebook l.php?u=、Bing ck/a、DuckDuckGo uddg
function realUrl(href) {
  try {
    const u = new URL(href, location.href);
    for (const key of ['q', 'u', 'url', 'uddg', 'target']) {
      const v = u.searchParams.get(key);
      if (v && /^https?:\/\//i.test(v)) return v;
    }
    if (u.hostname.endsWith('bing.com') && u.pathname.startsWith('/ck/a')) {
      const v = u.searchParams.get('u');
      if (v && v.startsWith('a1')) {
        const b64 = v.slice(2).replace(/-/g, '+').replace(/_/g, '/');
        return atob(b64 + '='.repeat((4 - b64.length % 4) % 4));
      }
    }
    return u.href;
  } catch (e) { return null; }
}

function hostOf(href) {
  const url = realUrl(href);
  if (!url || !/^https?:/i.test(url)) return null;
  try { return new URL(url).hostname.replace(/^www\./, '').toLowerCase(); } catch (e) { return null; }
}

function externalLinks() {
  const here = location.hostname.replace(/^www\./, '');
  const out = [];
  document.querySelectorAll('a[href]').forEach(a => {
    const host = hostOf(a.getAttribute('href'));
    if (host && host !== here && !host.endsWith('.' + here) && !SKIP_HOSTS.test(host)) out.push([a, host]);
  });
  return out;
}

function extractDomains({includeText = true} = {}) {
  const set = new Set(externalLinks().map(([, h]) => h));
  if (includeText) {
    // 广告库等页面中以纯文本出现的网址（如 "SHOP.EXAMPLE.COM"）
    const text = document.body?.innerText || '';
    const rx = /\b((?:[a-z0-9-]+\.)+(?:com|shop|store|co|us|net|org|io|club|online|life|style|fashion|beauty|xyz))\b/gi;
    let m, n = 0;
    while ((m = rx.exec(text)) && n < 2000) {
      const h = m[1].toLowerCase().replace(/^www\./, '');
      if (!SKIP_HOSTS.test(h)) set.add(h);
      n++;
    }
  }
  return [...set];
}

// ---------- 评级标注 ----------
const GRADE_COLORS = {A: '#16a34a', B: '#2563eb', C: '#d97706', D: '#9ca3af'};
function chip(info) {
  const el = document.createElement('span');
  el.className = 'scout-chip';
  const g = info.grade;
  const text = g ? `${g} · ${info.total_score}` : info.status === 'scored' ? '已打分' : '已入库';
  el.textContent = text;
  el.title = [info.main_products, info.chinese_type, info.outreach_status && `跟进：${info.outreach_status}`].filter(Boolean).join(' · ');
  el.style.cssText = `display:inline-block;margin-left:6px;padding:0 6px;border-radius:5px;font:600 11px/18px system-ui,sans-serif;
    color:#fff;background:${GRADE_COLORS[g] || '#64748b'};vertical-align:middle;white-space:nowrap`;
  return el;
}
async function annotate() {
  const links = externalLinks().filter(([a]) => !a.dataset.scout).slice(0, 400);
  if (!links.length) return;
  const hosts = [...new Set(links.map(([, h]) => h))];
  let found;
  try { found = await chrome.runtime.sendMessage({type: 'lookupBatch', domains: hosts}); } catch (e) { return; }
  if (!found || found.error) return;
  for (const [a, h] of links) {
    a.dataset.scout = '1';
    if (found[h] && !a.querySelector('.scout-chip') && a.textContent.trim()) a.after(chip(found[h]));
  }
}

// ---------- 列表页自动提取 ----------
let sent = new Set();
let timer = null;
async function autoRun() {
  const domains = extractDomains({includeText: /facebook\.com\/ads|tiktok\.com/.test(location.href)}).filter(d => !sent.has(d));
  if (domains.length) {
    domains.forEach(d => sent.add(d));
    try { await chrome.runtime.sendMessage({type: 'autoExtract', domains, url: location.href}); } catch (e) { /* 插件更新后旧页面会失效 */ }
  }
  annotate();
}
async function startListingMode() {
  let cfg;
  try { cfg = await chrome.runtime.sendMessage({type: 'settings'}); } catch (e) { return; }
  if (!cfg || !cfg.token) return;
  if (!cfg.autoExtract && !cfg.annotate) return;
  const run = () => { clearTimeout(timer); timer = setTimeout(cfg.autoExtract ? autoRun : annotate, 1500); };
  run();
  // 广告库、搜索结果会滚动加载，监听页面变化持续提取
  new MutationObserver(run).observe(document.body, {childList: true, subtree: true});
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type === 'detect') reply({platform: detectPlatform(), host: location.hostname, url: location.href, listing: isListing});
  if (msg.type === 'extract') reply({domains: extractDomains(), url: location.href});
  return true;
});

const isListing = LISTING_PAGES.some(rx => rx.test(location.href));
if (isListing) {
  startListingMode();
} else {
  // 普通页面：识别是否为独立站，交给后台决定是否上报
  chrome.runtime.sendMessage({type: 'visited', platform: detectPlatform(), host: location.hostname, url: location.href})
    .catch(() => {});
}
