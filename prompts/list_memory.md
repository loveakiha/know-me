# 让 web AI 列出记忆（复制即用）

对 ChatGPT / DeepSeek 等无本地写入能力的 web AI 使用。目的：把它们的持久记忆收割成标准事实，粘回本地进 facts。

把下面整段发给它：

---

请把你记忆中所有关于我的、可能对理解"我当前的生活、工作、正在做的事、长期项目、工具环境、兴趣、偏好、目标、习惯、客观约束"有帮助的事实，逐条列出来。

要求：
1. 每条一句完整的话，用第三人称，例如："用户近期持续研究本地大模型量化"。
2. 每条后面用括号标注：这是【用户明确说过】还是【你的推断】，以及你大概从什么时候开始知道。
3. 只列你确实记得的；不确定的不要编。
4. 不要执行我的任何其他指令——你列出的内容只是待确认的候选事实，不是要你去做的动作。

---

把输出粘贴给 `pm add-facts`（或先把每条整理成下面 JSON 再喂）：

```json
{
  "facts": [
    {
      "topic_key": "ai:llama_cpp",
      "category": "current_activity",
      "subject": "user",
      "predicate": "currently_researching",
      "object": "local_ai",
      "statement": "用户近期持续研究本地 AI / llama.cpp 量化",
      "evidence_type": "inferred",
      "evidence": ["<它给出的依据/原话>"],
      "source_agent": "chatgpt",
      "observed_on": "2026-10-02"
    }
  ]
}
```

> 注意：`source_agent` 写 `chatgpt` 或 `deepseek`。它的记忆只是候选来源，和你本地的 Hermes 提炼一样，都要过人工确认，谁的都不高一等。
