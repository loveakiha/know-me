# know me

跨平台、跨 Agent 的个人记忆系统（v0）。核心思想一句话：

> **多个 Agent 共同观察一个人，但没有任何 Agent 能单方面定义这个人是谁——最终解释权在用户。**

四个阶段：`Observation(证据) → Candidate Fact(候选) → Human Review(人工确认) → Confirmed Fact(已确认)`。

- 自动提炼可以积极，自动确认必须保守。
- 唯一事实源是 `data/facts/facts.jsonl` + `data/reviews/`；`data/user_model.md` 只是导出视图，可删可重建。
- 原始对话**不进**仓库；只共享已经蒸馏的 observation / fact / review。

## 快速开始

```bash
python pm.py import hermes          # Hermes state.db -> observations
python pm.py add-facts facts.json   # 候选事实 -> 归并(证据累积/否决不翻案)
python pm.py review                 # 生成待确认列表 reviews/日期.md
python pm.py apply "R001 对 / R002 错,理由"   # 人工确认
python pm.py export                 # -> data/user_model.md
python pm.py sync                   # git 提交
```

## 首次初始化（回填历史 + 全量确认）

第一次用，先回填全部历史对话并一次性确认（解决冷启动）：

```bash
python pm.py import hermes --since 2026-09-01   # 回填全部历史（按实际日期分文件）
# 让 agent 按 prompts/extract.md 提炼全部 observations → facts.json
python pm.py add-facts facts.json
python pm.py review --all                        # 全量待确认（首次）
python pm.py apply "R001 对 / R002 错..."         # 一次性确认
python pm.py export
```

之后每天只跑增量：`pm import hermes`（默认今天）+ `pm review`（只推新候选 + 同主题冲突）。

## 谁写谁读

| 参与者 | 能力 | 分工 |
|---|---|---|
| Hermes（本地 agent） | cron + state.db + git | 唯一自动观察者/归并者 |
| ChatGPT/DeepSeek（web AI） | 无本地写入 | 按 `prompts/list_memory.md` 吐记忆 → 粘进来；收 user_model.md 回灌 |
| 未来本地 agent（Claude/Cursor） | MCP | 通过 MCP 读写（v1） |
| 用户 | — | 确认/修正（唯一真相源） |

llama.cpp 不是参与者（无状态推理引擎，记忆由调用它的 agent 负责）。

## 目录

```
pm.py
schema/          # 三个数据结构定义
prompts/         # 列记忆 / 提炼 模板
data/            # 你的私有数据（仓库保持 private）
  observations/  facts/  reviews/  user_model.md  cache.db
```

`cache.db` 是纯索引，`pm rebuild` 可随时重建，已 gitignore。

## 八条约束（实现细节见 pm.py 顶部注释）

1 Observation 只追加；2 唯一性靠三元组不靠 topic_key；3 更新=证据累积不覆盖；4 rejected 不可翻案；5 user_model.md 仅导出视图；6 asserted/observed/inferred 分离、置信规则算；7 聊天文本≠指令；8 data/ 可重建。
