"""上下文窗口管理 —— 滑动窗口 + 规则提取式摘要。

策略：
  1. 消息总数超过 MAX_MESSAGES（32 条）时触发裁剪
  2. 保留最近 KEEP_RECENT（12 条）消息不变
  3. 被裁掉的旧消息用正则提取关键事实，压缩为摘要
  4. 摘要插在 system prompt 之后、保留消息之前
  5. 不用 LLM 做摘要，避免额外延迟和成本
"""
import re

# ── 阈值 ──
MAX_MESSAGES = 32     # 超过此数量触发裁剪（含 system prompt）
KEEP_RECENT = 12      # 保留最近 N 条消息原样不动
COMPACT_TRIGGER = 24  # history 超过此数量触发持久化裁剪（纯 user+assistant，不含 system）

# ── 丢弃名单：这些工具返回值又长又可重查 ──
DISCARD_TOOLS = {"search_policy"}  # 制度全文每次可重新 RAG

# ── 提取规则：(正则, 格式化模板) ──
EXTRACTORS: list[tuple[str, str]] = [
    # 假期余额
    (r"(年假|事假|病假|婚假|丧假|产假|陪产假|调休假).*?剩余\s*(\d+\.?\d*)\s*天", r"\1剩余\2天"),
    (r"调休.*?(\d+\.?\d*)\s*小时", r"调休余额\1小时"),
    # 请假/加班编号
    (r"编号\s*(lv_[a-z0-9]+|ot_[a-z0-9]+)", r"申请\1"),
    (r"(lv_[a-z0-9]+|ot_[a-z0-9]+).*?(年假|事假|病假|婚假|丧假|产假|陪产假|调休假|加班)\s*(\d+\.?\d*)\s*天", r"\1: \2 \3天"),
    # 审批结果
    (r"✅\s*(已批准|已拒绝|已撤销|已撤回|已自动通过)", r"\1"),
    (r"状态.*?(等待|已批准|已拒绝|pending|approved|rejected)", r"\1"),
    # 考勤
    (r"迟到\s*(\d+)\s*次", r"迟到\1次"),
    (r"缺勤\s*(\d+)\s*天", r"缺勤\1天"),
    # 员工信息
    (r"(emp_\d{4})\s*(\S+?)(?:\s|$)", r"\1 \2"),
    # 请假日期
    (r"(\d{4}-\d{2}-\d{2})\s*(?:至|到)\s*(\d{4}-\d{2}-\d{2})", r"\1至\2"),
]

# ── 用户消息压缩用 —
_USER_COMPRESS_PATTERNS = [
    (r"(请\S*假|撤回|撤销|审批|加班|考勤|余额|打卡|迟到).*", r"\1"),
]


def trim_context(messages: list[dict]) -> list[dict]:
    """
    对消息列表执行滑动窗口裁剪。

    参数:
        messages: 完整的消息列表，第一条应为 system prompt

    返回:
        裁剪后的消息列表（可能是原列表，未触发裁剪时原样返回）
    """
    if len(messages) <= MAX_MESSAGES:
        return messages

    # ── 分拆 ──
    system_msg = messages[0]           # system prompt 不动
    body = messages[1:]                # 可裁剪的对话体
    old = body[:-KEEP_RECENT]          # 要被压缩的旧消息
    recent = body[-KEEP_RECENT:]       # 保留的最近消息

    # ── 从旧消息中提取关键事实 ──
    facts = _extract_facts(old)

    # ── 重组 ──
    new_messages = [system_msg]

    if facts:
        summary_lines = "\n".join(f"- {f}" for f in facts)
        summary = (
            "[对话历史摘要] 以下是从之前对话中提取的关键信息：\n"
            + summary_lines
        )
        new_messages.append({"role": "user", "content": summary})
        new_messages.append({"role": "assistant", "content": "已了解之前的对话内容，我会基于这些信息继续帮你。"})

    new_messages.extend(recent)
    return new_messages


def _extract_facts(messages: list[dict]) -> list[str]:
    """从消息列表中用正则提取关键事实。"""
    facts: list[str] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if not content:
            continue

        if role == "user":
            # 压缩用户消息
            compressed = _compress_user(content)
            if compressed:
                facts.append(f"用户: {compressed}")

        elif role == "tool":
            # 丢弃长文本工具返回值（制度全文等）
            tool_name = _guess_tool_name(msg)
            if tool_name in DISCARD_TOOLS:
                continue
            if len(content) > 300:
                continue
            # 正则提取
            extracted = _apply_extractors(content)
            if extracted:
                facts.extend(extracted)
            else:
                # 没有匹配到规则 → 取第一行
                first_line = content.split("\n")[0].strip()
                if first_line and len(first_line) <= 80:
                    facts.append(first_line)

        elif role == "assistant":
            # 跳过带 tool_calls 的中间消息（纯骨架，无文本价值）
            if msg.get("tool_calls"):
                continue
            # 跳过很短的确认性回复
            if len(content) <= 20:
                continue
            # 取前 150 字
            short = content[:150]
            if len(content) > 150:
                short += "…"
            facts.append(f"助手: {short}")

    # ── 去重 + 限制数量 ──
    seen: set[str] = set()
    unique: list[str] = []
    for f in facts:
        if f not in seen:
            seen.add(f)
            unique.append(f)
        if len(unique) >= 15:
            break

    return unique


def _guess_tool_name(msg: dict) -> str:
    """尝试从消息内容推断工具名（tool 消息没有直接标工具名）。"""
    content = msg.get("content", "")
    # 通过特征关键词反推
    if "剩余" in content and ("年假" in content or "事假" in content or "调休" in content):
        return "query_leave_balance"
    if "调休" in content and "小时" in content:
        return "query_overtime_balance"
    if "请假申请已" in content or "编号 lv_" in content:
        return "create_leave_request"
    if "自动审批" in content:
        return "check_auto_approval"
    if "部门人力" in content:
        return "check_department_conflict"
    if "考勤" in content or "打卡" in content:
        return "query_my_attendance"
    if "迟到" in content and "次" in content:
        return "get_attendance_stats"
    if "制度" in content or "规定" in content:
        return "search_policy"
    return ""


def _apply_extractors(text: str) -> list[str]:
    """对文本应用所有提取规则，返回匹配到的格式化片段。"""
    results: list[str] = []
    for pattern, template in EXTRACTORS:
        for match in re.finditer(pattern, text):
            try:
                formatted = match.expand(template)
                if formatted and len(formatted) <= 60:
                    results.append(formatted)
            except (re.error, ValueError):
                continue
    return results


def _compress_user(text: str) -> str:
    """将用户消息压缩为简短意图描述。"""
    text = text.strip()
    # 短消息原样保留
    if len(text) <= 30:
        return text
    # 尝试匹配常见模式
    for pattern, template in _USER_COMPRESS_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return text[:m.end()]
    # 兜底：截断
    return text[:40] + "…"


def compact_history(history: list[dict]) -> list[dict]:
    """
    裁剪持久化历史，避免 DB 和内存中的 history 无限膨胀。

    与 trim_context() 的区别：
        - trim_context 操作 messages（含 system + tool），在 LLM 调用前运行
        - compact_history 操作 history（仅 user + assistant），在回复完成后运行
        - 两者共用同一套 _extract_facts() 提取规则

    参数:
        history: 用户+助手消息列表（不含 system prompt 和 tool 消息）

    返回:
        裁剪后的列表（可能是原列表，未触发裁剪时原样返回）
    """
    if len(history) <= COMPACT_TRIGGER:
        return history

    # ── 分拆 ──
    old = history[:-KEEP_RECENT]
    recent = history[-KEEP_RECENT:]

    # ── 从旧消息中提取关键事实（复用已有提取器）──
    facts = _extract_facts(old)

    # ── 重组 ──
    new_history: list[dict] = []

    if facts:
        summary_lines = "\n".join(f"- {f}" for f in facts)
        summary = (
            "[对话历史摘要] 以下是从之前对话中提取的关键信息：\n"
            + summary_lines
        )
        new_history.append({"role": "user", "content": summary})
        new_history.append({"role": "assistant", "content": "已了解之前的对话内容，我会基于这些信息继续帮你。"})

    new_history.extend(recent)
    return new_history
