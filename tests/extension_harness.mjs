// 插件后台脚本的集成测试：在 Node 中模拟 chrome.* API，对真实运行的服务器发请求。
// 用法：node tests/extension_harness.mjs <服务器地址> <个人令牌>
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const [server, token] = process.argv.slice(2);
const dir = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1')), '..', 'extension');
const store = {server, token, autoReport: true, autoExtract: true, annotate: true};
const listeners = [];
const badges = [];
const chrome = {
  storage: {sync: {get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : Object.keys(keys)).filter(k => k in store).map(k => [k, store[k]])),
                   set: async obj => Object.assign(store, obj)}},
  runtime: {onMessage: {addListener: fn => listeners.push(fn)}, onInstalled: {addListener() {}}, onStartup: {addListener() {}}},
  action: {setBadgeText: b => badges.push(b.text), setBadgeBackgroundColor() {}},
  contextMenus: {create() {}, onClicked: {addListener() {}}},
};
const ctx = vm.createContext({chrome, fetch, console, URL, self: {}, importScripts: () => {}});
vm.runInContext(fs.readFileSync(path.join(dir, 'background.js'), 'utf8'), ctx);
const send = (msg, tab = {id: 1}) => new Promise(res => listeners[0](msg, {tab}, res));

const me = await send({type: 'ping'});
assert.ok(me.username, '令牌应能识别用户：' + JSON.stringify(me));

const uniq = 'harness-' + Date.now();
const r1 = await send({type: 'autoExtract', domains: [`${uniq}.com`, 'demo-shop-01.com'], url: 'https://www.google.com/search?q=x'});
assert.equal(r1.received, 2);
assert.equal(r1.added, 1, '新域名应入库，已存在的不重复入库');
const r2 = await send({type: 'autoExtract', domains: [`${uniq}.com`], url: 'x'});
assert.equal(r2.received, 0, '同一会话内重复提交应被去重');

const found = await send({type: 'lookupBatch', domains: ['demo-shop-01.com', 'www.demo-shop-02.com', 'not-in-db-xyz.com']});
assert.ok(found['demo-shop-01.com'] && found['www.demo-shop-02.com'], '已入库站点应返回评级：' + JSON.stringify(found));
assert.ok(!found['not-in-db-xyz.com']);

const v = await send({type: 'visited', platform: 'shopify', host: `www.visit-${uniq}.com`, url: 'https://x'});
assert.equal(v.status, 'new', '浏览到新独立站应自动入库');
assert.ok(badges.includes('shop') && badges.includes('已入'));

const stats = await send({type: 'stats'});
assert.ok(stats.submitted >= 3 && stats.added >= 2);

store.token = 'sk_wrong';
const bad = await send({type: 'ping'});
assert.match(bad.error, /令牌无效/);
console.log('extension harness: all checks passed');
