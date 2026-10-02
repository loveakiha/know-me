# Schema v0

三个结构是全部数据模型。字段名即文档。

## observation（证据，只追加，C1）

存 `data/observations/YYYY-MM-DD/{agent}.jsonl`，一行一条。

```json
{
  "id": "obs_20261002_abc12345",
  "agent": "hermes",
  "observed_at": "2026-10-02T09:06:00Z",
  "conv_ref": "hermes:20261002_142649_111163",
  "summary": "检查并更新 llama.cpp 版本",
  "evidence": ["帮我看看llama.cpp是否最新", "怎么给ud-q4加MTP"],
  "topics": ["llama.cpp", "quantization"]
}
```

- `id`：`obs_<日期><hash>`，日期参与置信的"跨天"计算。
- **只追加，不回头改。** 发现判断错了，写新 observation / fact / review，不覆盖这一条。

## fact（候选→确认，唯一事实记录）

存 `data/facts/facts.jsonl`，一行一条，按 `id` 去重。

```json
{
  "id": "fact_<sha1前12位>",
  "topic_key": "ai:llama_cpp",
  "category": "current_activity",
  "subject": "user",
  "predicate": "currently_researching",
  "object": "local_ai",
  "statement": "用户近期持续研究本地 AI / llama.cpp 量化",
  "evidence_type": "inferred",
  "confidence": 3,
  "status": "candidate",
  "first_observed_at": "2026-10-02T09:06:00Z",
  "last_observed_at": "2026-10-02T09:06:00Z",
  "obs_dates": ["20261002"],
  "evidence_count": 2,
  "evidence": ["帮我看看llama.cpp是否最新", "怎么给ud-q4加MTP"],
  "evidence_ids": ["obs_20261002_abc12345"],
  "source_agents": ["hermes"],
  "valid_from": null,
  "valid_to": null,
  "created_at": "2026-10-02T09:06:00Z",
  "updated_at": "2026-10-02T09:06:00Z",
  "decided_at": null,
  "user_note": null
}
```

- **唯一性 = `category+subject+predicate+object`**（C2）。`topic_key` 只用于"找相关"，不是去重键。
- `id = sha1(唯一性)` 前 12 位。被否决后再次观察，生成 `_v2` 新 id，不翻案（C4）。
- 更新 = 证据累积，不覆盖（C3）：`evidence_count` 增、`source_agents` 增、`last_observed_at` 刷、`confidence` 重算。
- `evidence_type`：`asserted`(用户明说) / `observed`(观察到行为) / `inferred`(推断)，取最强。三者绝不混成一个事实（C6）。
- `confidence`（1–5）由规则算，模型不输出：
  - 基础分 = asserted 3 / observed 2 / inferred 1
  - 证据 ≥2 条 +1；≥2 个来源 agent +1；跨 ≥2 天 +1；封顶 5，下限 1。
- `status`：`candidate` / `confirmed` / `rejected` / `stale` / `superseded`。

## review（人工确认，artifact 即数据）

存 `data/reviews/YYYY-MM-DD.md`。不是 checkbox 交互，是持久化文件；回复语法解析于 `pm apply`。

```markdown
# 记忆确认 2026-10-02
- [ ] **R20261002-001** [建议✅] — 用户近期持续研究本地 AI / llama.cpp 量化
  `fact_abc123def456` · ai:llama_cpp · current_activity · 置信3/5 · inferred
  · 证据：帮我看看llama.cpp是否最新
  ↳ 已有 `fact_…` [rejected]：…；否决理由:…
```

回复（每行一条）：

```text
R001 对
R002 错,只是偶尔查资料
R003 改:用户近期对《2077》有兴趣
```
