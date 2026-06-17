"""智谱 Embedding 封装 —— 通过 OpenAI 兼容 API 调用 embedding-2。"""
import os
import numpy as np
from openai import OpenAI


def get_embedder() -> OpenAI:
    """获取智谱 embedding 客户端。"""
    api_key = os.getenv("ZHIPU_API_KEY")
    base_url = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")

    if not api_key:
        raise ValueError("请设置环境变量 ZHIPU_API_KEY")

    return OpenAI(api_key=api_key, base_url=base_url)


def embed(texts: list[str]) -> list[list[float]]:
    """
    对文本列表进行 embedding，返回向量列表。
    每个向量为 1024 维。
    """
    client = get_embedder()
    model = os.getenv("ZHIPU_EMBEDDING_MODEL", "embedding-2")

    response = client.embeddings.create(
        model=model,
        input=texts,
    )

    # 按输入顺序返回向量
    embeddings = [d.embedding for d in response.data]
    return embeddings


def embed_single(text: str) -> list[float]:
    """对单个文本进行 embedding，返回 1024 维向量。"""
    return embed([text])[0]
