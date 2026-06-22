"""测试 Mini Agent 的脚本 — 直接用 Python 跑，不乱码。"""
import urllib.request
import urllib.parse
import json

tests = [
    ("你好", "闲聊测试"),
    ("3 + 5 * 2 等于多少", "工具调用：计算器"),
    ("现在几点了", "工具调用：时间"),
    ("北京到上海多远", "无工具，模型直接回复"),
]

for msg, desc in tests:
    encoded = urllib.parse.quote(msg)
    url = f"http://127.0.0.1:8001/chat?msg={encoded}"
    resp = urllib.request.urlopen(url)
    data = json.loads(resp.read().decode("utf-8"))
    print("=" * 50)
    print(f"【{desc}】")
    print(f"用户: {msg}")
    print(f"AI: {data['reply']}")
    print()
