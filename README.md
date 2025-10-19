# Flask + WebSocket + ECharts 实时数据小示例

本示例展示：
- 后端：Flask + Flask-Sock 提供 WebSocket 接口，按间隔推送随机数据（JSON）。
- 前端：ECharts 折线图实时渲染。
- 前后端通信：WebSocket（`/ws`），消息体为 JSON。

## 目录结构

```
.
├── app.py
├── requirements.txt
└── static
    ├── index.html
    ├── main.js
    └── styles.css
```

## 环境准备

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

## 启动后端

使用 hypercorn（推荐，用于支持 WebSocket）：

```bash
hypercorn --bind 127.0.0.1:8000 app:app
```

启动成功后访问：
- http://127.0.0.1:8000

> 注意：Flask 自带开发服务器是 WSGI，不原生支持 WebSocket；请使用 `hypercorn`（或 `gunicorn` + gevent/eventlet 等）以启用 WebSocket。

## 前后端通信协议（JSON）

- 服务端 -> 客户端：数据点推送
```json
{
  "type": "tick",
  "series": "random",
  "timestamp": 173...,
  "value": 12.34
}
```

- 客户端 -> 服务端：设置推送间隔（单位毫秒，范围 50~10000）
```json
{ "type": "set_interval", "ms": 500 }
```

- 客户端 -> 服务端：设置序列名
```json
{ "type": "set_series", "name": "my_series" }
```

- 心跳机制：
  - 客户端 -> 服务端：`{ "type": "ping" }`
  - 服务端 -> 客户端：`{ "type": "pong", "t": 173... }`

- 错误或确认：
```json
{ "type": "ack", "action": "set_interval", "ms": 500 }
{ "type": "error", "message": "invalid JSON" }
```

## 常见问题

- 浏览器控制台提示无法连接 `ws://`：
  - 确认后端使用 `hypercorn` 启动，并监听的是 `127.0.0.1:8000`。
  - 若使用 HTTPS，需要切换到 `wss://`，前端脚本已自动根据协议选择 `ws/wss`。

- ECharts 无数据：
  - 检查 WebSocket 是否连接成功，页面顶部状态应显示“已连接”。
  - 查看后端日志是否有异常。

## 生产环境建议

- 使用 `gunicorn` + `gevent-websocket` 或 `hypercorn` 部署。
- 增加鉴权（例如使用 Cookie/Token 进行认证）。
- 增加分组/多路复用（使用不同 `series` 或频道）。
- 使用消息队列或缓存中间层（如 Redis）实现多实例广播。