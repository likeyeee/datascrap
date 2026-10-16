# AGENTS.md

给在本仓库工作的 AI 编码助手和开发者的说明。产品与架构设计见 [design.md](design.md)，部署与使用见 [README.md](README.md)。

## 项目是什么

**线索雷达**：持续发现美国市场的独立站，采集主营产品、推广方式、联系方式、华人卖家信号，交给 DeepSeek 按“海外仓合作 + 我方产品上架合作”的可行性打分。

- **前台** `/app`：运营、招商人员查看线索、认领、记录跟进、下载浏览器插件
- **后台** `/admin`：管理员监控采集、管理渠道、站点、用户、打分配置、AI 用量
- **浏览器插件** `extension/`：浏览时收集站点、在搜索结果旁标注评级

业务方是一家在美国有仓库的跨境电商公司，重点找在美华人卖家和国内跨境卖家。

## 已确定的约束（不要擅自改变）

- **只用免费数据源**：不要引入 SerpAPI、StoreLeads、BuiltWith 等付费 API
- **LLM 用 DeepSeek**（OpenAI 兼容接口，`deepseek-flash` 初筛、`deepseek-v4-pro` 复核），不要换厂商
- **部署在 Linux + Docker + Postgres**；本地开发用 SQLite，代码必须两者都能跑
- **合规**：遵守 robots.txt；不绕过验证码、不伪装浏览器绕过封锁；搜索引擎抓取渠道默认关闭
- **前端无构建步骤**：原生 ES Module + 手写 CSS，不引入 npm 构建链或前端框架；不依赖外部 CDN（服务器可能在国内访问）
- **界面文字、代码注释、提交说明使用中文**

## 常用命令

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Linux: .venv/bin/pip
python -m scout start                  # 网站 + 自动采集（单进程，本地/单机推荐）
python -m scout serve                  # 只启动网站
python -m scout run                    # 只运行采集（Docker 中的 worker 容器）
python -m scout create-user NAME --admin
python -m scout crawl example.com      # 调试：采集单站，打印结果，不写库
python -m scout process example.com    # 单站采集 + 打分并写库（会调用 DeepSeek）
python -m scout discover commoncrawl   # 手动运行一次发现渠道
python -m pytest -q                    # Python 测试（使用 data/test.db，不影响正式数据）
node tests/extension_harness.mjs http://127.0.0.1:8000 <个人令牌>   # 插件后台脚本对接真实服务器的测试
python extension/make_icons.py         # 重新生成插件图标
```

Windows 下用 `.venv\Scripts\python.exe`。

## 目录

```
config/              运行配置；company.yaml / scoring.yaml 可在后台在线覆盖（存数据库）
scout/
  config.py          加载 yaml + 环境变量覆盖；company()/scoring() 优先读数据库，30 秒缓存
  db.py              SQLAlchemy 模型；init_db() 会自动补齐新增的列（只加不改）
  auth.py            密码、签名 Cookie 会话、插件个人令牌、权限依赖
  domains.py         域名标准化、黑名单、候选入库 add_candidates()
  crawler/           fetcher（限速/robots）、extract（纯函数）、products、dnsinfo、cn（华人识别）、pipeline
  sources/           发现渠道插件（继承 Source，@register）
  llm/               DeepSeek 客户端、提示词与打分
  worker.py          采集/打分队列的领取与写回
  scheduler.py       持续运行：心跳、采集、打分、发现、维护五个循环
  analytics.py       看板统计口径（前后台共用）
  stats.py           LLM 每日用量、worker 心跳
  exporter.py        线索查询条件、Excel/CSV 导出
  api/               app.py（页面+挂载）、auth_routes.py、public.py（前台）、admin.py（后台）
  web/               login.html、app.html、admin.html、static/{base.css, ui.js, lead.js, app.js, admin.js}
extension/           Chrome MV3 插件；config.js 由服务器在下载时替换为预置配置
tests/               pytest + 插件 Node 测试
```

## 关键约定与坑

**数据与状态**
- 站点状态机：`new → crawling → crawled → scoring → scored`；终态 `alias / not_store / not_target / dead / blocked / failed / score_failed`。新增状态时同步更新 `web/static/ui.js` 的 `STATUS_LABEL`
- 失败用 `retry_at` 退避重试（1h、4h、9h），不要做立即重试的循环
- JSON 列以 `ensure_ascii=False` 存储，中文可以直接 `ILIKE` 搜索；不要改回默认序列化
- 数据库迁移只支持“新增可空列/新表”。重命名或改类型需要写迁移脚本，并在 README 中说明
- 修改 `Store` 字段后，检查 `exporter.store_row()`、`worker.STORE_FIELDS`、`llm/scorer.build_input()` 是否需要同步

**采集**
- Shopify 对 `products.json`、`meta.json` 单独限流（429），已关店的店 `meta.json` 也返回 429。所以先抓首页判断关店/跳转，商品优先用 `collections/all.atom` 和 sitemap
- 所有 Shopify 托管店铺共用一个限速组（`fetcher.SHOPIFY_GROUP`）；`.json/.atom` 接口的 429 不会暂停整组
- RDAP 只是辅助信息，被限流就跳过并冷却 10 分钟，不能阻塞采集
- `crawler/extract.py` 保持纯函数，新增识别规则优先写进 `config/cn_signals.yaml` 或 `MARKETING_PATTERNS`，并在 `tests/test_extract.py` 加用例

**LLM**
- 系统提示词由 `company()` + `scoring()` 生成，内容要保持稳定以命中 DeepSeek 前缀缓存；不要往里放时间戳等易变内容
- 总分由程序按权重计算（`scorer.compute_total`），不要让模型直接给总分
- 每次调用都会记入 `llm_usage_daily`；新增调用路径时也要走 `DeepSeekClient.chat_json`

**权限**
- 前台接口用 `Depends(current_user)`，后台接口放在 `api/admin.py`（路由器级别 `require_admin`）
- 成员只能看 `status == scored` 的线索；已被认领的线索只有负责人和管理员能改状态
- 系统令牌（`.env` 的 `API_TOKEN`）少于 16 位或为 `change-me` 时一律不认
- 插件个人令牌只存 sha256 哈希；下载插件包会生成新令牌并使旧令牌失效

**前端**
- 页面脚本是 ES Module，`startRouter(...)` 必须放在文件**末尾**，否则路由回调访问后面声明的 `const` 会触发 TDZ 错误
- 拼接 HTML 时所有动态内容都要经过 `esc()`
- 视觉参照飞书 / 多维表格（详见 design.md 第 12 节）：白底 + 分隔线，唯一主色 `#3370ff`；**不要**加渐变、装饰图标、问候语、空洞的副标题
- 颜色只用 `base.css` 中的 CSS 变量，亮色/暗色两套都要定义；选项值用 `tag()` / `gradeTag()` / `cnTag()` / `outreachTag()`，不要自造颜色
- 列表页用 `renderTable()`（多维表格样式，支持固定列、勾选、当前行），页面用 `setPage(html, {fill: true})`；详情统一用 `lead.js` 的 `openRecord()`（传 `container` 为分栏，不传为浮层）
- 下拉与筛选用 `menu()` / `popover()`，弹窗用 `modal()` / `confirmBox()`
- 图表单一系列用 `--series-1`，不做双轴图
- 静态资源以 `Cache-Control: no-cache` 返回；改动后浏览器会自动拿到新版本
- 桌面优先；窄屏下不能出现整页横向滚动，宽表格放在 `.bt-wrap` / `.tb-scroll` 里

**插件**
- `content.js` 是经典脚本（不是模块），只做 DOM 读取；所有网络请求经 `background.js` 发出
- 列表页（搜索结果、广告库）自动提取；普通页面只识别当前站点。新增列表页在 `LISTING_PAGES` 中添加
- 只读取用户正在浏览的页面，不做自动翻页、自动点击

## 常见改动怎么做

- **新增发现渠道**：在 `scout/sources/` 新建文件，继承 `Source`，实现 `async run() -> str`，用 `@register` 注册并在 `sources/__init__.py` 导入；在 `config/settings.yaml` 的 `scheduler.sources` 加开关与间隔；在 `api/admin.py` 的 `SOURCE_INFO` 加中文名称和说明
- **新增打分维度**：在后台“打分配置”或 `config/scoring.yaml` 增加维度（含 `label`、`weight`、`desc`），提示词和总分会自动包含
- **新增看板指标**：在 `analytics.py` 计算，`api/public.py` 的 `/api/overview` 返回，`web/static/app.js` 渲染（用 `barList` / `columnChart` / `funnel`）
- **新增后台页面**：在 `web/static/admin.js` 写页面函数，加入 `shell({nav})` 和文件末尾的 `routes`

## 完成改动前

1. `python -m pytest -q` 全部通过
2. 改了前端：启动服务，在桌面宽度和手机宽度下各看一遍，控制台无报错
3. 改了插件：`node --check extension/*.js`，有服务器时运行 `tests/extension_harness.mjs`
4. 改了表结构或配置项：更新 README 和 design.md 中对应的章节
