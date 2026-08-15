# 期刊论文接入说明

> 更新：2026-08-14
> 状态：已接入（直连 RSS）

## 一、目标

在「论文观察台」中按分类管理两类信息源：

- **公众号**（已有）：微信读书订阅，经 WeWe RSS 抓取。
- **期刊**（本次新增）：各出版商的 RSS/Atom feed，直连抓取。

期刊与公众号写入**同一套本地存档**（`每日论文推送/YYYY.M.D/articles.json`），每篇文章多一个 `category` 字段（`公众号` / `期刊`），观察台后端按分类聚合、前端按分类切换。

## 二、为什么期刊走「直连 RSS」而不是 WeWe RSS

最初方案设想让 WeWe RSS 订阅期刊 RSS（复用现有架构）。实测后改为**独立直连 RSS 抓取模块**，原因：

1. **WeWe RSS 的订阅接口是私有 tRPC**（`feed.add` / `platform.getMpInfo`），无公开文档，需逆向鉴权与批处理格式，脆弱易碎。
2. **网络出口相同**：WeWe RSS 跑在本机 Docker 内，与本机共享同一网络出口，出版商对 RSS 的拦截对它同样生效，绕不过。
3. **可控性**：直连抓取模块（`scripts/fetch_journals.py`）完全自管，解析 RSS 2.0 / RSS 1.0(RDF) / Atom 三种格式，单源失败不影响其他源。

效果与「统一数据源」完全一致——期刊和公众号都在观察台里按分类切换。

## 三、期刊清单

配置在 `config/journals.json`（**可提交、无敏感信息**，与含密码的 `config.json` 分离）。

当前包含：

> 2026-08-15 已完成连通性修复：ScienceDirect 期刊改用官方 `rss.sciencedirect.com/publication/science/{ISSN}` 地址；ACS 两刊和 MDPI《Membranes》在 RSS 返回 403 时，改用 Crossref 公开 DOI 元数据。配置内以 `source_type: "crossref"` 明确标识，其他来源仍走原生 RSS/Atom。

| 期刊 | 出版商 | 本环境状态 |
|------|--------|-----------|
| Journal of Membrane Science | ScienceDirect | ⚠️ 被拦截(403) |
| Water Research | ScienceDirect | ⚠️ 被拦截(403) |
| Environmental Science & Technology | ACS | ⚠️ 被拦截(000/超时) |
| Nature Water | Nature | ✅ 用 Nature 水领域主题 RSS |
| Nature Communications | Nature | ✅ 稳定可抓 |
| Nature | Nature | ✅ 稳定可抓(Atom) |
| Desalination | ScienceDirect | ⚠️ 被拦截(403) |
| Separation and Purification Technology | ScienceDirect | ⚠️ 被拦截(403) |
| npj Clean Water | Nature | ⚠️ 期刊独立 RSS 地址待核实 |
| ACS ES&T Water | ACS | ⚠️ 被拦截/地址待核实 |
| Journal of Water Process Engineering | ScienceDirect | ⚠️ 被拦截(403) |
| Membranes | MDPI | ⚠️ 被拦截(403) |
| arXiv·膜与分离预印本 | arXiv | ✅ 稳定可抓 |
| arXiv·物理化学预印本 | arXiv | ✅ 稳定可抓 |
| arXiv·材料科学预印本 | arXiv | ✅ 稳定可抓 |

### 出版商限制（重要）

本机网络出口下，**ScienceDirect 全系、ACS 全系、MDPI** 的 RSS 被出版商直接拦截（403 / 连接超时）。
这是网络环境限制，不是代码问题。这些期刊在观察台「期刊」分组里照常列出，只是当前文章数为 0，并显示「出版商限制」提示。

**解锁方式**（任选其一，改完即自动生效）：

- 在**可访问该出版商的网络**环境运行（如校园网、机构代理）；
- 或在 `config.json` 增加 `"journals_proxy": "http://代理地址:端口"`，`fetch_journals.py` 会为所有源走该代理。（注意：`config.json` 含密码、已被 gitignore，代理地址也别提交。）

## 四、抓取模块

`scripts/fetch_journals.py`：

- 读取 `config/journals.json`，逐个抓取 RSS；
- 兼容 RSS 2.0 / RSS 1.0(RDF) / Atom（命名空间无关解析）；
- 按发布日期（北京时间）过滤出当天文章；
- 单源失败（拦截/超时/格式异常）仅告警并跳过，不影响其他源；
- 输出字段与公众号一致，多 `category=期刊`。

被 `scripts/daily.py` 在「现场抓取 / 自定义抓取」时统一调用，与公众号文章合并后写入同一存档。

## 五、观察台 UI

- 左侧导航：文件总控 / 论文总控 / 公众号(分组) / 期刊(分组) / 基金(占位)；
- **文件总控**：公众号、期刊、基金三类信息源的状态卡片；
- **论文总控**：聚合所有来源最新论文，可按「全部 / 公众号 / 期刊」筛选；
- 点击「期刊」分组下任一期刊 → 按日期回溯该期刊文章；
- 每篇文章带分类徽章（公众号=绿 / 期刊=铜橙）。

## 六、基金（规划中）

左侧「基金」节点为占位，计划后续纳入：

- 基金申报通知（国自然等指南、截止日期）；
- 结题 / 成熟项目（跟踪产出与方向）。

本期仅占位，未接入真实数据源。
