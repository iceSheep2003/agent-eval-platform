"""记忆检索：**纯函数、无 IO**，便于穷举测试。

中文没有空格，不能按词切。这里按「单字 + 二元组」建词项：单字保证召回，
二元组保证精度。对客服这类短文本足够，且零依赖。
"""

from __future__ import annotations

from typing import Sequence


def tokenize(text: str) -> set[str]:
    """切出检索词项：中文单字与二元组，拉丁词按空格切。"""
    lowered = text.lower()
    terms: set[str] = set()
    latin: list[str] = []
    for char in lowered:
        if char.isalnum() and ord(char) < 128:
            latin.append(char)
            continue
        if latin:
            terms.add("".join(latin))
            latin = []
        if not char.isspace():
            terms.add(char)
    if latin:
        terms.add("".join(latin))

    # 中文二元组：在连续的非 ASCII 串上取相邻两字
    run: list[str] = []
    for char in lowered:
        if char.isalnum() and ord(char) >= 128:
            run.append(char)
        else:
            terms.update(_bigrams(run))
            run = []
    terms.update(_bigrams(run))
    return {term for term in terms if term}


def _bigrams(run: Sequence[str]) -> set[str]:
    return {run[index] + run[index + 1] for index in range(len(run) - 1)}


#: 标识符权重。**订单号、工单号这类精确匹配是决定性的**——
#: 用户写下 "A001" 就是在指定对象，不能被「退款」这种通用词的命中盖过去。
#: 这正是实测踩到的坑：查「A001 的退款情况」，A002 因为含「退款」排在前面。
_IDENTIFIER_WEIGHT = 5.0


def _weight(term: str) -> float:
    if len(term) >= 3 and any(char.isdigit() for char in term):
        return _IDENTIFIER_WEIGHT
    return 2.0 if len(term) > 1 else 1.0


def score(query_terms: set[str], entry_terms: Sequence[str]) -> float:
    """重叠度，按词项具体程度加权后归一化到 0–1。"""
    if not query_terms:
        return 0.0
    entry = set(entry_terms)
    hits = query_terms & entry
    if not hits:
        return 0.0
    total = sum(_weight(term) for term in query_terms)
    return sum(_weight(term) for term in hits) / total if total else 0.0
