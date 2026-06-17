"""FAISS 向量索引 + 检索。"""
import os
import pickle
import numpy as np

# 延迟导入 faiss，避免未安装时阻塞其他模块
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

INDEX_PATH = os.path.join(os.path.dirname(__file__), "faiss_index.bin")
CHUNKS_PATH = os.path.join(os.path.dirname(__file__), "chunks.pkl")

# 全局缓存
_index = None
_chunks = None


def _ensure_faiss():
    if not FAISS_AVAILABLE:
        raise ImportError("faiss-cpu 未安装，请运行: pip install faiss-cpu")


def build_index(chunks: list[str]) -> None:
    """
    对 chunks 编码并构建 FAISS 索引，保存到文件。
    使用 IndexFlatIP（内积相似度），向量需先做 L2 归一化。
    """
    _ensure_faiss()
    from rag.embedder import embed

    print(f"正在构建 FAISS 索引，共 {len(chunks)} 个片段...")

    # 获取所有 chunk 的 embedding
    vectors = embed(chunks)
    vec_array = np.array(vectors, dtype=np.float32)

    # L2 归一化，使内积等价于余弦相似度
    faiss.normalize_L2(vec_array)

    # 构建 IndexFlatIP 索引（1024 维）
    dim = vec_array.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vec_array)

    # 保存索引到文件
    faiss.write_index(index, INDEX_PATH)

    # 保存 chunks 到文件
    with open(CHUNKS_PATH, "wb") as f:
        pickle.dump(chunks, f)

    # 更新全局缓存
    global _index, _chunks
    _index = index
    _chunks = chunks

    print(f"FAISS 索引构建完成，索引文件: {INDEX_PATH}")


def _load_index():
    """加载已保存的索引和 chunks。如果文件不存在则返回 None。"""
    global _index, _chunks

    if _index is not None and _chunks is not None:
        return

    _ensure_faiss()

    if os.path.exists(INDEX_PATH) and os.path.exists(CHUNKS_PATH):
        _index = faiss.read_index(INDEX_PATH)
        with open(CHUNKS_PATH, "rb") as f:
            _chunks = pickle.load(f)
        print(f"已加载 FAISS 索引 ({_index.ntotal} 条向量)")
    else:
        # 索引未构建，从 policies.md 构建
        from rag.loader import load_policies
        chunks = load_policies()
        build_index(chunks)


def search(query: str, top_k: int = 3) -> list[str]:
    """
    检索与 query 最相关的 top_k 个文档片段。
    如果索引未初始化，自动调用 build_index()。
    """
    _ensure_faiss()
    from rag.embedder import embed_single

    # 确保索引已加载
    _load_index()

    # 编码查询
    query_vec = np.array([embed_single(query)], dtype=np.float32)
    faiss.normalize_L2(query_vec)

    # 检索
    scores, indices = _index.search(query_vec, min(top_k, len(_chunks)))

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx >= 0 and idx < len(_chunks):
            results.append(_chunks[idx])

    return results
