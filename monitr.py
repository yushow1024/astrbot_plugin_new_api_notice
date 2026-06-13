"""new-api 日志监控与消息提醒

原始数据样本（取自 new-api /api/log/ 接口 ``data`` 数组中的典型条目）::

    {
        "items": [
            {
                "id": 65368,
                "user_id": 1,
                "created_at": 1781100011,
                "type": 2,
                "content": "",
                "username": "admin",
                "token_name": "openclaw",
                "model_name": "MiniMax-M2.7",
                "quota": 15096,
                "prompt_tokens": 167999,
                "completion_tokens": 174,
                "use_time": 7,
                "is_stream": false,
                "channel": 1,
                "channel_name": "MiniMax",
                "token_id": 68,
                "group": "default",
                "ip": "",
                "request_id": "202606101400042055565918268d9d6UPZ2Wdqi",
                "other": "{\"admin_info\":{\"use_channel\":[\"1\"]},\"billing_source\":\"wallet\",...,\"frt\":-1000,...}"
            }
        ]
    }

字段说明：

* ``is_stream`` - 是否流式请求（``True`` / ``False``）
* ``use_time`` - 总用时，单位秒
* ``other.frt`` - 首字用时（毫秒），``frt / 1000`` 即秒；保留一位小数、四舍五入
* ``type`` - 日志类型：``1`` 充值，``2`` 消费，``3`` 管理，``4`` 系统，``5`` 错误

提醒规则：

调用 :func:`fetch_notice_messages` 时会拉取一次日志，然后逐条过滤：

* ``type == 1``（充值）：始终提醒
* ``type == 2``（消费）：仅在 ``is_stream and frt > 60`` 或 ``not is_stream and use_time > 60`` 时提醒
* ``type in (3, 4, 5)``：始终提醒

命中时返回按行美化的纯文本消息（每条日志一段），未命中则返回空列表。
"""

from __future__ import annotations

import json
import sys
import time
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from astrbot.api import logger

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型注解
    from new_api_sdk import NewAPISDK


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 提醒阈值（秒）
SLOW_REQUEST_THRESHOLD_SECONDS: float = 60.0

# 已提醒日志 ID 缓冲区长度。超过此长度时最旧的一条自动出队（FIFO）。
NOTIFIED_LOG_BUFFER_SIZE: int = 100

# 已提醒过的日志 ID 队列。``deque(maxlen=...)`` 满时自动丢弃最左侧元素，
# 用于在进程内防止同一条日志被重复提醒。
# 日志 ID 在 new-api 中是 int，但为安全起见统一存为 str。
NOTIFIED_LOG_IDS: "deque[str]" = deque(maxlen=NOTIFIED_LOG_BUFFER_SIZE)

# 日志类型 -> 友好名称
TYPE_NAMES: Dict[int, str] = {
    1: "充值",
    2: "消费",
    3: "管理",
    4: "系统",
    5: "错误",
}

# 类型对应的图标
TYPE_ICONS: Dict[int, str] = {
    1: "💰",
    2: "🪙",
    3: "🛠️",
    4: "📢",
    5: "❌",
}


# 内置示例数据（来自 new-api 真实响应），便于离线调试与单元测试
SAMPLE_LOG_RESPONSE: Dict[str, Any] = {
    "items": [
        {
            "id": 65368,
            "user_id": 1,
            "created_at": 1781100011,
            "type": 2,
            "content": "",
            "username": "admin",
            "token_name": "openclaw",
            "model_name": "MiniMax-M2.7",
            "quota": 15096,
            "prompt_tokens": 167999,
            "completion_tokens": 174,
            "use_time": 7,
            "is_stream": False,
            "channel": 1,
            "channel_name": "MiniMax",
            "token_id": 68,
            "group": "default",
            "ip": "",
            "request_id": "202606101400042055565918268d9d6UPZ2Wdqi",
            "other": (
                "{\"admin_info\":{\"use_channel\":[\"1\"]},\"billing_source\":\"wallet\","
                "\"cache_ratio\":0.28,\"cache_tokens\":164411,\"completion_ratio\":4,"
                "\"frt\":-1000,\"group_ratio\":0.4,\"model_price\":-1,"
                "\"model_ratio\":0.75,\"request_conversion\":[\"OpenAI Compatible\"],"
                "\"request_path\":\"/v1/chat/completions\","
                "\"user_group_ratio\":-1}"
            ),
        },
        {
            "id": 65367,
            "user_id": 77,
            "created_at": 1781099996,
            "type": 2,
            "content": "",
            "username": "zhutao",
            "token_name": "星枢",
            "model_name": "claude-opus-4-8",
            "quota": 57978,
            "prompt_tokens": 74792,
            "completion_tokens": 279,
            "use_time": 28,
            "is_stream": True,
            "channel": 24,
            "channel_name": "llm-default-claude",
            "token_id": 36,
            "group": "default",
            "ip": "",
            "request_id": "202606101359286543046128268d9d6DrWy4wEc",
            "other": (
                "{\"admin_info\":{\"is_multi_key\":true,\"multi_key_index\":0,"
                "\"use_channel\":[\"24\"]},\"billing_source\":\"wallet\","
                "\"cache_creation_ratio\":1.25,\"cache_creation_ratio_5m\":1.25,"
                "\"cache_creation_tokens\":464,\"cache_creation_tokens_5m\":464,"
                "\"cache_ratio\":0.1,\"cache_tokens\":5368,\"cache_write_tokens\":464,"
                "\"claude\":true,\"completion_ratio\":5,\"frt\":26912,\"group_ratio\":0.3,"
                "\"model_price\":-1,\"model_ratio\":2.5,"
                "\"request_conversion\":[\"OpenAI Compatible\",\"Claude Messages\"],"
                "\"request_path\":\"/v1/chat/completions\","
                "\"stream_status\":{\"end_reason\":\"eof\",\"status\":\"ok\"},"
                "\"usage_semantic\":\"anthropic\",\"user_group_ratio\":0.3}"
            ),
        },
        {
            "id": 5610,
            "user_id": 82,
            "created_at": 1778564609,
            "type": 3,
            "content": "管理员增加用户额度 ＄10.000000 额度",
            "username": "zhangyuan",
            "token_name": "",
            "model_name": "",
            "quota": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "use_time": 0,
            "is_stream": False,
            "channel": 0,
            "channel_name": "",
            "token_id": 0,
            "group": "",
            "ip": "",
            "other": "{\"admin_info\":{\"admin_id\":1,\"admin_username\":\"admin\"}}",
        },
        {
            "id": 22152,
            "user_id": 6,
            "created_at": 1780106800,
            "type": 1,
            "content": "通过兑换码充值 ＄10.000000 额度，兑换码ID 5",
            "username": "yushow1024",
            "token_name": "",
            "model_name": "",
            "quota": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "use_time": 0,
            "is_stream": False,
            "channel": 0,
            "channel_name": "",
            "token_id": 0,
            "group": "",
            "ip": "",
            "other": "",
        },
    ]
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def parse_other(other: Any) -> Dict[str, Any]:
    """安全解析 ``other`` 字段（JSON 字符串）成字典。

    解析失败或字段为空时返回空字典，不抛出异常。
    """
    if not other:
        return {}
    if isinstance(other, dict):
        return other
    if isinstance(other, str):
        try:
            data = json.loads(other)
        except (ValueError, TypeError):
            logger.warning("解析日志 other 字段失败: %r", other)
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def get_first_token_latency(item: Dict[str, Any]) -> Optional[float]:
    """从日志条目中提取首字用时（秒，保留一位小数）。

    ``other.frt`` 字段是首字用时（毫秒）。如果小于等于 0 或不存在，返回 ``None``。
    """
    other = parse_other(item.get("other"))
    frt = other.get("frt")
    if not isinstance(frt, (int, float)) or frt <= 0:
        return None
    # 毫秒 -> 秒，保留一位小数、四舍五入
    return round(float(frt) / 1000.0, 1)


def format_timestamp(created_at: Any) -> str:
    """将秒级时间戳格式化为 ``YYYY-MM-DD HH:MM:SS``。"""
    try:
        ts = int(created_at)
    except (TypeError, ValueError):
        return str(created_at)
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def format_quota(quota: Any) -> str:
    """将 quota（1 quota = 0.000001 美元）格式化为带单位的易读字符串。"""
    if not isinstance(quota, (int, float)):
        return "-"
    # 1 美元 = 1_000_000 quota
    usd = float(quota) / 500_000.0
    return f"＄{usd:.6f}"


# ---------------------------------------------------------------------------
# 判断与格式化
# ---------------------------------------------------------------------------


def should_notify(item: Dict[str, Any]) -> bool:
    """根据规则判断该条日志是否需要发送提醒。

    * ``type == 1`` 充值 → True
    * ``type == 2`` 消费 → 流式首字用时 > 60s，或非流式总用时 > 60s
    * ``type in (3, 4, 5)`` → True
    * 其他类型 → False
    """
    log_type = item.get("type")
    if log_type in (1, 3, 4, 5):
        return True
    if log_type == 2:
        is_stream = bool(item.get("is_stream"))
        if is_stream:
            frt = get_first_token_latency(item)
            return frt is not None and frt > SLOW_REQUEST_THRESHOLD_SECONDS
        use_time = item.get("use_time") or 0
        return use_time > SLOW_REQUEST_THRESHOLD_SECONDS
    return False


def format_notice_message(item: Dict[str, Any]) -> str:
    """把单条日志格式化为一段易读的多行消息。"""
    log_type = item.get("type")
    icon = TYPE_ICONS.get(log_type, "ℹ️")
    type_name = TYPE_NAMES.get(log_type, f"未知({log_type})")

    lines: List[str] = []
    lines.append(
        f"{icon} 【{type_name}】"
        f"  #{item.get('id', '-')}"
        f"  {format_timestamp(item.get('created_at'))}"
    )

    username = item.get("username") or "-"
    user_id = item.get("user_id")
    lines.append(f"  👤 用户：{username} (id={user_id})")

    # 消费、错误 类日志展示 token / 模型
    if log_type in (2, 5):
        token_name = item.get("token_name") or "-"
        model_name = item.get("model_name") or "-"
        channel_name = item.get("channel_name") or "-"
        is_stream = bool(item.get("is_stream"))

        lines.append(f"  🔑 Token：{token_name}  ｜  🤖 模型：{model_name}")
        lines.append(
            f"  📡 渠道：{channel_name}  ｜  "
            f"模式：{'流式' if is_stream else '非流式'}"
        )

    # 消费类日志展示 用时 / 额度
    if log_type == 2:
        use_time = item.get("use_time") or 0
        frt = get_first_token_latency(item)

        lines.append(
            f"  ⏱️ 用时：{use_time}s"
            + (f"  ｜  首字：{frt}s" if frt is not None else "")
        )
        prompt_tokens = item.get("prompt_tokens") or 0
        completion_tokens = item.get("completion_tokens") or 0
        lines.append(
            f"  📊 Tokens：prompt={prompt_tokens}, completion={completion_tokens}"
        )
        lines.append(f"  💸 消耗：{format_quota(item.get('quota'))}")

    # 说明
    content = (item.get("content") or "").strip()
    if content:
        lines.append(f"  📝 说明：{content}")

    request_id = item.get("request_id")
    if request_id:
        lines.append(f"  🆔 请求：{request_id}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 对外主入口
# ---------------------------------------------------------------------------


def extract_log_items(payload: Any) -> List[Dict[str, Any]]:
    """从 ``get_logs`` 的响应中抽取日志条目列表。

    不同版本 new-api 字段略有差异：``data`` 可能是直接数组，
    也可能是 ``{"items": [...], "total": ...}`` 这样的结构。
    """
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    items = payload.get("items")

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]

    # 兜底：有些实现里 data 是 dict，再嵌一层
    if isinstance(data, dict):
        nested_items = data.get("items")
        if isinstance(nested_items, list):
            return [item for item in nested_items if isinstance(item, dict)]

    return []


async def fetch_notice_messages(
    sdk: "NewAPISDK",
    *,
    page: int = 0,
    page_size: int = 20,
    start_timestamp: int = 0,
    end_timestamp: int = 0,
    max_items: Optional[int] = None,
) -> List[str]:
    """拉取一次 new-api 日志，按规则过滤并返回美化后的消息列表。

    Args:
        sdk: 已经初始化好的 :class:`NewAPISDK` 实例。
        page: 日志页码。
        page_size: 每页条数。
        start_timestamp: 起始时间戳（秒），0 表示不限制。
        end_timestamp: 结束时间戳（秒），0 表示不限制。
        max_items: 最多处理多少条日志，避免一次提醒过多。

    Returns:
        需要发送的提醒消息列表（每条对应一行原始日志）。
        如果没有命中规则则返回空列表。
    """
    payload = await sdk.get_logs(
        page=page,
        page_size=page_size,
        type=0,  # 拉全部类型
        start_timestamp=start_timestamp or 0,
        end_timestamp=end_timestamp or 0,
    )

    items = extract_log_items(payload)
    if max_items is not None and max_items > 0:
        items = items[:max_items]

    messages: List[str] = []
    for item in items:
        # 进程内去重：同一条日志只在首次出现时提醒。
        # 日志 ID 统一转成 str 后再比对，避免 int / str 混存导致漏判。
        raw_id = item.get("id")
        if raw_id is None:
            continue
        log_id = str(raw_id)
        if log_id in NOTIFIED_LOG_IDS:
            continue
        if not should_notify(item):
            continue
        try:
            messages.append(format_notice_message(item))
        except Exception:  # noqa: BLE001
            logger.exception("格式化日志提醒失败，跳过该项: %r", item)
            continue
        # 成功生成提醒消息后才记录 ID，避免格式化失败时占用缓冲区。
        NOTIFIED_LOG_IDS.append(log_id)
    return messages


__all__ = [
    "SLOW_REQUEST_THRESHOLD_SECONDS",
    "NOTIFIED_LOG_BUFFER_SIZE",
    "NOTIFIED_LOG_IDS",
    "SAMPLE_LOG_RESPONSE",
    "TYPE_NAMES",
    "TYPE_ICONS",
    "parse_other",
    "get_first_token_latency",
    "format_timestamp",
    "format_quota",
    "should_notify",
    "format_notice_message",
    "extract_log_items",
    "fetch_notice_messages",
    "demo",
]


# ---------------------------------------------------------------------------
# 离线演示入口
# ---------------------------------------------------------------------------


def demo() -> int:
    """用内置 :data:`SAMPLE_LOG_RESPONSE` 演示筛选与格式化。

    不会发起任何网络请求。可通过 ``python monitr.py`` 直接运行。
    """
    # Windows 默认 GBK 控制台无法打印 emoji，这里做一次 utf-8 重配。
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

    items = extract_log_items(SAMPLE_LOG_RESPONSE)

    # 额外补两个合成用例：消费类慢请求（流式 frt>60s、非流式 use_time>60s）
    items = list(items) + [
        {
            "id": 99001,
            "user_id": 1,
            "created_at": int(time.time()),
            "type": 2,
            "content": "",
            "username": "slow_stream",
            "token_name": "demo",
            "model_name": "claude-opus-4-8",
            "quota": 100000,
            "prompt_tokens": 1024,
            "completion_tokens": 16,
            "use_time": 75,
            "is_stream": True,
            "channel": 1,
            "channel_name": "demo-channel",
            "token_id": 1,
            "group": "default",
            "ip": "",
            "request_id": "demo-slow-stream",
            "other": json.dumps({"frt": 72500, "model_ratio": 2.5}),
        },
        {
            "id": 99002,
            "user_id": 1,
            "created_at": int(time.time()),
            "type": 2,
            "content": "",
            "username": "slow_nonstream",
            "token_name": "demo",
            "model_name": "MiniMax-M2.7",
            "quota": 50000,
            "prompt_tokens": 256,
            "completion_tokens": 32,
            "use_time": 90,
            "is_stream": False,
            "channel": 1,
            "channel_name": "demo-channel",
            "token_id": 1,
            "group": "default",
            "ip": "",
            "request_id": "demo-slow-nonstream",
            "other": json.dumps({"frt": -1000, "model_ratio": 1.0}),
        },
    ]
    if not items:
        logger.warning("示例数据中没有日志条目。")
        return 1

    logger.info(f"=== 共 {len(items)} 条日志，命中提醒的如下 ===")
    hit = 0
    for item in items:
        log_id = item.get("id", "-")
        log_type = item.get("type")
        # 显式收窄到 int，再传给 Dict[int, str].get
        if isinstance(log_type, int):
            type_name = TYPE_NAMES.get(log_type, f"未知({log_type})")
        else:
            type_name = f"未知({log_type})"
        is_stream = bool(item.get("is_stream"))
        frt = get_first_token_latency(item)
        use_time = item.get("use_time")
        reason = should_notify(item)
        logger.info(
            f"[{log_id}] type={log_type}({type_name}) "
            f"is_stream={is_stream} use_time={use_time} frt={frt} -> "
            f"{'提醒' if reason else '忽略'}"
        )
        if reason:
            logger.info("-" * 40)
            logger.info(format_notice_message(item))
            logger.info("-" * 40)
            hit += 1
    logger.info(f"=== 命中 {hit} 条 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(demo())
