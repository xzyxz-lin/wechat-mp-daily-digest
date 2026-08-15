# 期刊抓取连通性修复说明

## 问题

原有 ScienceDirect 配置使用期刊网页附带的 RSS 路径，在当前网络环境中返回 403。ACS 与 MDPI 的 RSS 端点也返回 403，且 ACS 已迁移平台，旧期刊代码或旧 RSS 路径不再可靠。

## 修复

- Water Research、Journal of Membrane Science、Desalination、Separation and Purification Technology、Journal of Water Process Engineering 改为 ScienceDirect 官方 publication RSS，使用期刊 ISSN 作为稳定标识。
- Environmental Science & Technology、ACS ES&T Water、Membranes 使用 Crossref 的公开 DOI 元数据接口作为备用源。每个此类来源都在 `config/journals.json` 中声明 `source_type: "crossref"` 与 ISSN。
- `scripts/fetch_journals.py` 新增 Crossref 抓取器，统一输出与 RSS 相同的文章字段、按近 7 天窗口过滤，并沿用已有 URL 去重和标题翻译流程。
- ScienceDirect 官方 RSS 将发布日期置于摘要中的 `Publication date:` 字段，抓取器现已提取并解析该日期，避免将整批文章误判为“无日期”。

## 验收方式

运行日常抓取时，15 个来源均有请求路径：12 个为原生 RSS/Atom，3 个为 Crossref 元数据。Crossref 项的文章链接为 DOI 链接或 Crossref 提供的落地页链接。

## 说明

Crossref 是 DOI 注册机构提供的公开元数据服务，不代替全文访问；它用于确保 ACS 与 MDPI 在 RSS 被封锁时仍能稳定发现新论文。
