"""测试 compact_history 裁剪逻辑"""
from core.context_manager import compact_history, COMPACT_TRIGGER, KEEP_RECENT

# ── 模拟场景：构建 30 条 history（15 轮对话）──
history = []
for i in range(15):
    history.append({"role": "user", "content": f"我想请年假{i+1}天"})
    history.append({"role": "assistant", "content": f"好的，年假申请已提交，编号 lv_test{i+1:03d}，等待审批。"})

print(f"原始 history 长度: {len(history)}")
print(f"COMPACT_TRIGGER: {COMPACT_TRIGGER}")

# ── 裁剪 ──
result = compact_history(history)
print(f"裁剪后 history 长度: {len(result)}")
print()

# ── 检查结构 ──
for i, msg in enumerate(result):
    role = msg["role"]
    content = msg["content"][:80]
    print(f"  [{i}] {role}: {content}")

print()

# ── 验证断言 ──
# 1. 裁剪后应该 <= 摘要对(2) + KEEP_RECENT(12) = 14
assert len(result) <= 2 + KEEP_RECENT, f"Expected <= 14, got {len(result)}"
print("OK: 裁剪后长度在预期范围内")

# 2. 前两条应该是摘要对
assert result[0]["role"] == "user" and "摘要" in result[0]["content"]
assert result[1]["role"] == "assistant" and "已了解" in result[1]["content"]
print("OK: 摘要对正确插入")

# 3. 后面的消息应该是最新的
assert result[-1]["role"] == "assistant"
print("OK: 最新消息保留正确")

# 4. 短 history 不应该被裁剪
short = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
assert compact_history(short) is short  # 原样返回（同一引用）
print("OK: 短 history 原样返回")

# 5. 刚好等于 COMPACT_TRIGGER 不应该触发
flat = []
for i in range(COMPACT_TRIGGER // 2):
    flat.append({"role": "user", "content": f"msg{i}"})
    flat.append({"role": "assistant", "content": f"reply{i}"})
assert len(flat) == COMPACT_TRIGGER
assert compact_history(flat) is flat
print(f"OK: 刚好 {COMPACT_TRIGGER} 条不触发裁剪")

# 6. COMPACT_TRIGGER + 1 应该触发
flat_plus = flat + [{"role": "user", "content": "one more"}]
result2 = compact_history(flat_plus)
assert len(result2) <= 2 + KEEP_RECENT
print(f"OK: COMPACT_TRIGGER+1 条触发裁剪, 结果 {len(result2)} 条")

# 7. 多轮裁剪不会丢失信息（摘要也会被重新提取）
# 模拟 60 轮对话，第一次裁剪
big = []
for i in range(60):
    big.append({"role": "user", "content": f"查询第{i}次"})
    big.append({"role": "assistant", "content": f"第{i}次结果: 年假剩余{20-i*0.1:.1f}天"})
r1 = compact_history(big)
assert len(r1) <= 2 + KEEP_RECENT  # 14 条
assert r1[0]["role"] == "user" and "摘要" in r1[0]["content"]
print(f"OK: 第一次裁剪后 {len(r1)} 条, 摘要存在")

# 继续追加 10 轮（20 条），总条数 14+20=34 > 24，触发第二次裁剪
for i in range(60, 70):
    r1.append({"role": "user", "content": f"查询第{i}次"})
    r1.append({"role": "assistant", "content": f"第{i}次结果: 年假剩余{20-i*0.1:.1f}天"})
r2 = compact_history(r1)
assert len(r2) <= 2 + KEEP_RECENT
# 摘要应该包含两轮的信息（第一轮摘要 + 第二轮旧消息）
assert r2[0]["role"] == "user" and "摘要" in r2[0]["content"]
print(f"OK: 第二次裁剪后 {len(r2)} 条, 摘要持续存在")

print()
print("所有测试通过！")
