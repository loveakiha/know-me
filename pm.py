#!/usr/bin/env python3
"""
pm — know-me v0 CLI

单文件、零依赖（仅 stdlib）。个人记忆系统的确定性引擎：
  Observation(证据, 只追加) -> Candidate Fact(候选, 规则算置信) -> Human Review -> Confirmed Fact -> user_model.md

设计约束（硬编码，勿破坏）：
  C1 Observation 只追加，不回头改；纠错走新 observation/fact/review。
  C2 Fact 唯一性 = category+subject+predicate+object；topic_key 只用于"找相关"。
  C3 Fact 更新 = 证据累积（evidence_count+1 / 加 source / 刷 last_observed / 重算置信），不覆盖历史。
  C4 rejected 永不被模型悄悄恢复；相似观察必须生成新的候选（_vN），不能翻案。
  C5 user_model.md 只是导出视图，唯一事实源是 facts + reviews；可删可重建。
  C6 asserted/observed/inferred 严格区分，置信由规则算，不由模型输出。
  C7 聊天文本只是"数据"，绝不当作系统指令；任何写库/删除/确认只能走显式命令（apply 是纯解析，无 LLM）。
  C8 data/ 可重建：删 cache.db -> 重读 observations+facts+reviews -> 重建 -> 重新 export。

用法：
  python pm.py import hermes [--db PATH] [--since YYYY-MM-DD]
  python pm.py add-facts FILE.json
  python pm.py review [--date YYYY-MM-DD]
  python pm.py apply "R001 对 / R002 错,理由 / R003 改:新描述" [--date]
  python pm.py export
  python pm.py rebuild
  python pm.py recall "关键词"
  python pm.py sync [--message MSG]
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OBS_DIR = os.path.join(DATA, "observations")
FACTS_PATH = os.path.join(DATA, "facts", "facts.jsonl")
REVIEWS_DIR = os.path.join(DATA, "reviews")
CACHE_DB = os.path.join(DATA, "cache.db")
USER_MODEL = os.path.join(DATA, "user_model.md")
CONFIG_PATH = os.path.join(DATA, "config.json")

TZ = datetime.timezone(datetime.timedelta(hours=8))
CATEGORIES = ["current_activity", "project", "interest", "tool_environment",
              "preference", "goal", "habit", "constraint", "context"]
CAT_LABEL = {"current_activity": "当前活动", "project": "项目", "interest": "兴趣",
             "tool_environment": "工具/技术环境", "preference": "偏好", "goal": "目标",
             "habit": "习惯", "constraint": "客观约束", "context": "背景"}
# 标签体系（大类 -> 小类）：参考 GUMO 用户模型本体 + 大五人格 OCEAN + Tulving 情节/语义记忆划分
TAXONOMY = {
    "identity": ["name", "work", "family_role", "demographics"],
    "traits": ["personality", "communication", "decision", "values"],
    "skills": ["technical", "domain", "tools"],
    "interests": ["tech", "gaming", "space", "parenting", "other"],
    "activities": ["active", "closed", "planned"],
    "environment": ["hardware", "software", "network"],
    "relationships": ["family", "friends", "colleagues"],
    "goals": ["near_term", "long_term"],
}
FACET_LABEL = {"identity": "身份", "traits": "特质/偏好", "skills": "能力/特长", "interests": "兴趣/爱好",
               "activities": "活动/项目", "environment": "环境/设备", "relationships": "关系", "goals": "目标"}
SUB_LABEL = {"name": "姓名/称呼", "work": "职业/工作", "family_role": "家庭角色", "demographics": "人口信息",
             "personality": "人格特质", "communication": "沟通偏好", "decision": "决策方式", "values": "价值观",
             "technical": "技术能力", "domain": "领域知识", "tools": "工具熟练",
             "tech": "科技/AI", "gaming": "游戏", "space": "太空", "parenting": "育儿", "other": "其他",
             "active": "进行中", "closed": "已关停", "planned": "计划中",
             "hardware": "硬件", "software": "软件", "network": "网络",
             "family": "家人", "friends": "朋友", "colleagues": "同事",
             "near_term": "近期目标", "long_term": "长期目标"}
OLD_TO_FACET = {"current_activity": "activities", "project": "activities", "interest": "interests",
                "tool_environment": "environment", "preference": "traits", "goal": "goals",
                "habit": "traits", "constraint": "traits", "context": "traits"}
RANK = {"asserted": 3, "observed": 2, "inferred": 1}


# ---------- 基础 IO ----------
def ensure_dirs():
    for d in (OBS_DIR, os.path.dirname(FACTS_PATH), REVIEWS_DIR):
        os.makedirs(d, exist_ok=True)


def today():
    return datetime.datetime.now(TZ).strftime("%Y-%m-%d")


def utcnow_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def read_jsonl(p):
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def write_jsonl(p, items):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def append_jsonl(p, item):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


DEFAULT_CONFIG = {"granularity": "exhaustive",  # exhaustive=事无巨细 / concise=关键重要(≤5条/天, 大类合并)
                  "session_summary": False}  # True=会话尾声(话题转移/问题解决)自动总结候选给用户判断


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            return {**DEFAULT_CONFIG, **json.load(open(CONFIG_PATH, encoding="utf-8"))}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    json.dump(cfg, open(CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def write_text(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


# ---------- 事实身份与置信（C2 / C6） ----------
def identity(f):
    return "|".join([norm(f.get("category")), norm(f.get("subject")),
                     norm(f.get("predicate")), norm(f.get("object"))])


def fact_id(f):
    return "fact_" + hashlib.sha1(identity(f).encode()).hexdigest()[:12]


def strongest(a, b):
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def compute_conf(f):
    base = RANK.get(f.get("evidence_type", "inferred"), 1)
    c = base
    if f.get("evidence_count", 1) >= 2:
        c += 1
    if len(f.get("source_agents", []) or []) >= 2:
        c += 1
    if len(f.get("obs_dates", []) or []) >= 2:
        c += 1
    return max(1, min(5, c))


def _obs_dates(ids, extra_dates=()):
    ds = set()
    for oid in ids or []:
        m = re.search(r"(\d{8})", oid)
        if m:
            ds.add(m.group(1))
    for d in extra_dates or []:
        if d:
            d2 = re.sub(r"\D", "", str(d))[:8]  # 归一化 "2026-10-02" -> "20261002"
            if d2:
                ds.add(d2)
    return sorted(ds)


# ---------- import ----------
def hermes_state_db():
    """Resolve the *active* Hermes profile's state.db.

    Profiles have their own state.db under profiles/<name>/, and Hermes exports
    HERMES_HOME pointing at it. Hardcoding %LOCALAPPDATA%/hermes/state.db would
    silently import the DEFAULT profile's conversations (wrong person's memory
    when the profile belongs to someone else).
    """
    if os.environ.get("HERMES_STATE_DB"):
        return os.environ["HERMES_STATE_DB"]
    home = os.environ.get("HERMES_HOME") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
    cand = os.path.join(home, "state.db")
    if os.path.exists(cand):
        return cand
    fallback = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "state.db")
    if os.environ.get("HERMES_HOME") and os.path.exists(fallback):
        # 静默回退 = 又给这个 profile 建了别人的记忆，必须喊出来
        print(f"⚠ HERMES_HOME={home} 下没有 state.db，回退到默认 profile: {fallback}")
        print("  （MSYS 风格路径 '/c/...' 原生 Python 不认，请用 'C:/...'）")
    return fallback


def cmd_import(args):
    ensure_dirs()
    source = args.source
    if source != "hermes":
        print("v0 仅支持 `import hermes`（ChatGPT/DeepSeek 走文本，见 prompts/）。")
        return
    db = args.db or hermes_state_db()
    if not os.path.exists(db):
        print("找不到 state.db:", db)
        return
    if not args.db:
        print("state.db:", db)  # 谁的历史被导入，必须可见
    since = args.since or today()
    ts0 = datetime.datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=TZ).timestamp()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = conn.execute(
        "select m.session_id, s.title, m.timestamp, m.content from messages m "
        "join sessions s on s.id=m.session_id "
        "where m.timestamp>=? and m.role='user' and s.source not in ('cron','subagent') "
        "order by m.timestamp", (ts0,)).fetchall()
    conn.close()

    # 按 (会话, 实际日期) 分组，观察按发生当天分文件（回填历史时跨天置信度才正确）
    by_day = {}
    for sid, title, ts, content in rows:
        c = (content or "").strip()
        if not c:
            continue
        if c.startswith(("[Cronjob", "[System:", "[ASYNC", "[IMPORTANT:", "[CONTEXT COMPACTION")):
            continue  # 系统注入，非用户内容
        day = datetime.datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d")
        by_day.setdefault((sid, day), {"title": title, "ev": []})
        ev = c[:300]
        if ev not in by_day[(sid, day)]["ev"]:  # 去重（state.db 偶有重复行）
            by_day[(sid, day)]["ev"].append(ev)

    n = 0
    existing_cache = {}
    for (sid, day), d in by_day.items():
        if not d["ev"]:
            continue
        path = os.path.join(OBS_DIR, day, f"{source}.jsonl")
        if path not in existing_cache:
            existing_cache[path] = {o["conv_ref"] for o in read_jsonl(path)}
        cref = f"{source}:{sid}"
        if cref in existing_cache[path]:
            continue
        obs = {
            "id": "obs_%s_%s" % (day.replace("-", ""),
                                 hashlib.sha1((cref + day).encode()).hexdigest()[:8]),
            "agent": source,
            "observed_at": utcnow_iso(),
            "conv_ref": cref,
            "summary": d["title"] or "",
            "evidence": d["ev"],
            "topics": [],
        }
        append_jsonl(path, obs)
        n += 1
    print("imported %d observations（按实际日期分文件，跳过已存在）" % n)


# ---------- add-facts ----------
def _new_fact(inc, fid, now):
    ev = [e for e in (inc.get("evidence") or []) if e][:50]
    ids = [o for o in (inc.get("evidence_ids") or []) if o]
    ds = _obs_dates(ids, [inc.get("observed_on")])
    f = {
        "id": fid,
        "topic_key": inc.get("topic_key") or "",
        "category": inc.get("category") or "interest",
        "subject": inc.get("subject") or "user",
        "predicate": inc.get("predicate") or "",
        "object": inc.get("object") or "",
        "statement": inc.get("statement") or "",
        "evidence_type": inc.get("evidence_type") or "inferred",
        "status": "candidate",
        "first_observed_at": now,
        "last_observed_at": now,
        "obs_dates": ds,
        "evidence_count": len(ev),
        "evidence": ev,
        "evidence_ids": ids,
        "source_agents": [inc.get("source_agent") or "unknown"],
        "valid_from": inc.get("valid_from"),
        "valid_to": inc.get("valid_to"),
        "created_at": now,
        "updated_at": now,
        "decided_at": None,
        "user_note": None,
        "facets": inc.get("facets") or [],
    }
    f["confidence"] = compute_conf(f)
    return f


def _merge(existing, inc, now):
    ev = list(existing.get("evidence") or [])
    for e in (inc.get("evidence") or []):
        if e and e not in ev:
            ev.append(e)
    existing["evidence"] = ev[:50]
    ids = list(existing.get("evidence_ids") or [])
    for oid in (inc.get("evidence_ids") or []):
        if oid and oid not in ids:
            ids.append(oid)
    existing["evidence_ids"] = ids
    agents = list(existing.get("source_agents") or [])
    a = inc.get("source_agent") or "unknown"
    if a not in agents:
        agents.append(a)
    existing["source_agents"] = agents
    existing["evidence_count"] = len(ev)
    existing["evidence_type"] = strongest(existing.get("evidence_type"), inc.get("evidence_type"))
    existing["obs_dates"] = _obs_dates(ids, existing.get("obs_dates") or []) or \
        _obs_dates(ids, [inc.get("observed_on")])
    existing["last_observed_at"] = now
    existing["updated_at"] = now
    existing["confidence"] = compute_conf(existing)


def _find_conflicts(inc, index):
    # 关联性匹配：同一实体(topic_key 或 object) 但谓词不同 + 已有 confirmed → 视为冲突
    conf = []
    for e in index.values():
        if e.get("status") != "confirmed":
            continue
        same_tk = bool(e.get("topic_key")) and e.get("topic_key") == inc.get("topic_key")
        same_obj = norm(e.get("object")) == norm(inc.get("object"))
        diff_pred = norm(e.get("predicate")) != norm(inc.get("predicate"))
        if (same_tk or same_obj) and diff_pred:
            conf.append(e["id"])
    return conf


def cmd_add_facts(args):
    ensure_dirs()
    payload = json.load(open(args.file, encoding="utf-8"))
    incs = payload["facts"] if isinstance(payload, dict) else payload
    existing = read_jsonl(FACTS_PATH)
    index = {f["id"]: f for f in existing}
    now = utcnow_iso()
    rep = {"created": 0, "merged": 0, "rejected_variant": 0, "conflict": 0}
    for inc in incs:
        fid = fact_id(inc)
        if fid in index and index[fid]["status"] == "rejected":  # C4
            k = 2
            while ("%s_v%d" % (fid, k)) in index:
                k += 1
            newfid = "%s_v%d" % (fid, k)
            f = _new_fact(inc, newfid, now)
            f["rejected_variant_of"] = fid
            index[newfid] = f
            rep["rejected_variant"] += 1
            continue
        if fid in index:  # C3 累积（同一 identity = 重复，不新增、不重审）
            _merge(index[fid], inc, now)
            rep["merged"] += 1
        else:
            f = _new_fact(inc, fid, now)
            # 自动关联匹配 + 手动标注（agent 对语义冲突如 photo-agent 可显式标 conflict_with）
            conf = list(dict.fromkeys(_find_conflicts(inc, index) + (inc.get("conflict_with") or [])))
            if conf:
                f["conflict_with"] = conf
                rep["conflict"] += 1
            index[fid] = f
            rep["created"] += 1
    write_jsonl(FACTS_PATH, list(index.values()))
    print("created=%d merged=%d rejected_variant=%d conflict=%d" % (rep["created"], rep["merged"], rep["rejected_variant"], rep["conflict"]))


# ---------- review ----------
def _read_rid_map(md_path):
    rid2fact = {}
    if not os.path.exists(md_path):
        return rid2fact
    lines = open(md_path, encoding="utf-8").read().splitlines()
    for i, line in enumerate(lines):
        m = re.search(r"R(\d{8}-\d{3})", line)
        if m:
            rid = "R" + m.group(1)
            for j in range(i + 1, min(i + 4, len(lines))):
                mf = re.search(r"`(fact_[a-z0-9_]+)`", lines[j])
                if mf:
                    rid2fact[rid] = mf.group(1)
                    break
    return rid2fact


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sugg(f):
    et = f.get("evidence_type")
    c = f.get("confidence", 0)
    if et == "asserted" or c >= 4:
        return "✅"
    if c <= 1 or (et == "inferred" and c <= 2):
        return "❌"
    return "❓"


def _gen_widget(date, assigns, facts, tk_multi):
    fact_by_id = {f2["id"]: f2 for f2 in facts}
    cards = []
    for rid, f in assigns:
        conflict_html = ""
        for cid in (f.get("conflict_with") or []):
            cf = fact_by_id.get(cid)
            if cf:
                conflict_html += '<div style="color:#ef4444;font-size:12px;">⚠ conflicts with confirmed: %s</div>' % _esc(cf.get("statement", ""))
        if conflict_html:
            card = (
                '<div class="item" data-rid="%s" style="border:1px solid var(--border);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;">'
                '<div style="color:var(--foreground);font-size:14px;line-height:1.5;">%s</div>'
                '%s'
                '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">'
                '<button class="opt" data-v="A" style="cursor:pointer;padding:3px 9px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--foreground);font-size:12px;">A 旧的才对</button>'
                '<button class="opt" data-v="B" style="cursor:pointer;padding:3px 9px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--foreground);font-size:12px;">B 新的才对</button>'
                '<button class="opt" data-v="C" style="cursor:pointer;padding:3px 9px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--foreground);font-size:12px;">C 都对</button>'
                '<button class="opt" data-v="D" style="cursor:pointer;padding:3px 9px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--foreground);font-size:12px;">D 其他</button>'
                '</div>'
                '<div style="display:flex;gap:6px;align-items:center;">'
                '<input class="fix" placeholder="if D, explain…" style="flex:1;background:transparent;border:1px solid var(--border);border-radius:6px;padding:4px 8px;color:var(--foreground);font-size:13px;">'
                '</div></div>' % (rid, _esc(f.get("statement")), conflict_html))
        else:
            card = (
                '<div class="item" data-rid="%s" style="border:1px solid var(--border);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;">'
                '<div style="color:var(--foreground);font-size:14px;line-height:1.5;">%s</div>'
                '<div style="display:flex;gap:14px;align-items:center;">'
                '<button class="dec" data-v="对" title="true" style="cursor:pointer;border:none;background:transparent;color:#22c55e;font-size:16px;padding:0;">✓</button>'
                '<button class="dec" data-v="不确定" title="not sure" style="cursor:pointer;border:none;background:transparent;color:#ef4444;font-size:16px;padding:0;">❓</button>'
                '</div>'
                '<div style="display:flex;gap:6px;align-items:center;">'
                '<input class="fix" placeholder="clarify…" style="flex:1;background:transparent;border:1px solid var(--border);border-radius:6px;padding:4px 8px;color:var(--foreground);font-size:13px;">'
                '</div></div>' % (rid, _esc(f.get("statement"))))
        cards.append(card)
    return (
        '<div style="display:flex;flex-direction:column;gap:10px;">'
        '<div style="color:var(--muted-foreground);font-size:13px;">review · %d pending · ✓=true · ❓=not sure · conflict=A/B/C/D · then submit</div>'
        '%s'
        '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;">'
        '<button id="allyes" style="cursor:pointer;padding:7px 14px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--foreground);font-size:13px;">✓ all</button>'
        '<button id="submitall" style="cursor:pointer;padding:7px 14px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--muted-foreground);font-size:13px;">submit (0)</button>'
        '</div></div>'
        '<script>'
        '(function(){'
        'var items=Array.prototype.slice.call(document.querySelectorAll(".item"));'
        'var state={};'
        'function set(b,on){b.style.opacity=on?"1":"0.4";b.style.fontWeight=on?"700":"400";}'
        'function refresh(){var n=0;items.forEach(function(it){var r=it.getAttribute("data-rid");var v=state[r];'
        'it.querySelectorAll(".dec,.opt").forEach(function(b){set(b,b.getAttribute("data-v")===v);});if(v)n++;});'
        'var sa=document.getElementById("submitall");sa.textContent="submit ("+n+")";'
        'sa.style.color=n?"var(--accent)":"var(--muted-foreground)";}'
        'items.forEach(function(it){var r=it.getAttribute("data-rid");'
        'it.querySelectorAll(".dec,.opt").forEach(function(b){b.onclick=function(){var v=b.getAttribute("data-v");'
        'state[r]=(state[r]===v)?undefined:v;refresh();};});'
        'it.querySelector(".fix").addEventListener("focus",function(){'
        'state[r]=it.querySelector(".opt")?"D":"不确定";refresh();});'
        '});'
        'document.getElementById("allyes").onclick=function(){'
        'var ls=items.filter(function(it){return !it.querySelector(".opt");})'
        '.map(function(it){return it.getAttribute("data-rid")+" 对";});'
        'if(ls.length)window.hermes.send(ls.join("\\n"));};'
        'document.getElementById("submitall").onclick=function(){'
        'var ls=[];items.forEach(function(it){var r=it.getAttribute("data-rid");var v=state[r];'
        'if(v==="对")ls.push(r+" 对");'
        'else if(v==="不确定"){var t=it.querySelector(".fix").value.trim();ls.push(r+" 不确定"+(t?":"+t:""));}'
        'else if(v==="A"||v==="B"||v==="C")ls.push(r+" "+v);'
        'else if(v==="D"){var t=it.querySelector(".fix").value.trim();ls.push(r+" D"+(t?":"+t:""));}'
        '});'
        'if(ls.length)window.hermes.send(ls.join("\\n"));};'
        'refresh();'
        '})();'
        '</script>'
    ) % (len(assigns), "\n".join(cards))


# init 的自陈字段：(facet, key, 行标签, 输入框示例)
INIT_QUESTIONS = [
    ("identity", "name", "name", "what should I call you?  e.g. loveakiha / 许诺"),
    ("identity", "work", "work", "job · role · org"),
    ("identity", "family_role", "family", "role at home · e.g. dad / husband / son"),
]


def _gen_init_widget():
    rows = "".join(
        '<div style="display:flex;gap:10px;align-items:center;">'
        '<div style="flex:none;width:64px;color:var(--muted-foreground);font-size:12px;">%s</div>'
        '<input class="q" data-facet="%s" data-key="%s" placeholder="%s" style="flex:1;background:transparent;border:1px solid var(--border);border-radius:6px;padding:4px 8px;color:var(--foreground);font-size:13px;">'
        '</div>' % (label, facet, key, ph)
        for facet, key, label, ph in INIT_QUESTIONS)
    return (
        '<div style="display:flex;flex-direction:column;gap:12px;">'
        '<div style="color:var(--muted-foreground);font-size:13px;line-height:1.5;">'
        'self-intro · write freely in your own words — I split it into facts, you confirm them · '
        'three optional fills below · then submit</div>'
        '<textarea id="intro" rows="6" placeholder="3-5 sentences: who you are, what you do, what you are into, what you are working on — anything you want known for good." '
        'style="width:100%%;box-sizing:border-box;resize:vertical;background:transparent;border:1px solid var(--border);border-radius:8px;padding:8px 10px;color:var(--foreground);font-size:13px;line-height:1.6;"></textarea>'
        '%s'
        '<button id="sub" style="align-self:flex-start;cursor:pointer;padding:8px 16px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--muted-foreground);font-size:13px;">submit (0)</button>'
        '</div>'
        '<script>'
        '(function(){'
        'var intro=document.getElementById("intro");var qs=[].slice.call(document.querySelectorAll(".q"));'
        'var sub=document.getElementById("sub");'
        'function refresh(){var n=(intro.value.trim()?1:0);qs.forEach(function(i){if(i.value.trim())n++;});'
        'sub.textContent="submit ("+n+")";sub.style.color=n?"var(--accent)":"var(--muted-foreground)";}'
        'intro.addEventListener("input",refresh);qs.forEach(function(i){i.addEventListener("input",refresh);});'
        'sub.onclick=function(){'
        'var payload={intro:intro.value.trim(),answers:[]};'
        'qs.forEach(function(i){var v=i.value.trim();'
        'if(v)payload.answers.push({facet:i.getAttribute("data-facet"),key:i.getAttribute("data-key"),v:v});});'
        'if(!payload.intro&&!payload.answers.length)return;'
        'window.hermes.send("PMINIT "+JSON.stringify(payload));'
        'sub.textContent="sent ✓";sub.style.color="var(--muted-foreground)";'
        'intro.disabled=true;qs.forEach(function(i){i.disabled=true;});};'
        'refresh();'
        '})();'
        '</script>'
    ) % rows


def cmd_init(args):
    ensure_dirs()
    p = os.path.join(REVIEWS_DIR, "init.html")
    write_text(p, _gen_init_widget())
    print("init widget ->", p)


def cmd_review(args):
    ensure_dirs()
    date = args.date or today()
    facts = read_jsonl(FACTS_PATH)
    cands = [f for f in facts if f.get("status") == "candidate"]

    # 增量：只看"新候选"（之前 review 没展示过）+ "同 topic_key 有多条事实"（冲突并排给用户看）
    prior_shown = set()
    if not args.all:
        for fn in sorted(os.listdir(REVIEWS_DIR)):
            if fn.endswith(".md") and fn != date + ".md":
                txt = open(os.path.join(REVIEWS_DIR, fn), encoding="utf-8").read()
                prior_shown |= set(re.findall(r"`(fact_[a-z0-9_]+)`", txt))

    tk_multi = {}
    for f in facts:
        tk = f.get("topic_key", "")
        if tk:
            tk_multi[tk] = tk_multi.get(tk, 0) + 1

    shown, hidden = [], 0
    for f in cands:
        tk = f.get("topic_key", "")
        if args.all or f["id"] not in prior_shown or tk_multi.get(tk, 0) >= 2:
            shown.append(f)
        else:
            hidden += 1

    shown.sort(key=lambda f: (f.get("topic_key", ""), f.get("category", ""), f["id"]))

    # 稳定 R-id：复用当天已分配的，只给新候选发新号（避免确认后重编号、连点错位）
    md_path = os.path.join(REVIEWS_DIR, date + ".md")
    rid2fact = _read_rid_map(md_path)
    fact2rid = {fid: rid for rid, fid in rid2fact.items()}
    next_seq = max([int(r.rsplit("-", 1)[1]) for r in rid2fact], default=0)
    assigns = []
    for f in shown:
        fid = f["id"]
        if fid in fact2rid:
            rid = fact2rid[fid]
        else:
            next_seq += 1
            rid = "R%s-%03d" % (date.replace("-", ""), next_seq)
        assigns.append((rid, f))

    head = "共 %d 条待确认" % len(assigns)
    if hidden:
        head += "（另有 %d 条更早候选已隐藏，`pm review --all` 查看全部）" % hidden
    L = ["# 记忆确认 %s" % date, "", head, "",
         "这些是从你今天的对话里提炼的候选事实，你只需判断对/错/改（决策），不必补事实；若漏了重要的事，直接说一句，我再补提。",
         "[建议✅]=大概率成立，点头即可 · [建议❌]=大概率不对，先否 · [建议❓]=拿不准，你定。",
         "逐行回复，每行一条判断（⚡=同主题多条 · ⚠️冲突=与已确认事实矛盾，重点看）：", "",
         "```", "R001 对", "R002 错,理由", "R003 改:新描述", "```", ""]
    fact_by_id = {f2["id"]: f2 for f2 in facts}
    for rid, f in assigns:
        st = f.get("statement") or ""
        ev0 = (f.get("evidence") or [None])[0] or ""
        flag = " ⚡同主题" if tk_multi.get(f.get("topic_key", ""), 0) >= 2 else ""
        conflict = f.get("conflict_with") or []
        if conflict:
            flag += " ⚠️冲突"
        L.append("- [ ] **%s** [建议%s] — %s%s" % (rid, _sugg(f), st, flag))
        L.append("  `%s` · %s · %s · 置信%s/5 · %s" % (
            f["id"], f.get("topic_key", ""), f.get("category", ""),
            f.get("confidence", ""), f.get("evidence_type", "")))
        if ev0:
            L.append("  · 证据：%s" % ev0[:80])
        if conflict:
            for cid in conflict:
                cf = fact_by_id.get(cid)
                if cf:
                    L.append("  ⚠️ 与已确认事实冲突：`%s` [confirmed] %s" % (cid, cf.get("statement", "")))
        if tk_multi.get(f.get("topic_key", ""), 0) >= 2:
            for sib in facts:
                if sib["id"] != f["id"] and sib.get("topic_key", "") == f.get("topic_key", ""):
                    reason = "；否决理由:%s" % sib["user_note"] if sib.get("user_note") else ""
                    L.append("  ↳ 已有 `%s` [%s]：%s%s" % (sib["id"], sib.get("status", ""), sib.get("statement", ""), reason))
        L.append("")
    if not assigns:
        L.append("（无待确认事实）")
    write_text(md_path, "\n".join(L))

    # 交互式 widget（由 ::preview 引用；按钮 data-hermes-send 发隐藏消息）
    html_path = os.path.join(REVIEWS_DIR, date + ".html")
    write_text(html_path, _gen_widget(date, assigns, facts, tk_multi))
    print("%d 待确认（隐藏 %d 旧候选） -> %s + %s" % (len(assigns), hidden, md_path, html_path))


# ---------- apply ----------
def _resolve(tok, rid2fact):
    tok = tok.strip()
    if tok in rid2fact:
        return tok
    if re.fullmatch(r"R\d{8}-\d{3}", tok):
        return tok if tok in rid2fact else None
    m = re.fullmatch(r"R?(\d{3})", tok)
    if m:
        for r in rid2fact:
            if r.endswith("-" + m.group(1)):
                return r
    return None


def _parse_reply(text, rid2fact):
    def strip_kw(s, kws):
        s = s.strip()
        for kw in kws:
            m = re.match(r"^\s*" + re.escape(kw) + r"\s*[，,;；:：.、]?\s*", s, re.I)
            if m:
                return s[m.end():].strip()
        return s

    decisions = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r"(R\d{8}-\d{3}|R\d{3}|#\d+|\b\d{3}\b)", line)
        if not m:
            continue
        rid = _resolve(m.group(1), rid2fact)
        if not rid:
            continue
        rest = line[m.end():].strip().lstrip("——-:：,、，.").strip()
        mo = re.match(r"^([ABCD])\s*[:：]?\s*(.*)$", rest, re.I)
        if mo:
            o = mo.group(1).upper()
            if o == "A":
                decisions[rid] = ("reject", "维持已确认事实")
            elif o == "B":
                decisions[rid] = ("confirm", "采用新说法，旧事实待复核")
            elif o == "C":
                decisions[rid] = ("confirm", "两者都成立（补充）")
            else:
                decisions[rid] = ("skip", mo.group(2) or None)
            continue
        if re.search(r"改\s*[为:：成]?", rest):
            m2 = re.search(r"改\s*[为:：成]?\s*[：:]\s*(.*)", rest) or re.search(r"改\s*[为:：成]?\s+(.*)", rest)
            decisions[rid] = ("modify", (m2.group(1).strip() if m2 else rest))
        elif re.search(r"错|否|不对|删除|拒绝|取消|reject|\bno\b|❌|✗", rest, re.I):
            decisions[rid] = ("reject", strip_kw(rest, ["错", "否", "不对", "删除", "拒绝", "取消", "reject", "no", "❌", "✗"]) or None)
        elif re.search(r"对|确认|是|正确|ok|yes|✓|✅|√", rest, re.I):
            decisions[rid] = ("confirm", strip_kw(rest, ["对", "确认", "是", "正确", "ok", "yes", "✓", "✅", "√"]) or None)
        else:
            decisions[rid] = ("skip", rest)
    return decisions


def cmd_apply(args):
    ensure_dirs()
    date = args.date or today()
    rp = os.path.join(REVIEWS_DIR, date + ".md")
    if not os.path.exists(rp):
        print("无当日 review 文件:", rp)
        return
    lines = open(rp, encoding="utf-8").read().splitlines()
    rid2fact = {}
    for i, line in enumerate(lines):
        m = re.search(r"R(\d{8}-\d{3})", line)
        if not m:
            continue
        rid = "R" + m.group(1)
        for j in range(i + 1, min(i + 4, len(lines))):
            mf = re.search(r"`(fact_[a-z0-9_]+)`", lines[j])
            if mf:
                rid2fact[rid] = mf.group(1)
                break

    decisions = _parse_reply(args.reply, rid2fact)
    facts = read_jsonl(FACTS_PATH)
    index = {f["id"]: f for f in facts}
    now = utcnow_iso()
    for rid, (action, note) in decisions.items():
        fid = rid2fact.get(rid)
        if not fid or fid not in index:
            print("%s -> 未匹配" % rid)
            continue
        f = index[fid]
        if action == "confirm":
            f["status"], f["decided_at"], f["user_note"] = "confirmed", now, note or None
            print("%s -> 已确认" % rid)
        elif action == "reject":
            f["status"], f["decided_at"], f["user_note"] = "rejected", now, note or None
            print("%s -> 已否决" % rid)
        elif action == "modify":
            f["user_note"] = '原:"%s"' % f.get("statement")
            f["statement"], f["status"], f["decided_at"] = note, "confirmed", now
            print("%s -> 已修改并确认" % rid)
        else:
            print("%s -> 跳过" % rid)
            continue
        f["updated_at"] = now
    write_jsonl(FACTS_PATH, list(index.values()))


# ---------- export ----------
def cmd_export(args):
    ensure_dirs()
    facts = read_jsonl(FACTS_PATH)
    conf = [f for f in facts if f.get("status") == "confirmed"]
    L = ["# 用户世界模型（导出视图）", "",
         "> 由 `facts.jsonl` 自动生成，可随时删除重建。唯一事实来源是 facts + reviews，请勿手改本文件。", ""]
    def _major(f):
        for fc in (f.get("facets") or []):
            if "." in fc:
                return fc.split(".", 1)[0]
        return OLD_TO_FACET.get(f.get("category", ""), "traits")
    by = {}
    for f in conf:
        by.setdefault(_major(f), []).append(f)
    for cat in TAXONOMY:
        if cat not in by:
            continue
        L.append("## %s" % FACET_LABEL.get(cat, cat))
        for f in by[cat]:
            src = ", ".join(f.get("source_agents", []) or [])
            L.append("- %s  `[%s]` (来源:%s, 置信%s/5)" % (
                f["statement"], f.get("topic_key", ""), src, f.get("confidence", "")))
        L.append("")
    L.append("---\n生成于 %s · 已确认事实 %d 条" % (today(), len(conf)))
    write_text(USER_MODEL, "\n".join(L))
    print("exported %d confirmed facts -> %s" % (len(conf), USER_MODEL))


# ---------- rebuild / recall ----------
def cmd_rebuild(args):
    ensure_dirs()
    if os.path.exists(CACHE_DB):
        os.remove(CACHE_DB)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("create table observations(id text primary key, agent text, observed_at text, "
                 "conv_ref text, summary text, topics text)")
    conn.execute("create table facts(id text primary key, topic_key text, category text, "
                 "predicate text, object text, statement text, evidence_type text, "
                 "confidence int, status text, first_observed_at text, last_observed_at text, "
                 "obs_dates text, evidence_count int, source_agents text, facets text)")
    no, nf = 0, 0
    for root, _dirs, files in os.walk(OBS_DIR):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            for o in read_jsonl(os.path.join(root, fn)):
                conn.execute("insert or replace into observations values (?,?,?,?,?,?)",
                             (o.get("id"), o.get("agent"), o.get("observed_at"),
                              o.get("conv_ref"), o.get("summary"), json.dumps(o.get("topics", []), ensure_ascii=False)))
                no += 1
    for f in read_jsonl(FACTS_PATH):
        conn.execute("insert or replace into facts values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (f.get("id"), f.get("topic_key"), f.get("category"), f.get("predicate"),
                      f.get("object"), f.get("statement"), f.get("evidence_type"),
                      f.get("confidence"), f.get("status"), f.get("first_observed_at"),
                      f.get("last_observed_at"), json.dumps(f.get("obs_dates", []), ensure_ascii=False),
                      f.get("evidence_count"), json.dumps(f.get("source_agents", []), ensure_ascii=False),
                      json.dumps(f.get("facets", []), ensure_ascii=False)))
        nf += 1
    conn.commit()
    conn.close()
    print("rebuilt %s: observations=%d facts=%d" % (CACHE_DB, no, nf))


def cmd_recall(args):
    if not os.path.exists(CACHE_DB):
        cmd_rebuild(None)
    conn = sqlite3.connect(CACHE_DB)
    q = args.query
    if getattr(args, "facet", None):
        rows = conn.execute(
            "select id,statement,facets,confidence,status,topic_key from facts "
            "where facets like ? order by confidence desc limit 50",
            ("%" + args.facet + "%",)).fetchall()
    else:
        rows = conn.execute(
            "select id,statement,facets,confidence,status,topic_key from facts "
            "where statement like ? or object like ? or topic_key like ? "
            "order by (case status when 'confirmed' then 0 when 'candidate' then 1 else 2 end), confidence desc limit 20",
            ("%" + q + "%", "%" + q + "%", "%" + q + "%")).fetchall()
    conn.close()
    if not rows:
        print("无匹配")
        return
    for r in rows:
        print("[%s] %s  (%s · 置信%s · %s)" % (r[4], r[1], r[2], r[3], r[5]))


# ---------- config ----------
def cmd_config(args):
    cfg = load_config()
    if args.action == "get":
        for k, v in cfg.items():
            print("%s = %s" % (k, v))
    elif args.action == "set":
        if args.key == "granularity" and args.value not in ("exhaustive", "concise"):
            print("granularity 只支持 exhaustive(事无巨细) / concise(关键重要≤5条/天)")
            return
        cfg[args.key] = args.value
        save_config(cfg)
        print("%s = %s" % (args.key, cfg[args.key]))


# ---------- sync ----------
def cmd_sync(args):
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        subprocess.run(["git", "-C", ROOT, "init"], check=True)
    subprocess.run(["git", "-C", ROOT, "add", "-A"], check=True)
    r = subprocess.run(["git", "-C", ROOT, "diff", "--cached", "--quiet"])
    if r.returncode == 0:
        print("无变更")
        return
    subprocess.run(["git", "-C", ROOT, "commit", "-m", args.message or ("memory %s" % today())], check=True)
    print("committed")
    rem = subprocess.run(["git", "-C", ROOT, "remote"], capture_output=True, text=True)
    if rem.stdout.strip():
        subprocess.run(["git", "-C", ROOT, "push"], check=True)
        print("pushed")


def main():
    ap = argparse.ArgumentParser(description="know-me v0")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="导入对话 -> observation")
    p.add_argument("source")
    p.add_argument("--db")
    p.add_argument("--since", help="YYYY-MM-DD，默认今天")

    p = sub.add_parser("add-facts", help="导入候选事实 JSON")
    p.add_argument("file")

    p = sub.add_parser("review")
    p.add_argument("--date")
    p.add_argument("--all", action="store_true")

    p = sub.add_parser("apply")
    p.add_argument("reply")
    p.add_argument("--date")

    sub.add_parser("init")
    sub.add_parser("export")
    sub.add_parser("rebuild")

    p = sub.add_parser("recall")
    p.add_argument("query")
    p.add_argument("--facet", help="按标签过滤，如 interests.tech 或 activities")

    p = sub.add_parser("config")
    csp = p.add_subparsers(dest="action", required=True)
    csp.add_parser("get")
    cset = csp.add_parser("set")
    cset.add_argument("key")
    cset.add_argument("value")

    p = sub.add_parser("sync")
    p.add_argument("--message")

    args = ap.parse_args()
    {"import": cmd_import, "add-facts": cmd_add_facts, "review": cmd_review,
     "apply": cmd_apply, "init": cmd_init, "export": cmd_export, "rebuild": cmd_rebuild,
     "recall": cmd_recall, "config": cmd_config, "sync": cmd_sync}[args.cmd](args)


if __name__ == "__main__":
    main()
