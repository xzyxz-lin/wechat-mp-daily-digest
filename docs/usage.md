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

示例：
```bash
python daily.py --date 2026-08-12
python daily.py --dry-run
```

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