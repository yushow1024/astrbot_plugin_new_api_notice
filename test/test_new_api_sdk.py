"""new_api_sdk 测试用例

直接调用 SDK 真实接口的集成测试，不依赖 pytest / pytest-asyncio，
可使用 ``python -m test.test_new_api_sdk`` 或
``python test/test_new_api_sdk.py`` 直接执行。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 让脚本既能被 ``python -m test.test_new_api_sdk`` 运行，
# 也能被 ``python test/test_new_api_sdk.py`` 直接运行。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from new_api_sdk import NewAPISDK  # noqa: E402
else:
    from ..new_api_sdk import NewAPISDK  # noqa: E402


BASE_URL = "https://api.cerebrumiq.top"
TOKEN = "9IFhGxOioOKs1RQblcDDG/0Umo6/"


async def test_get_logs() -> dict:
    """调用 ``get_logs`` 拉取最近若干条请求日志。

    使用最近 7 天的时间窗口（秒级时间戳），并限制 ``page_size = 5``
    以避免拉取过多数据。
    """
    import time

    end_timestamp = int(time.time())
    start_timestamp = end_timestamp - 7 * 24 * 60 * 60  # 最近 7 天

    async with NewAPISDK(BASE_URL, TOKEN, user_id=1) as sdk:
        result = await sdk.get_logs(
            page=0,
            page_size=5,
            type=0,            # 0:全部
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    # ---- 基本断言 ----
    assert isinstance(result, dict), f"期望返回 dict, 实际得到 {type(result).__name__}"

    # new-api / one-api 风格接口通用字段: success / data / message
    # 视具体实现,这里只做宽松校验
    print("=== get_logs 返回结果 ===")
    for key, value in result.items():
        if key == "data" and isinstance(value, list):
            print(f"{key}: list[{len(value)}]")
            for i, item in enumerate(value[:3]):
                print(f"  [{i}] {item}")
            if len(value) > 3:
                print(f"  ... 共 {len(value)} 条")
        else:
            print(f"{key}: {value}")

    assert "success" in result or "data" in result, (
        f"返回结果缺少 success / data 字段: {result}"
    )
    return result


async def _async_main() -> int:
    try:
        await test_get_logs()
    except AssertionError as e:
        print(f"\n[FAIL] {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\n[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print("\n[PASS] test_get_logs")
    return 0


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
