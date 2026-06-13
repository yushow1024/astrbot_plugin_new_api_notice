# 📢 astrbot_plugin_new_api_notice

> 一个用于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的 [new-api](https://github.com/QuantumNous/new-api) / [one-api](https://github.com/songquanpeng/one-api) 日志监控与消息提醒插件。

定时拉取 new-api 的日志接口,自动把 **充值 / 慢请求 / 管理操作 / 系统消息 / 错误** 推送到指定的会话(QQ、Telegram、飞书、Discord 等 AstrBot 支持的所有平台),让你不打开后台也能第一时间感知 API 网关的动态。

---

## ✨ 功能特性

- 🔔 **多类型日志提醒**:覆盖 new-api 的 5 类日志(充值 / 消费 / 管理 / 系统 / 错误)
- 🐢 **慢请求自动捕获**:消费类日志中,流式请求 `首字用时 > 60s`、非流式 `总用时 > 60s` 自动告警
- 🎯 **会话级开关**:支持按会话(umo)独立启停,谁需要谁开
- 🔁 **进程内去重**:基于 FIFO 缓冲区(默认 100 条)防止同一条日志被重复提醒
- 🎨 **消息美化**:带 emoji 图标和分组展示,Token / 模型 / 渠道 / 用时 / 消耗一目了然
- ⚡ **异步 SDK**:基于 `httpx.AsyncClient` 封装,自带请求重试与退避
- 🧪 **可离线调试**:`monitr.py` 内置示例数据,`python monitr.py` 即可本地预览效果

---

## 📸 提醒效果预览

```
🪙 【消费】  #65367  2026-06-10 13:59:56
  👤 用户:xxx (id=1)
  🔑 Token:星枢  ｜  🤖 模型:claude-opus-4-8
  📡 渠道:xxx ｜  模式:流式
  ⏱️ 用时:28s  ｜  首字:26.9s
  📊 Tokens:prompt=74792, completion=279
  💸 消耗:＄0.057978
  🆔 请求:202606101359286543046128268d9d6DrWy4wEc

💰 【充值】  #22152  2026-05-30 16:46:40
  👤 用户:xxx (id=1)
  📝 说明:通过兑换码充值 ＄10.000000 额度,兑换码ID 5
```

---

## 📦 安装

### 方式一:从 AstrBot 插件市场安装(推荐)

在 AstrBot 管理面板的「插件市场」中搜索 `new_api_notice` 一键安装。

### 方式二:手动克隆

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/yushow1024/astrbot_plugin_new_api_notice.git
```

然后在 AstrBot 管理面板重启或重载插件即可。

### 依赖

- Python >= 3.12
- [`httpx`](https://www.python-httpx.org/) >= 0.28.1
- [`apscheduler`](https://apscheduler.readthedocs.io/)(AstrBot 已内置)

---

## ⚙️ 配置

插件首次加载后,会在 AstrBot 管理面板的「插件管理 → new_api_notice → 配置」中生成两个字段:

| 字段 | 说明 | 示例 |
| ---- | ---- | ---- |
| `base_url` | new-api 的基础 URL,**不要带末尾斜杠** | `https://api.example.com` |
| `token` | new-api 后台生成的 Token(具备查询日志权限) | `sk-xxxxxxxxxxxxxxxx` |

> ⚠️ Token 默认按 `New-Api-User: 1`(即管理员)发起请求,需要在 new-api 后台创建具有日志查询权限的 Token。

填写完成后保存,无需重启,下一次执行任务时即生效。

---

## 🚀 使用方法

在任意 AstrBot 接入的会话中(私聊 / 群聊均可)发送以下指令:

| 指令 | 说明 |
| ---- | ---- |
| `/new_api_start_notice` | 在 **当前会话** 启动 new-api 日志定时监控(默认每 5 秒拉取一次) |
| `/new_api_stop_notice` | 停止 **当前会话** 的监控任务 |

启动后,插件会按以下流程工作:

1. 每隔一段时间调用 `GET /api/log/` 拉取最近 5 分钟的日志
2. 根据规则过滤需要提醒的条目
3. 美化排版后推送到当前会话

---

## 🧠 提醒规则

| 日志类型 | type | 触发条件 |
| -------- | ---- | -------- |
| 💰 充值 | `1` | 始终提醒 |
| 🪙 消费 | `2` | 流式:`other.frt / 1000 > 60s`<br>非流式:`use_time > 60s` |
| 🛠️ 管理 | `3` | 始终提醒 |
| 📢 系统 | `4` | 始终提醒 |
| ❌ 错误 | `5` | 始终提醒 |

慢请求阈值由 [monitr.py](monitr.py) 中的常量控制,如需调整可自行修改:

```python
# 提醒阈值(秒)
SLOW_REQUEST_THRESHOLD_SECONDS: float = 60.0

# 已提醒日志 ID 缓冲区长度(用于去重)
NOTIFIED_LOG_BUFFER_SIZE: int = 100
```

---

## 🗂️ 项目结构

```
astrbot_plugin_new_api_notice/
├── main.py              # 插件入口,提供 start/stop 指令与定时调度
├── monitr.py            # 日志过滤、格式化与提醒规则
├── new_api_sdk.py       # new-api 接口 SDK 封装(异步)
├── _conf_schema.json    # 插件配置 schema(base_url / token)
├── metadata.yaml        # 插件元信息
├── pyproject.toml       # Python 项目依赖声明
└── test/
    └── test_new_api_sdk.py  # SDK 单元测试
```

---

## 🧪 本地调试

`monitr.py` 内置了一份真实样本数据 `SAMPLE_LOG_RESPONSE`,可以离线预览提醒效果:

```bash
python monitr.py
```

输出示例会列出所有命中规则的提醒文本,**不会发起任何网络请求**,便于在改规则、调格式时快速验证。

运行 SDK 的单元测试:

```bash
pytest test/
```

---

## 🛠️ 自定义扩展

[new_api_sdk.py](new_api_sdk.py) 已经封装了 new-api 的常用接口,你可以基于它快速实现更多玩法:

```python
from .new_api_sdk import NewAPISDK

async with NewAPISDK("https://api.example.com", "your-token", user_id=1) as sdk:
    # 查看自己的余额
    me = await sdk.get_user_self()

    # 拉日志
    logs = await sdk.get_logs(page_size=20, type=2)

    # 拉渠道列表
    channels = await sdk.get_channels()

    # 调用未封装的接口
    raw = await sdk.request("GET", "/api/some/path", params={"x": 1})
```

已封装的接口:

- 📜 日志:`get_logs`
- 👤 用户:`get_user_self` / `get_user_list` / `get_user` / `update_user_status`
- 🔑 Token:`get_tokens` / `get_token`
- 📡 渠道:`get_channels`
- 🤖 模型:`get_models`
- 📊 仪表盘:`get_dashboard`
- 💡 状态:`get_status`
- 🔌 通用:`request`

---

## ❓ FAQ

**Q1:启动后没有任何提醒?**
A:确认 `base_url` 不包含末尾 `/`,Token 在 new-api 后台具备「查询日志」权限,并且最近 5 分钟内确实有命中规则的日志(可去 new-api 后台对照查看)。

**Q2:为什么消费日志只在用时超过 60 秒才提醒?**
A:这是默认规则——只关心慢请求,避免高频消费日志把会话刷屏。如果想调整,修改 [monitr.py](monitr.py) 里的 `SLOW_REQUEST_THRESHOLD_SECONDS` 即可,或自行改写 `should_notify` 函数。

**Q3:多个会话同时开启会重复提醒吗?**
A:每个会话有独立的定时任务(以 umo 为 key),但去重缓冲区 `NOTIFIED_LOG_IDS` 是 **进程内全局共享** 的。也就是说,同一条日志只会在 **第一个** 抓到它的会话里被推送一次。这是为了避免广播相同日志,后续可按需改造为 per-umo 去重。

**Q4:重启 AstrBot 后任务还在吗?**
A:不在。当前实现使用内存中的 `AsyncIOScheduler`,重启后需要重新发送 `/new_api_start_notice`。如有持久化需求,可在 `metadata` 或 KV 存储中保存活跃会话列表,启动时恢复。

---

## 📝 开发说明

- 该插件基于 AstrBot Star API 实现,目前注册名为 `helloworld`(模板默认值),如需修改请编辑 [main.py](main.py) 中的 `@register(...)` 参数。
- 定时间隔写死在 `IntervalTrigger(seconds=5)`,后续可考虑放入配置文件。
- 日志类型与图标映射参见 [monitr.py](monitr.py) 中的 `TYPE_NAMES` / `TYPE_ICONS`。

---

## 📚 参考链接

- [AstrBot 主仓库](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot 插件开发文档(中文)](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 插件开发文档(English)](https://docs.astrbot.app/en/dev/star/plugin-new.html)
- [new-api 项目](https://github.com/QuantumNous/new-api)
- [one-api 项目](https://github.com/songquanpeng/one-api)

---

## 📄 License

本项目基于 [LICENSE](LICENSE) 开源,欢迎 issue / PR。

---

## 🙏 致谢

- 感谢 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 提供的优秀插件框架。
- 感谢 [new-api](https://github.com/QuantumNous/new-api) 提供的开放接口。
