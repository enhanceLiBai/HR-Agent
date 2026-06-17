"""文档加载器 —— 加载 policies.md 并按 --- 分隔符切分。"""
import os


def load_policies() -> list[str]:
    """
    加载 policies.md 并按 '---' 分隔符切分为文档片段。
    每个片段保留其所属的 ## 标题作为上下文。
    返回 chunk 列表，预期约 12-15 个 chunk。
    """
    policies_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "policies.md")

    if not os.path.exists(policies_path):
        raise FileNotFoundError(f"找不到制度文件: {policies_path}")

    with open(policies_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 按 --- 分隔
    raw_chunks = content.split("\n---\n")

    chunks = []
    current_title = ""  # 跟踪最近遇到的 ## 标题

    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # 提取标题行作为上下文
        for line in chunk.split("\n"):
            line = line.strip()
            if line.startswith("## "):
                current_title = line
                break

        # 如果 chunk 本身没有标题，给它加上最近的标题作为上下文
        if current_title and not any(l.strip().startswith("## ") for l in chunk.split("\n")):
            chunk = current_title + "\n" + chunk

        # 跳过纯标题块（就是单独的 --- 之间的标题前言）
        chunks.append(chunk)

    print(f"加载制度文档完成，共 {len(chunks)} 个片段。")
    return chunks
