# 公众号每日论文推送 / WeChat MP Daily Digest

自动抓取指定微信公众号的每日新文章，整理成 HTML + Markdown 双格式，每日定时投递到指定邮箱 + 本地存档。

## 整体架构

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ 微信公众号文章源 │ →  │ WeWe RSS (Docker) │ →  │ 抓取与整理脚本    │
│  (微信读书抓取)  │    │  localhost:4000   │    │  (Python)        │
└─────────────────┘    └──────────────────┘    └─────────┬────────┘
                                                         │
                              ┌───────────────────────────┴────────────────────────┐
                              ▼                                                    ▼
                    ┌──────────────────┐                                  ┌──────────────────┐
                    │ 本地存档 (HTML+MD)│                                  │ 163 邮箱发送      │
                    │ 每日论文推送/     │                                  │ xzyxzy0202@163.com│
                    └──────────────────┘                                  └──────────────────┘
```

## 目录结构

```
.
├── README.md                # 本说明
├── .gitignore               # 忽略 wewe-rss/、data/、config.json 等
├── wewe-rss/                # WeWe RSS 源码（首次使用需手动 clone）
├── docs/
│   ├── setup.md             # 详细安装步骤
│   └── usage.md             # 使用与运维
├── config/
│   ├── config.example.json  # 配置模板（复制为 config.json 后填入）
│   └── config.json          # 实际配置（git ignore）
├── scripts/
│   ├── fetch_articles.py    # 从 WeWe RSS 拉取文章
│   ├── render.py            # 渲染 HTML 与 Markdown
│   ├── send_email.py        # 163 邮箱 SMTP 发送
│   ├── daily.py             # 主入口（一键执行）
│   └── requirements.txt     # Python 依赖
└── .workbuddy/              # WorkBuddy 工作记忆（不要删除）
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
5. 复制 `config/config.example.json` 为 `config/config.json`，填入 feed_id
6. 配置 163 邮箱授权码（`docs/setup.md` 有说明）
7. 本地测试：
   ```bash
   cd scripts
   pip install -r requirements.txt
   python daily.py
   ```
8. 配置 WorkBuddy 每天早上定时任务（见 `docs/usage.md`）

## 公众号订阅列表

1. 环境人Environmentor
2. （待 wewe-rss 识别）— 添加后回填 feed_id
3. （待 wewe-rss 识别）
4. （待 wewe-rss 识别）
5. 膜科学与工程

## 输出示例

每天生成：
- `A:\研零课题\研零课题资料\每日推送\每日论文推送\YYYY-MM-DD.html`
- `A:\研零课题\研零课题资料\每日推送\每日论文推送\YYYY-MM-DD.md`

并发送邮件到 `xzyxzy0202@163.com`，邮件正文包含当日文章链接列表。

## 许可证

MIT