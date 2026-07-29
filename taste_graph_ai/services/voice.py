"""
voice.py — AI 写作语调统一入口

所有 AI 生成的内容（标题 / 文案 / 趋势解读 / 预填）必须先过本模块。
底层数据：
  - docs/voice.md             (人类可读的规则)
  - data/voice_examples.json  (5 条 few-shot 样本)
  - taste_memory.json         (prefer/avoid 词表)

用法：
  from taste_graph_ai.services.voice import build_messages
  msgs = build_messages("caption", user_prompt="9 张图关于 灰色", context={"images": [...]})
  # msgs 是 OpenAI 风格的 messages 数组
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any

# ── 路径 ────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
VOICE_EXAMPLES_PATH = REPO_ROOT / "data" / "voice_examples.json"
TASTE_MEMORY_PATH = REPO_ROOT / "taste_memory.json"

# ── 加载 few-shot 样本（启动时一次，缓存到模块级）──
def _load_examples() -> list[dict]:
    try:
        with open(VOICE_EXAMPLES_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("examples", [])
    except Exception:
        return []

def _load_keywords() -> tuple[list[str], list[str]]:
    """返回 (prefer_keywords, avoid_keywords)"""
    try:
        with open(TASTE_MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        prefer = data.get("prefer", {}).get("keywords", [])
        avoid = data.get("avoid", {}).get("keywords", [])
        return prefer, avoid
    except Exception:
        return [], []

_EXAMPLES = _load_examples()
_PREFER, _AVOID = _load_keywords()


# ── 核心 system prompt ──────────────────────────────────
def _build_system_prompt(task: str) -> str:
    """根据任务类型拼 system message"""
    prefer_str = "、".join(_PREFER[:20])  # 限 20 个避免 prompt 过长
    avoid_str = "、".join(_AVOID)

    base = f"""你是 TasteGraph AI 的内容生成助手。
整个账号的 voice 是 **quiet-cool editorial travel lifestyle** —— 像 Hidden NY × JJJJound × archive mood 的私藏参考册。

# Identity
冷静、克制、都市、低饱和，但不能无聊。所有输出必须符合这个 voice。

# North Star
Quiet, but not empty · Cool, but not performative · Refined, but not luxury-flexing · Daily, but not boring · Strange enough to have taste · Practical enough to become products.

# PREFER 关键词（强烈倾向）
{prefer_str}

# AVOID 关键词（绝对不要用）
{avoid_str}

# 绝对不要出现的表达
"姐妹们冲" / "太绝了" / "高级感拉满" / "氛围感天花板" / "普通人必看" / "谁懂啊" / "狠狠拿捏"

# 推荐使用的开头
"最近越来越喜欢..." / "这组不是在讲..." / "它吸引我的地方是..." / "有些东西不需要太明确地表达自己。"

# Caption 硬性要求
1. 短句 + 句号断行（不要感叹号）
2. 至少 1 个具体设计师/品牌（Helmut Lang / Raf Simons / Jil Sander / Margiela / Acne Studios / Lemaire / Our Legacy / 032c / Vitsoe / Dries Van Noten）
3. 至少 1 个具体材质词（棉 / 羊毛 / 牛仔 / PVC / 聚酯 / 锌合金 / 哑光金属 / 亚麻 / 帆布）
4. 至少 1 个具体地点或时间（安特卫普 2006 / 表参道 / 涩谷 8:47 / 雨天下午 / 安特卫普 / 巴黎 / 柏林）
5. 至少 1 句否定陈述（"没有 logo" / "无印花" / "无装饰" / "没有暖意"）

# Title 硬性要求
1. ≤ 20 字
2. 是一个 taste 判断，不只描述
3. 中英混用时整条保持单一语种
4. 3 个备选让用户挑
5. ❌ 避免：今日 moodboard / 好看的图片分享 / 最近喜欢的风格 / 一些穿搭参考
"""

    # 任务特定规则
    task_rules = {
        "caption": """
# 当前任务：生成 caption
- 短句、句号断行
- 像一段旁白，不像广告
- 句尾可以是一个具体物件、一个否定陈述、或一个文化锚点
- 不要 wrap 标题（caption 跟 title 是两个东西）
""",
        "title": """
# 当前任务：生成 3 个 title 备选
- 返回 JSON 数组，3 个字符串
- 每个 ≤ 20 字
- 3 个风格不同：可分别走「具象物件」「判断句」「英文化」
""",
        "theme": """
# 当前任务：生成 theme 名
- 2-3 字 + 句点断句（例：物.粉.形 / 灰调静止 / 冷质穿搭）
- 抽象但具体
- 避免形容词堆砌
""",
        "trend": """
# 当前任务：解读趋势
- 用"上升中 / 消退中 / 编辑建议" 三个段落
- 每个段落的语气要像编辑简报，不像新闻
- 提到具体设计师/品牌/年份
- 末尾给 1-2 个具体的"做内容方向"
""",
        "prefill": """
# 当前任务：预填 3 字段
返回严格 JSON：
{{
  "theme": "2-3 字主题（句点断句或短词）",
  "title": "≤ 20 字 标题（taste 判断）",
  "caption": "短句 caption（符合上面 Caption 硬性要求）"
}}
""",
    }
    return base + task_rules.get(task, "")


# ── 拼 few-shot messages ────────────────────────────────
def _build_few_shot(task: str) -> list[dict]:
    """
    根据 task 选最相关的 2 条样本当 few-shot。
    优先用 caption 类的样本（最丰富），其他任务也可复用。
    """
    if not _EXAMPLES:
        return []

    msgs: list[dict] = []
    # 选 2 条 caption 类的样本
    for ex in _EXAMPLES[:2]:
        msgs.append({"role": "user", "content": f"用 voice 写一段 caption：{ex['why_today']}"})
        msgs.append({"role": "assistant", "content": ex["caption"]})

    # 如果是 title 任务，再附 title 样本
    if task == "title" and _EXAMPLES:
        ex = _EXAMPLES[0]
        msgs.append({"role": "user", "content": f"用 voice 写 3 个 title 备选：{ex['why_today']}"})
        msgs.append({"role": "assistant", "content": json.dumps(ex["titles"], ensure_ascii=False)})

    return msgs


# ── 公共 API ────────────────────────────────────────────
def build_messages(
    task: str,
    user_input: str,
    context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """
    拼 OpenAI 风格的 messages 数组。

    Args:
        task: caption | title | theme | trend | prefill
        user_input: 用户原始 prompt
        context: 可选上下文（如图片描述、关键词、源信息）

    Returns:
        list of {"role": "system/user/assistant", "content": "..."}
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system_prompt(task)},
    ]
    # few-shot
    messages.extend(_build_few_shot(task))
    # 实际任务
    user_content = user_input
    if context:
        ctx_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
        user_content = f"{user_input}\n\n# Context\n{ctx_str}"
    messages.append({"role": "user", "content": user_content})
    return messages


def get_system_prompt(task: str) -> str:
    """只返回 system prompt（调试 / 测试用）"""
    return _build_system_prompt(task)


def get_examples() -> list[dict]:
    """返回 few-shot 样本（调试 / 测试用）"""
    return _EXAMPLES


# ── 自测 ────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(f"Loaded {_len := len(_EXAMPLES)} examples, {len(_PREFER)} prefer, {len(_AVOID)} avoid")
    print("=" * 60)
    msgs = build_messages("prefill", "9 张图：灰色、棉质、城市、阴天", context={"sources": ["Helmut Lang", "Lemaire"]})
    for m in msgs:
        print(f"\n[{m['role']}]")
        print(m["content"][:300] + ("..." if len(m["content"]) > 300 else ""))
