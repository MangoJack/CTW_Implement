---
name: ctw_fetch
description: CTW Web 资源获取 — 从 URL 抓取内容并返回结构化的 SourceInput
version: "1.0"
---

# CTW Fetch

CTW 管线前置阶段：获取网络资源内容。

## 触发

当用户提供 URL 且需要获取远程内容以进行分类/摄入时触发。作为管线的第一个实际步骤（在分类之前）。

## 支持的资源类型

| 类型 ID | 来源 | 获取策略 |
|---------|------|---------|
| `article` | 通用网页、V2EX、知乎、Medium、Reddit 等 | HTTP GET → HTML 解析（title, meta, OG tags, body text） |
| `repo` | GitHub | GitHub API → name, description, README |
| `pdf` | arXiv | arXiv API → title, authors, abstract |
| `video` | YouTube, Bilibili | YouTube oEmbed / Bilibili 页面元数据 |
| `tool` | npm, PyPI, crates.io | 对应 Registry API → 包元数据 |
| `model` | HuggingFace | HF API → model card |

## 流程

```
URL
  │
  ▼
┌──────────────────┐
│  推断 source_type │ ← 域名 + 路径启发式
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  分派到类型获取器  │ ← article / repo / pdf / video / tool / model
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  HTTP GET / API   │ ← 15s 超时, User-Agent 设置
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  提取结构化内容    │ ← title, description, content, source_type
└────────┬─────────┘
         │
         ▼
    SourceInput
      ├── url
      ├── title
      ├── description
      ├── content
      ├── source_type
      └── raw_file_path (自动生成)
```

## 使用

```python
from ctw_fetch.fetcher import ResourceFetcher

fetcher = ResourceFetcher()

# 自动检测类型
source = fetcher.fetch("https://github.com/user/repo")
# source.title == "user/repo"
# source.source_type == "repo"
# source.content contains README

# 手动指定类型
source = fetcher.fetch("https://example.com/article", source_type="article")

# 批量获取
sources = fetcher.fetch_batch(["https://url1", "https://url2"])
```

## 依赖

- `lib/ctw_types.py` — SourceInput 类型定义
- Python stdlib: `urllib.request`, `html.parser`, `re`, `json`
- 无额外第三方依赖

## 错误处理

获取失败时不抛异常，返回 SourceInput 并尽可能填充已获取的字段。
空字段表示获取失败，由后续阶段判断是否需要人工介入。
