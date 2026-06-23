"""SESSION-level LLM annotator — generates a Chinese title + summary for the trajectory."""
import json

from trajlens.core.model import Item

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "中文短标题，10-20字，概括任务主题",
        },
        "summary": {
            "type": "string",
            "description": "中文摘要，2-4句话，覆盖任务目标、过程特点、结果质量",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-6个标签，如: bug修复, 前端, 重构, 测试, 多轮对话, 工具密集, 高质量, 有回退",
        },
    },
    "required": ["title", "summary", "tags"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """你是一个编码智能体轨迹的分析员。给定一条完整的 agent session 数据，生成中文标题、摘要和标签。

## 你会看到

1. **首轮用户消息**（完整）— 这是任务的起点
2. **末轮 assistant 消息**（完整）— 这是任务的终点/结果
3. **脚手架统计** — 轮次数、步骤数、工具调用次数、工具种类
4. **已有标注** — resolution(解决状态)、pushback(回退次数) 等

## 输出要求

- **title**: 中文，10-20字，能区分不同轨迹的核心任务。格式参考: "修复登录页 XSS 漏洞" / "重构用户认证模块" / "为 API 添加分页支持"
- **summary**: 中文，2-4句话，纯客观陈述，不要美化或乐观推测。第一句说任务目标。第二句说过程事实（轮次、主要操作）。第三句说结局——只描述最后一条消息实际说了什么，不推断用户是否满意。如果没有明确成功信号，就写"未见明确成功确认"，不要写"最终解决了问题"。
- **tags**: 3-5个标签，只打类型和领域标签，不打质量标签:
  - 任务类型: bug修复, 新功能, 重构, 测试, 文档, 配置, git操作, 调研, 代码审查, 算法
  - 技术领域: 前端, 后端, API, 数据库, CI/CD, 安全, DevOps, 文件操作

响应必须是有效 JSON。"""


def _summarize(it: Item, max_chars: int = 500) -> str:
    if it.type == "message":
        c = it.content[:max_chars] + ("…" if len(it.content) > max_chars else "")
        return f"[{it.role}] {c}"
    if it.type == "function_call":
        return f"[call] {it.name}({it.arguments[:100]})"
    if it.type == "function_call_output":
        return f"[output] {it.output[:150]}"
    return ""


def build(unit: list, ctx: list) -> list[dict]:
    items = unit

    # Extract first user message (full)
    first_user = ""
    for it in items:
        if it.type == "message" and it.role == "user":
            first_user = it.content[:2000]
            break

    # Extract last assistant message (full)
    last_asst = ""
    for it in reversed(items):
        if it.type == "message" and it.role == "assistant":
            last_asst = it.content[:2000]
            break

    # Compute scaffold stats
    turn_count = sum(1 for it in items if it.type == "message" and it.role == "user")
    step_count = len({(it.run_id, it.step_id) for it in items if it.step_id is not None})
    tool_calls = [it for it in items if it.type == "function_call"]
    tool_count = len(tool_calls)
    tool_names = list(dict.fromkeys(it.name for it in tool_calls))  # unique, ordered

    stats = (
        f"user_turns: {turn_count}  ← \"多轮对话\" 仅当 >=3\n"
        f"steps: {step_count}\n"
        f"tool_calls: {tool_count}  ← \"工具密集\" 仅当 >=10\n"
        f"tool_names: {', '.join(tool_names[:15]) if tool_names else '无'}\n"
        f"total_items: {len(items)}"
    )

    prompt_parts = [
        "## 首轮用户消息\n" + (first_user or "(无)"),
        "## 末轮 assistant 消息\n" + (last_asst or "(无)"),
        "## 脚手架统计（选 tags 时必须严格依据这些数值）\n" + stats,
    ]

    prompt = "\n\n".join(prompt_parts) + "\n\n请生成 title、summary 和 tags。"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def parse(response: str) -> dict:
    data = _loads(response)
    if data is None:
        return {"title": "", "summary": "", "tags": []}
    return {
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
        "tags": data.get("tags", []),
    }


def _loads(response: str) -> dict | None:
    for candidate in (response, _strip_fences(response), _braces(response)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _braces(s: str) -> str:
    lo, hi = s.find("{"), s.rfind("}")
    return s[lo:hi + 1] if 0 <= lo < hi else ""
