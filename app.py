import json
import random
import time
from threading import Thread

from flask import Flask
from flask import send_from_directory
from flask_sock import Sock

app = Flask(__name__, static_folder="static", static_url_path="")
sock = Sock(app)


@app.route("/")
def index():
    # 访问根路径时返回前端页面
    return app.send_static_file("index.html")


@app.route("/static/<path:path>")
def static_files(path):
    # 兼容手动访问静态资源
    return send_from_directory("static", path)


@sock.route("/ws")
def websocket(ws):
    """
    WebSocket 连接处理：
    - 后台线程按设定间隔向客户端推送随机数据
    - 主线程监听客户端发来的 JSON 指令（例如修改推送间隔）
    """
    state = {
        "interval_ms": 1000,  # 默认1秒推送一次
        "running": True,
        "series": "random"    # 序列名
    }

    def sender():
        # 持续向客户端推送数据
        while state["running"]:
            payload = {
                "type": "tick",
                "series": state["series"],
                "timestamp": int(time.time() * 1000),   # 前端用毫秒时间戳
                "value": round(random.uniform(0, 100), 2)
            }
            try:
                ws.send(json.dumps(payload))
            except Exception:
                # 连接被关闭或异常，停止发送
                break
            time.sleep(max(state["interval_ms"], 50) / 1000.0)

    t = Thread(target=sender, daemon=True)
    t.start()

    try:
        # 处理客户端发来的 JSON 消息
        while True:
            msg = ws.receive()
            if msg is None:
                # 客户端关闭
                break
            try:
                data = json.loads(msg)
            except Exception:
                # 返回错误格式
                try:
                    ws.send(json.dumps({"type": "error", "message": "invalid JSON"}))
                except Exception:
                    pass
                continue

            # 处理不同类型的指令
            if data.get("type") == "set_interval":
                ms = data.get("ms")
                if isinstance(ms, int) and 50 <= ms <= 10_000:
                    state["interval_ms"] = ms
                    ack = {"type": "ack", "action": "set_interval", "ms": ms}
                    try:
                        ws.send(json.dumps(ack))
                    except Exception:
                        pass
                else:
                    try:
                        ws.send(json.dumps({
                            "type": "error",
                            "message": "ms must be integer between 50 and 10000"
                        }))
                    except Exception:
                        pass
            elif data.get("type") == "set_series":
                name = data.get("name")
                if isinstance(name, str) and 1 <= len(name) <= 32:
                    state["series"] = name
                    try:
                        ws.send(json.dumps({"type": "ack", "action": "set_series", "name": name}))
                    except Exception:
                        pass
                else:
                    try:
                        ws.send(json.dumps({"type": "error", "message": "invalid series name"}))
                    except Exception:
                        pass
            elif data.get("type") == "ping":
                try:
                    ws.send(json.dumps({"type": "pong", "t": int(time.time() * 1000)}))
                except Exception:
                    pass
            else:
                try:
                    ws.send(json.dumps({"type": "error", "message": "unknown command"}))
                except Exception:
                    pass
    finally:
        state["running"] = False
        # 线程是 daemon，会自动退出；此处可选择 join 短暂等待（非必须）


if __name__ == "__main__":
    # 本地开发可用 Flask 自带，但原生 WSGI 不支持 WS。
    # 推荐使用 hypercorn 运行：
    #   hypercorn --bind 127.0.0.1:8000 app:app
    # 如需直接运行，可只用于静态文件调试：
    app.run(host="127.0.0.1", port=8000, debug=True)