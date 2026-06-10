"""new-api 接口 SDK 封装

对 new-api / one-api 风格 LLM 网关接口的常用方法做了一层薄封装，
全部方法为异步方法，便于在 AstrBot 之类的异步环境中直接 await。

使用示例::

    async with NewAPISDK("https://api.example.com", "your-token", user_id=1) as sdk:
        # 拉最近 20 条日志
        logs = await sdk.get_logs(page_size=20, start_timestamp=1780761600)
        # 查看当前用户余额 / 额度
        me = await sdk.get_user_self()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

import httpx


logger = logging.getLogger(__name__)


class NewAPIError(Exception):
    """new-api 接口调用异常"""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class NewAPISDK:
    """new-api 接口 SDK

    实例化时传入 ``base_url`` 和 ``token`` 即可使用。``user_id`` 对应
    ``New-Api-User`` 请求头（默认 1，与 new-api 管理员接口习惯一致）。
    支持 ``async with`` 上下文管理，也支持手动 ``await sdk.close()``。
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        user_id: int = 1,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
    ) -> None:
        """
        Args:
            base_url: API 基础地址，例如 ``https://api.example.com``
            token: 认证 Token（Bearer Token）
            user_id: 用户 ID，对应 ``New-Api-User`` 请求头
            timeout: 单次请求超时时间（秒）
            max_retries: 请求失败时的最大重试次数
            backoff: 重试退避基数（秒），实际按 ``backoff * 2 ** attempt`` 退避
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.user_id = user_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

        self._client: Optional[httpx.AsyncClient] = None

    # ---------- 生命周期 ----------

    async def __aenter__(self) -> "NewAPISDK":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ---------- 内部工具 ----------

    def _build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "New-Api-User": str(self.user_id),
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """统一请求方法。出错时自动重试，最终抛出 :class:`NewAPIError`。"""
        url = self._build_url(path)
        client = await self._ensure_client()

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=self._build_headers(headers),
                )
                text = resp.text
                try:
                    payload: Any = resp.json()
                except Exception:
                    payload = {"raw": text}

                if resp.status_code >= 400:
                    message = None
                    if isinstance(payload, dict):
                        message = (
                            payload.get("message")
                            or payload.get("error")
                            or payload.get("msg")
                            or payload.get("detail")
                        )
                    if not message:
                        message = text or f"HTTP {resp.status_code}"
                    raise NewAPIError(
                        f"new-api 请求失败: {message}",
                        status_code=resp.status_code,
                        response=payload if isinstance(payload, dict) else {"data": payload},
                    )

                if not isinstance(payload, dict):
                    return {"data": payload}
                return payload

            except httpx.HTTPError as e:
                last_exc = e
                logger.warning("new-api 请求异常 (第 %d 次): %s", attempt + 1, e)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.backoff * (2 ** attempt))
            except NewAPIError:
                # 业务错误（4xx/5xx）直接抛出，不再重试
                raise

        raise NewAPIError(f"new-api 请求失败: {last_exc}") from last_exc

    # ================== 日志相关 ==================

    async def get_logs(
        self,
        *,
        page: int = 0,
        page_size: int = 20,
        type: int = 0,
        username: str = "",
        token_name: str = "",
        model_name: str = "",
        start_timestamp: int = 0,
        end_timestamp: int = 0,
        channel: Optional[int] = None,
        group: str = "",
        request_id: str = "",
    ) -> Dict[str, Any]:
        """获取请求日志

        Args:
            page: 页码（从 0 开始）
            page_size: 每页条数
            type: 日志类型（0:全部 1:充值 2:消费 3:管理 4:系统）
            username: 用户名模糊匹配
            token_name: Token 名模糊匹配
            model_name: 模型名模糊匹配
            start_timestamp: 起始时间戳（秒）
            end_timestamp: 结束时间戳（秒）
            channel: 渠道 ID
            group: 用户组
            request_id: 请求 ID
        """
        params: Dict[str, Any] = {
            "p": page,
            "page_size": page_size,
            "type": type,
        }
        for key, value in (
            ("username", username),
            ("token_name", token_name),
            ("model_name", model_name),
            ("start_timestamp", start_timestamp or None),
            ("end_timestamp", end_timestamp or None),
            ("channel", channel),
            ("group", group),
            ("request_id", request_id),
        ):
            if value not in (None, ""):
                params[key] = value
        return await self._request("GET", "/api/log/", params=params)

    # ================== 用户相关 ==================

    async def get_user_self(self) -> Dict[str, Any]:
        """获取当前登录用户信息（含余额 / 额度等）"""
        return await self._request("GET", "/api/user/self")

    async def get_user_list(
        self,
        *,
        page: int = 0,
        page_size: int = 100,
        keyword: str = "",
    ) -> Dict[str, Any]:
        """获取用户列表（需要管理员权限）"""
        params: Dict[str, Any] = {"p": page, "page_size": page_size}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/api/user/", params=params)

    async def get_user(self, user_id: int) -> Dict[str, Any]:
        """获取指定用户详情"""
        return await self._request("GET", f"/api/user/{user_id}")

    async def update_user_status(self, user_id: int, status: int) -> Dict[str, Any]:
        """更新用户状态（1:启用 2:禁用）"""
        return await self._request(
            "PUT",
            "/api/user/status",
            json={"id": user_id, "status": status},
        )

    # ================== Token 相关 ==================

    async def get_tokens(
        self,
        *,
        page: int = 0,
        page_size: int = 100,
        keyword: str = "",
    ) -> Dict[str, Any]:
        """获取 Token 列表"""
        params: Dict[str, Any] = {"p": page, "page_size": page_size}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/api/token/", params=params)

    async def get_token(self, token_id: int) -> Dict[str, Any]:
        """获取指定 Token 详情"""
        return await self._request("GET", f"/api/token/{token_id}")

    # ================== 渠道相关 ==================

    async def get_channels(
        self,
        *,
        page: int = 0,
        page_size: int = 100,
        keyword: str = "",
    ) -> Dict[str, Any]:
        """获取渠道列表"""
        params: Dict[str, Any] = {"p": page, "page_size": page_size}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/api/channel/", params=params)

    # ================== 模型相关 ==================

    async def get_models(self) -> Union[Dict[str, Any], List[Any]]:
        """获取可用模型列表"""
        return await self._request("GET", "/api/models/")

    # ================== 仪表盘统计 ==================

    async def get_dashboard(self) -> Dict[str, Any]:
        """获取仪表盘统计信息（需要管理员权限）"""
        return await self._request("GET", "/api/dashboard")

    # ================== 服务状态 ==================

    async def get_status(self) -> Dict[str, Any]:
        """获取服务运行状态"""
        return await self._request("GET", "/api/status")

    # ================== 通用方法 ==================

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
    ) -> Dict[str, Any]:
        """通用请求方法，可用于调用未封装的接口。"""
        return await self._request(method, path, params=params, json=json, data=data)
