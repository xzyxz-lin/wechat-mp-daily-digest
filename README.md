# 每日论文推送 / Paper Daily Digest

自动抓取指定**微信公众号**与**期刊 RSS**的每日新论文，整理成 HTML + Markdown 双格式，每日定时投递到指定邮箱 + 本地存档，并提供本地 Web 管理系统（**论文观察台**）进行总控与历史检索。

## 整体架构

```
┌─────────────────┐    ┌──────────────────┐
│ 微信公众号文章源 │ →  │ WeWe RSS (Docker) │ ─┐
│  (微信读书抓取)  │    │  localhost:4000   │  │   ┌──────────────────┐
└─────────────────┘    └──────────────────┘  ├→ │ 抓取与整理脚本    │
┌─────────────────┐                          │   │  (Python)        │
│ 期刊 RSS 源      │ ──── 直连抓取 ────────────┘   └─────────┬────────┘
│ Nature/arXiv 等  │                                        │
└─────────────────┘                                         │
              ┌──────────────────────┬───────────────────────┴─────────┐
              ▼                      ▼                                 ▼
   ┌──────────────────┐   ┌──────────────────┐              ┌──────────────────┐
   │ 本地存档(HTML+MD) │   │ 163 邮箱发送      │              │ Web 管理系统      │
   │ 每日论文推送/     │   │ xzyxzy0202@163   │              │ 论文观察台         │
   │ YYYY.M.D/        │   │                  │              │ localhost:8032    │
   └──────────────────┘   └──────────────────┘              └──────────────────┘
```

## 目录结构

```
.
├── README.md                  # 本说明
├── .gitignore                 # 忽略 wewe-rss/、data/、config.json 等
├── wewe-rss/                  # WeWe RSS 源码（首次使用需手动 clone）
├── docs/
│   ├── setup.md               # 详细安装步骤
│   ├── usage.md               # 使用与运维（含 Web 系统、开机自启）
│   ├── journals.md            # 期刊源接入说明（RSS 清单、限制、扩展方式）
│   └── docker-troubleshooting.md # Docker 自启排障记录
├── config/
│   ├── config.example.json    # 配置模板（复制为 config.json 后填入）
│   ├── config.json            # 实际配置（git ignore，含邮箱授权码）
│   └── journals.json          # 期刊 RSS 清单（可提交，无敏感信息）
├── scripts/
│   ├── fetch_articles.py      # 从 WeWe RSS 拉取公众号文章（带重试）
│   ├── fetch_journals.py      # 期刊 RSS 直连抓取（RSS2.0/RSS1.0/Atom）
│   ├── render.py              # 渲染 HTML 与 Markdown
│   ├── send_email.py          # 163 邮箱 SMTP 发送
│   ├── daily.py               # 主入口（幂等 + --force + 按日期分文件夹）
│   ├── install_startup.py     # 安装/卸载开机自启动脚本
│   └── requirements.txt       # Python 依赖
├── web/
│   ├── paper_observatory.py   # Web 后端（纯标准库，端口 8032）
│   ├── paper_observatory.html # Web 前端页面
│   ├── paper_observatory.css  # 前端样式（墨色+纸面+氧化绿+铜橙）
│   ├── paper_observatory.js   # 前端交互
│   ├── start_web.cmd          # 启动入口（cmd）
│   ├── start_web.ps1          # 启动脚本（健康检查 + 开浏览器）
│   └── install_shortcut.py    # 创建桌面快捷方式
└── .workbuddy/                # WorkBuddy 工作记忆（不要删除）
```

## 快速开始

1. 安装 Docker Desktop（详细步骤见 `docs/setup.md`）
2. 启动 WeWe RSS：
   ```bash
   cd wewe-rss
   docker-compose -f docker-compose.sqlite.yml up -d
   ```
3. 浏览器打开 http://localhost:4000 → 账号管理 → 微信扫码登录微信读书
4. 公众号源 → 添加公众号（粘贴任意一篇文章链接）
5. 复制 `config/config.example.json` 为 `config/config.json`，填入公众号白名单 + 邮箱授权码
6. 本地测试：
   ```bash
   cd scripts
   pip install -r requirements.txt
   python daily.py
   ```
7. 配置每日定时推送 + 开机即推（见 `docs/usage.md`）

## 订阅源

### 公众号（5 个，走 WeWe RSS）

| # | 公众号 |
|---|--------|
| 1 | 环境人Environmentor |
| 2 | Environmental Advances |
| 3 | 膜法笔记 |
| 4 | 环境工程与科学 |
| 5 | 膜科学与工程 |

### 期刊 / 预印本（15 个源，直连 RSS）

围绕**膜分离 · 水处理 · 环境工程**方向，清单见 `config/journals.json`，详细说明见 `docs/journals.md`。

| 分组 | 源 |
|------|-----|
| 顶刊 | Nature、Nature Communications、Nature Water（水主题） |
| 膜与分离 | Journal of Membrane Science、Desalination、Separation and Purification Technology、Membranes |
| 水与环境 | Water Research、Environmental Science & Technology、ACS ES&T Water、npj Clean Water、Journal of Water Process Engineering |
| 预印本 | arXiv（cond-mat.soft / physics.chem-ph / cond-mat.mtrl-sci） |

> ⚠️ 本机网络出口下 **ScienceDirect（JMS/Desalination/SPT/JWPE/WR）、ACS（ES&T/ES&T Water）、MDPI（Membranes）** 的 RSS 会被出版商拦截（403/超时），已在配置中标注。Nature 系与 arXiv 稳定可抓。在可访问的网络环境或在 `config.json` 中配置 `journals_proxy` 后自动解锁。

## 输出与推送

每天抓取后生成（按日期分文件夹）：

```
每日论文推送/
  2026.8.13/
    2026.8.13.html      # 排版好的 HTML
    2026.8.13.md        # Markdown
    articles.json       # 结构化数据（供 Web 检索）
  2026.8.14/
    ...
```

同时发送邮件到 `xzyxzy0202@163.com`，邮件正文含当日文章链接列表。

## Web 管理系统（论文观察台）

桌面双击「论文观察台」快捷方式，或手动启动：

```bash
cd web
python paper_observatory.py --port 8032
```

浏览器打开 http://127.0.0.1:8032。左侧导航分为四层：

| 导航 | 说明 |
|------|------|
| **文件总控** | 首屏。三张分类卡片（公众号 / 期刊 / 基金），显示各类源数、论文数、覆盖天数 |
| **论文总控** | 全部论文聚合流，可按「全部 / 公众号 / 期刊」筛选，翻页检索 |
| **公众号** | 可折叠分组，展开后是 5 个公众号，点进去看该号的历史归档 |
| **期刊** | 可折叠分组，展开后是各期刊/预印本源 |
| **基金** | UI 占位，后续接入基金项目信息 |

其他：点文章 → 抽屉显示详情 + 分类 + 原文链接；右上角「现场抓取」→ 强制重抓当天（按日期去重，不重复）。

## 许可证

MIT
