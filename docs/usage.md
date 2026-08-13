# 使用与运维

## 每日自动推送

依赖 **WorkBuddy 自动化**（automation），每天早上定时执行：

```
任务名：公众号每日论文推送
触发：每天 07:30
操作：python daily.py
工作目录：A:\workbuddy项目\推送公众号论文\scripts
```

## 手动执行

```bash
cd "A:\workbuddy项目\推送公众号论文\scripts"
python daily.py
```

参数（可选）：
- `--date 2026-08-13`：指定日期抓取（默认今天）
- `--dry-run`：只抓取不发送不写本地
- `--no-email`：只写本地不发邮件
- `--no-local`：只发邮件不写本地
- `--force`：强制重跑（即使当天已推送，覆盖当天文件夹）

示例：
```bash
python daily.py --date 2026-08-12
python daily.py --dry-run
python daily.py --force
```

## 开机即推（可选）

脚本带**幂等判断**：当天已推过就自动跳过，多次触发也只推一次。

- 每天早上 07:30 的定时任务负责「正常定时推」
- 开机自启动脚本负责「开机晚于 07:30 时立即推」
- 两者叠加，最终效果：开机早于 07:30 → 07:30 推；开机晚于 07:30 → 开机即推

安装/卸载开机自启动：
```bash
cd "A:\workbuddy项目\推送公众号论文\scripts"
python install_startup.py           # 安装（开机登录后自动静默跑 daily.py）
python install_startup.py --remove  # 卸载
```

> 前提：Docker Desktop 需开启「开机自启」（Settings → General → Start Docker Desktop when you sign in），容器已配置 `restart: unless-stopped`。

## Web 管理系统

桌面双击「公众号论文观察台」快捷方式（`C:\Users\PC\Desktop\公众号论文观察台.lnk`），或手动：

```bash
cd "A:\workbuddy项目\推送公众号论文\web"
python paper_observatory.py --port 8031
```

浏览器打开 http://127.0.0.1:8031：

- **全局总览**：公众号数 / 累计文章 / 归档天数 / 最近归档
- **公众号归档**：点侧边栏或卡片进入，按日期倒序翻页浏览历史推文
- **文章抽屉**：点文章弹出详情（标题、公众号、时间、摘要、原文链接）
- **现场抓取**：右上角按钮，强制重抓当天文章（`daily.py --force`），抓完自动刷新

> 现场抓取与每日推送共用「按日期分文件夹」的存档，天然去重，不会重复推送历史文章。

## 添加新公众号

1. 在 WeWe RSS 后台 **公众号源 → 添加+**
2. 粘贴新公众号的任意一篇文章链接
3. 等待 1-2 分钟，WeWe RSS 自动抓取历史 + 最新
4. 获取新公众号的 feed_id：
   ```bash
   curl http://localhost:4000/feeds/all.json | python -m json.tool
   ```
5. 在 `config/config.json` 中加入新公众号
6. 手动测试一次：`python daily.py --dry-run`

## 升级 WeWe RSS

```bash
cd "A:\workbuddy项目\推送公众号论文\wewe-rss"
git pull
docker compose -f docker-compose.sqlite.yml pull
docker compose -f docker-compose.sqlite.yml up -d
```

升级前**先备份数据**：
```bash
cp -r data data.bak.$(date +%Y%m%d)
```

## 数据备份

WeWe RSS 数据库在 `wewe-rss/data/wewe-rss.db`，本地推送结果在 `A:\研零课题\研零课题资料\每日推送\每日论文推送\`。

建议每周手动备份一次 `wewe-rss.db`。

## 微信读书账号被封（"今日小黑屋"）

- 表现：抓取全部失败 / 账号状态显示"今日小黑屋"
- 处理：等 24 小时自动解封，或重启容器清除记录：
  ```bash
  docker compose -f docker-compose.sqlite.yml restart
  ```
- 预防：减少每日新增订阅源（≤ 3 个），避免短时间高频抓取