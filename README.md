# 线索雷达 · 美区独立站合作线索

持续从多个免费渠道发现美国市场独立站，采集主营产品、推广方式、联系方式和华人卖家信号，
再由 DeepSeek 按“海外仓合作 + 产品上架合作”的可行性打分。

- **前台** `/app`：给运营、招商同事用。数据概览、线索库、线索详情与跟进、我的线索看板、浏览器插件下载
- **后台** `/admin`：给管理员用。采集监控、发现渠道、站点管理、用户、打分配置、AI 用量、团队跟进
- **浏览器插件**：浏览时收集独立站，在搜索结果和广告库里自动提取站点并标注评级

架构与设计细节见 [design.md](design.md)；给开发者和 AI 编码助手的约定见 [AGENTS.md](AGENTS.md)。

## 部署（Linux + Docker）

```bash
cp .env.example .env
# 编辑 .env：填写 DEEPSEEK_API_KEY；API_TOKEN 填一串至少 16 位的随机字符
docker compose up -d --build
```

浏览器打开 `http://服务器IP:8000`：

1. 首次访问会进入“创建管理员”页面，输入 `.env` 中的 `API_TOKEN`，设置管理员账号
2. 在后台 **用户** 页给运营、招商同事创建账号（角色选“成员”）
3. 在后台 **打分配置** 页填写我方公司画像：仓库位置与服务、可上架的产品品类、合作偏好
4. 同事登录前台，在 **浏览器插件** 页下载插件并按步骤安装

三个容器：`db`（Postgres）、`api`（网站）、`worker`（自动采集）。在后台 **采集监控** 页可以看到采集进程是否在运行。
对外开放前建议用 Nginx 加 HTTPS（会话 Cookie 在 HTTPS 下自动加 Secure）。

## 本地运行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux/macOS: .venv/bin/pip
python -m scout start                             # 网站 + 自动采集，一个命令启动
```

打开 http://localhost:8000 。本地默认使用 SQLite（`data/scout.db`）。
也可以分开运行：`python -m scout serve`（只网站）和 `python -m scout run`（只采集）。

## 配置

| 位置 | 内容 | 修改方式 |
|---|---|---|
| 后台 · 打分配置 | 公司画像、打分维度与权重、等级阈值 | 在线修改，约 30 秒后对新的打分生效；可恢复为文件默认值 |
| `config/company.yaml`、`config/scoring.yaml` | 上面两项的默认值 | 改文件后重启 |
| `config/settings.yaml` | 并发、限速、重采周期、DeepSeek 模型、各渠道开关与间隔 | 改文件或用环境变量 `SECTION__KEY` 覆盖，重启生效；渠道开关也可在后台切换 |
| `config/cn_signals.yaml` | 华人识别规则：姓氏库、聚居地、国内 DNS/注册商/应用、权重 | 改文件后重启 |
| `config/keywords.yaml` | 搜索渠道关键词、域名黑名单 | 改文件后重启 |
| `.env` | DeepSeek Key、系统令牌、会话密钥、数据库地址 | 重启生效 |

## 采集什么

- **基本信息**：网址、店铺名、建站平台、国家与所在地、币种
- **主营产品**：商品数量、价格区间、商品样本、品类、最近上新；AI 归纳主营产品和品类
- **推广方式**：广告像素、邮件短信工具、联盟与网红工具、评价应用、社媒账号；AI 归纳推广渠道
- **联系方式**：公开的邮箱、电话、社媒主页
- **华人识别**：规则证据 + AI 判断（在美华人 / 国内跨境卖家 / 港澳台 / 非华人 / 无法判断）
- **打分**：海外仓契合、选品契合、华人关联、体量、活跃度、可触达六项，加权得总分和 A/B/C/D 等级，附打分理由、建联切入点和英文开场白

## 发现渠道（全部免费）

| 渠道 | 说明 | 默认 |
|---|---|---|
| 浏览器插件 | 浏览识别、列表页自动提取、一键提取、右键加入 | 主力 |
| Common Crawl | 批量获取 Shopify / Shoplazza / Shopline 店铺子域名 | 开 |
| 证书透明日志 | 新开的 Shoplazza / Shopline 店铺 | 开 |
| 外链扩散 | 高分或华人站点的外部链接 | 开 |
| 搜索引擎 | 抓取 DuckDuckGo / Bing 结果页，**违反其使用条款**，遇验证码即停 | 关 |
| 导入 | 后台粘贴或上传 CSV，或命令行导入 | — |

## 浏览器插件

推荐从前台 **浏览器插件** 页下载：压缩包已预置服务器地址和个人令牌。解压后在 Chrome 打开
`chrome://extensions` → 开启“开发者模式” → “加载已解压的扩展程序” → 选择解压出的文件夹。

也可以直接加载仓库中的 `extension/` 目录，再在插件设置页填写服务器地址和个人令牌
（令牌在前台 **浏览器插件** 页生成）。

## 命令行

```bash
python -m scout start                      # 网站 + 自动采集
python -m scout serve | run                # 只网站 / 只采集
python -m scout create-user lily           # 创建成员（会提示输入密码）；--admin 创建管理员
python -m scout crawl example.com          # 调试：采集单站并打印结果，不写库
python -m scout process example.com        # 单站采集 + 打分并写库
python -m scout add a.com b.com            # 加入采集队列
python -m scout import-csv list.csv --column url
python -m scout discover commoncrawl       # 手动运行一次渠道
python -m scout export leads.xlsx --min-score 60 --chinese-type 在美华人
python -m pytest -q                        # 测试
```

## 数据库升级

启动时会自动创建新表、补齐新增的列，已有数据保留。只新增不修改，删除或改名列需要手动迁移。

## 合规说明

- 默认遵守 robots.txt，单站点请求间隔 1.5 秒；只采集公开页面和公开接口；不登录、不绕过验证码
- 插件只读取用户正在浏览的页面，不自动翻页、不自动点击
- 采集到的是商家公开的商务联系方式；批量发送开发信时需遵守 CAN-SPAM 等法规（真实发件人信息、提供退订方式）
- 搜索引擎渠道默认关闭，开启前请自行评估风险
