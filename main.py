import asyncio
import time
from functools import partial
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from astrbot.api import logger
from astrbot.api.event import MessageChain, filter
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .monitr import fetch_notice_messages
from .new_api_sdk import NewAPISDK


@register("helloworld", "YourName", "new-api 日志监控与消息提醒", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: Any | None = None):
        super().__init__(context, config)
        # 自行保存插件配置（_conf_schema.json 加载后的 AstrBotConfig）
        self.config = config
        self.scheduler = AsyncIOScheduler()
        self.job_id = "notice_job:"
        # 启动调度器
        self.scheduler.start()

        # 记录每个 umo 上一次抓到的日志 id，避免重复提醒
        self._last_seen_log_id: dict[str, int] = {}
        # SDK 实例缓存
        self._sdk: NewAPISDK | None = None
        self._sdk_lock = asyncio.Lock()

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    # 注册指令的装饰器。指令名为 helloworld。注册成功后，发送 `/helloworld` 就会触发这个指令，并回复 `你好, {user_name}!`
    @filter.command("helloworld")
    async def helloworld(self, event: AstrMessageEvent):
        """这是一个 hello world 指令""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
        user_name = event.get_sender_name()
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链 # from astrbot.api.message_components import *
        logger.info(message_chain)
        yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!") # 发送一条纯文本消息

    @filter.command("hello")
    async def hello(self, event: AstrMessageEvent):
        """Aloha!"""
        await self.put_kv_data("greeted", True)
        greeted = await self.get_kv_data("greeted", False)
        yield event.plain_result(greeted)
        await self.delete_kv_data("greeted")

    @filter.command("new_api_start_notice")
    async def start_notice(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin

        job_id = self.job_id + umo

        # 2. 检查是否已有该任务，避免重复添加
        if self.scheduler.get_job(job_id):
            yield event.plain_result("任务已在运行中，请勿重复启动。")
            return

        # 使用 partial 预绑定参数
        bound_task = partial(self.send_periodic_message, event)

        # 3. 添加一个每5秒执行一次的间隔任务 (使用 IntervalTrigger)
        self.scheduler.add_job(
            bound_task,
            trigger=IntervalTrigger(seconds=5),  # 关键：设置触发间隔为5秒
            id=job_id,
            replace_existing=True
        )

        yield event.plain_result("已启动每5秒发送消息的任务。")

        # notice_umos = await self.get_kv_data("notice_umos", None)
        # if notice_umos is None:
        #     notice_umos = set()
        # else:
        #     notice_umos = set(notice_umos)
        # notice_umos.add(umo)
        # await self.put_kv_data("notice_umos", list(notice_umos))
        message_chain = MessageChain().message("开启通知成功 umo:" + umo)
        await self.context.send_message(umo, message_chain)  # type: ignore[attr-defined]
        event.stop_event()

    @filter.command("new_api_stop_notice")
    async def stop_notice(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin

        job_id = self.job_id + umo

        try:
            # 方式1：只删除单个任务（推荐，调度器继续运行）
            self.scheduler.remove_job(job_id)
            yield event.plain_result("定时消息任务已停止")
        except Exception:
            yield event.plain_result("当前没有运行中的定时任务")

        # notice_umos = await self.get_kv_data("notice_umos", None)
        # if notice_umos is None:
        #     notice_umos = set()
        # else:
        #     notice_umos = set(notice_umos)
        # notice_umos.discard(umo)
        # await self.put_kv_data("notice_umos", list(notice_umos))
        message_chain = MessageChain().message("关闭通知成功 umo:" + umo)
        await self.context.send_message(umo, message_chain)  # type: ignore[attr-defined]
        event.stop_event()

    def _get_plugin_config(self) -> tuple[str | None, str | None]:
        """从插件配置中读取 base_url 和 token。

        配置来源是 ``_conf_schema.json``，由 StarManager 注入为 ``self.config``。
        """
        cfg = self.config
        base_url: str | None = None
        token: str | None = None
        if cfg is not None:
            try:
                base_url = cfg.get("base_url")  # type: ignore[attr-defined]
                token = cfg.get("token")  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                logger.exception("读取插件配置失败")
        return base_url, token

    async def _get_sdk(self) -> NewAPISDK | None:
        """根据插件配置创建（并缓存）NewAPISDK 实例。"""
        if self._sdk is not None:
            return self._sdk

        base_url, token = self._get_plugin_config()
        if not base_url or not token:
            logger.warning("未配置 base_url 或 token，无法启动 new-api 监控")
            return None

        async with self._sdk_lock:
            if self._sdk is not None:
                return self._sdk
            self._sdk = NewAPISDK(base_url=base_url, token=token, user_id=1)
            await self._sdk._ensure_client()
            return self._sdk

    async def send_periodic_message(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin
        try:
            sdk = await self._get_sdk()
            if sdk is None:
                return

            # 拉最近 5 分钟的日志，避免一次拉太多
            end_ts = int(time.time())
            start_ts = end_ts - 5 * 60

            messages = await fetch_notice_messages(
                sdk,
                page=0,
                page_size=20,
                start_timestamp=start_ts,
                end_timestamp=end_ts,
            )
            if not messages:
                return

            message_chain = MessageChain().message("\n\n".join(messages))
            await self.context.send_message(umo, message_chain)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            logger.exception("new-api 监控任务执行失败")
        finally:
            event.stop_event()

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        if self._sdk is not None:
            try:
                await self._sdk.close()
            except Exception:  # noqa: BLE001
                pass
            self._sdk = None
