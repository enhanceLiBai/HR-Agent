"""search_policy —— RAG 检索公司制度。"""
from rag.retriever import search as rag_search

TOOL_SEARCH_POLICY = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": "检索公司假期和考勤制度文档。当员工询问任何关于假期规定、请假条件、考勤规则的问题时，必须先调用此工具查询。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索查询语句，如'年假可以请几天'、'病假需要什么证明'、'婚假怎么休'"
                }
            },
            "required": ["query"]
        }
    }
}


def search_policy(query: str) -> str:
    """
    在 policies.md 中检索与查询相关的制度规定。

    实现：
        1. 调用智谱 embedding-2 将 query 转为向量
        2. 用 FAISS 在预建索引中检索 top-3 最相似的文档片段
        3. 将 3 个片段用 "\n---\n" 拼接返回
        4. 如果 FAISS 索引未初始化，先调用 build_index() 构建

    参数:  query - 自然语言查询，如 "年假最多能请几天" 或 "病假需要什么证明"
    返回:  相关制度文本片段，如未找到则返回 "未找到相关制度规定。"
    """
    try:
        results = rag_search(query, top_k=3)
    except Exception as e:
        return f"❌ 检索制度时出错: {str(e)}"

    if not results:
        return "未找到相关制度规定。"

    return "\n---\n".join(results)
