"""可追溯的本地 FAQ：型号硬过滤、同义词分类和纯 Python BM25，无向量数据库。"""

import json
import math
import re
from collections import Counter

from react_agent import storage

SYNONYMS = {
    "bluetooth": ["蓝牙", "配对", "bluetooth", "搜索不到", "搜不到", "配不上"],
    "network": ["联网", "连不上网", "网络", "wifi", "wi-fi", "断网"],
    "power": ["开不了机", "无法开机", "不开机", "不亮", "没反应", "电源"],
    "offline": ["离线", "掉线", "offline"],
    "charging": ["充电", "电池", "充不进电"],
    "screen": ["屏幕", "花屏", "竖线"],
    "shipping": ["物流", "快递", "配送"],
    "warranty": ["保修", "质保"],
    "safety": ["冒烟", "起火", "漏电", "烧焦"],
}


# 函数说明：classify_issue
# 功能：按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。
# 内部调用：
#   - text.casefold()：进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。
#   - any()：检查是否至少有一项符合条件；全部不符合或序列为空时返回 False。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
#   - SYNONYMS.items()：遍历键和值的配对，供参数整理、过滤条件或字段展示使用。
#   - max()：选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。
# 间接调用 / 回调：
#   - scores.get：由 max 调用/注册：按映射返回对应值；这里用于显示名称或评分选择，而不是立即主动调用。
def classify_issue(text: str) -> str:
    """按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。"""
    query = text.casefold()
    if any(term in query for term in SYNONYMS["safety"]):
        return "safety"
    scores = {
        kind: sum(term in query for term in terms) for kind, terms in SYNONYMS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "other"


# 函数说明：model_in
# 功能：用正则提取明确型号；多个不同型号时返回 None，要求调用者追问。
# 内部调用：
#   - text.upper()：把字母转为大写，统一设备型号或错误码。
#   - re.findall()：提取所有匹配项，形成设备型号、英文词或中文片段列表。
#   - re.fullmatch()：要求整段文本符合正则；用于账号/编号校验或排除工单编号被误当设备型号。
#   - dict.fromkeys()：用字典键的唯一性去重并保留首次出现顺序，随后可转回列表。
#   - list()：把迭代器或集合展开成列表，或复制列表以便收集后续结果。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
def model_in(text: str) -> str | None:
    """用正则提取明确型号；多个不同型号时返回 None，要求调用者追问。"""
    models = list(
        dict.fromkeys(
            value
            for value in re.findall(
                r"(?<![A-Z0-9])[A-Z]{1,8}\d{2,8}(?![A-Z0-9])", text.upper()
            )
            if not re.fullmatch(r"T\d+", value)
        )
    )
    return models[0] if len(models) == 1 else None


# 函数说明：tokenize
# 功能：用正则产生英文词和中文双字片段，供 BM25 做本地全文排序。
# 内部调用：
#   - text.casefold()：进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。
#   - re.findall()：提取所有匹配项，形成设备型号、英文词或中文片段列表。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - max()：选择最大值；可以配合 key 按分数选类别，也用于设置数量下限。
#   - range()：产生整数序列，供有界重试、模拟轮次或并发任务循环使用。
#   - tokens.extend()：把另一序列的每个元素追加到列表，合并消息或分词结果。
def tokenize(text: str) -> list[str]:
    """用正则产生英文词和中文双字片段，供 BM25 做本地全文排序。"""
    text = text.casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    for span in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.extend(span[i : i + 2] for i in range(max(1, len(span) - 1)))
    return tokens


# 函数说明：bm25
# 功能：调用 tokenize/Counter/log 计算 BM25；只在已经按型号过滤的资料中排序。
# 内部调用：
#   - tokenize()：用正则产生英文词和中文双字片段，供 BM25 做本地全文排序。
#   - Counter()：统计每个词/片段的出现频次，形成 BM25 的文档词频。
#   - bag.values()：遍历映射里的所有值，供求和、校验或 SQL 参数整理使用。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - set()：构造不重复元素集合，用于检查未知参数、工具配对或唯一查询词。
#   - math.log()：计算 BM25 逆文档频率中的自然对数，让较少见的查询词获得更高区分度。
#   - enumerate()：遍历时同时提供序号和元素，便于给工具调用、轮次或时间线编号。
def bm25(query: str, documents: list[str]) -> list[float]:
    """调用 tokenize/Counter/log 计算 BM25；只在已经按型号过滤的资料中排序。"""
    bags = [Counter(tokenize(doc)) for doc in documents]
    if not bags:
        return []
    average = sum(sum(bag.values()) for bag in bags) / len(bags) or 1
    scores = [0.0] * len(bags)
    for word in set(tokenize(query)):
        count = sum(word in bag for bag in bags)
        inverse = math.log(1 + (len(bags) - count + 0.5) / (count + 0.5))
        for index, bag in enumerate(bags):
            frequency = bag[word]
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * sum(bag.values()) / average
            )
            scores[index] += inverse * frequency * 2.5 / (denominator or 1)
    return scores


# 函数说明：search
# 功能：调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。
# 内部调用：
#   - isinstance()：判断对象是否属于指定类型，避免把错误类型当成消息、字符串或预期异常处理。
#   - len()：取得字符串、列表或字典的长度，用于长度限制、数量统计或测试断言。
#   - storage.result()：统一结果格式；保留旧版 ok/error，新增 success/error_code/retryable。
#   - model_in()：用正则提取明确型号；多个不同型号时返回 None，要求调用者追问。
#   - device_model.upper()：把字母转为大写，统一设备型号或错误码。
#   - (device_model or explicit or '').strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - (device_model or explicit or '').strip(...).upper()：把字母转为大写，统一设备型号或错误码。
#   - classify_issue()：按 SYNONYMS 统计故障词；无明确证据返回 other，含糊的‘连不上’不擅自认定蓝牙。
#   - query.strip()：去除文本两端空白，规范输入或判断是否只含空白。
#   - (storage.ROOT / 'data/faq.json').read_text()：读取 UTF-8 文本，供解析 FAQ 或固定评测用例。
#   - json.loads()：把 JSON 文本还原为字典/列表；不把其中的文本作为程序执行。
#   - 字符串.join()：以当前字符串为分隔符连接多个文本，生成展示文案或仅含可信列名的 SQL 结构。
#   - bm25()：调用 tokenize/Counter/log 计算 BM25；只在已经按型号过滤的资料中排序。
#   - zip()：把多个序列按位置配对，关联候选文档与分数或统计列与状态。
#   - word.casefold()：进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。
#   - query.casefold()：进行适合大小写无关比较的文本归一化，兼容英文关键词/证据检查。
#   - sum()：累加数值；对布尔表达式累加时，True 按 1 计数。
#   - round()：按指定小数位四舍五入，使相似度、费用或耗时便于展示。
#   - ranked.append()：把一个元素追加到当前列表尾部，收集消息、条件、结果或审计展示内容。
#   - sorted()：返回按默认次序或 key 规则排好的新列表，不原地修改原列表。
#   - all()：检查是否每项都符合条件；用于汇总断言、调用成功或步骤耗尽状态。
# 匿名函数：
#   - lambda entry: -entry['score']：由 sorted 的 key 调用，返回负分数，让检索结果按分数从高到低排列。
def search(
    query: str,
    device_model: str | None = None,
    issue_type: str | None = None,
    tried_steps: list[str] | None = None,
    entries=None,
) -> dict:
    """调用 model_in/classify_issue/bm25：型号先过滤，返回编号、来源和未尝试步骤；无资料明确失败。"""
    if not isinstance(query, str) or len(query) > 2000:
        return storage.result(
            "search_faq", False, "invalid_fields", "查询限 2000 字。", matches=[]
        )
    explicit = model_in(query)
    if device_model and explicit and device_model.upper() != explicit:
        return storage.result(
            "search_faq",
            False,
            "model_conflict",
            "问题中的型号与检索参数不一致，请核对。",
            matches=[],
        )
    device_model = (device_model or explicit or "").strip().upper()
    if not device_model:
        return storage.result(
            "search_faq",
            False,
            "missing_model",
            "请先提供设备型号，以免引用其他型号的步骤。",
            matches=[],
        )
    issue_type = (
        issue_type if issue_type and issue_type != "other" else classify_issue(query)
    )
    if issue_type == "other" and query.strip() in {
        "连不上",
        "无法连接",
        "连接失败",
        "坏了",
        "怎么办",
    }:
        return storage.result(
            "search_faq",
            False,
            "missing_issue",
            "请说明是蓝牙、网络还是其他功能出现故障。",
            matches=[],
        )
    if issue_type not in {*SYNONYMS, "other"}:
        return storage.result(
            "search_faq", False, "invalid_issue_type", "故障类别无效。", matches=[]
        )
    entries = (
        entries
        if entries is not None
        else json.loads((storage.ROOT / "data/faq.json").read_text())
    )
    candidates = [
        entry
        for entry in entries
        if device_model in entry["product_models"]
        and (issue_type == "other" or entry["issue_type"] == issue_type)
    ]
    scores = bm25(
        query,
        [entry["question"] + " " + " ".join(entry["keywords"]) for entry in candidates],
    )
    ranked = []
    for entry, score in zip(candidates, scores):
        hits = sum(word.casefold() in query.casefold() for word in entry["keywords"])
        if (
            hits
            or score > 0.8
            or (issue_type != "other" and entry["issue_type"] == issue_type)
        ):
            tried = tried_steps or []
            remaining = [
                step
                for step in entry["steps"]
                if step["id"] not in tried and step["text"] not in tried
            ]
            ranked.append(
                {**entry, "remaining_steps": remaining, "score": round(score + hits, 4)}
            )
    matches = sorted(ranked, key=lambda entry: -entry["score"])[:3]
    if not matches:
        return storage.result(
            "search_faq",
            False,
            "no_matching_faq",
            f"目前没有找到适用于 {device_model} 的对应说明，不能套用其他型号的步骤。可补充故障或申请售后。",
            device_model=device_model,
            issue_type=issue_type,
            matches=[],
        )
    return storage.result(
        "search_faq",
        device_model=device_model,
        issue_type=issue_type,
        matches=matches,
        exhausted=all(not entry["remaining_steps"] for entry in matches),
    )
