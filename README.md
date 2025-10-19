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





# YOLO11 行为识别流服务（Flask + WebSocket(JSON) + MJPEG + ECharts）

本项目提供一套“视频流 → YOLO11 推理 → 后端(Flask) → WebSocket(JSON) → 前端可视化”的完整链路。
- 后端以流方式读取视频源（文件/摄像头/RTSP），用 YOLO11 执行检测/跟踪与“行为分类”。
- 将每帧结果以 JSON 通过 WebSocket 推送给前端，包含每个目标的行为标注与六类行为的人数统计。
- 同时提供叠加检测框后的 MJPEG 视频流，前端可直接播放或自行重绘。
- 前端示例使用 ECharts 横向柱状图实时展示“某一时刻六种学生行为的人数”。

---



## 功能概览

- 支持输入源：本地视频文件、摄像头索引（0/1/...）、RTSP/HTTP 视频流。
- YOLO 推理：`ultralytics.YOLO` + 跟踪（BoT-SORT 默认），可持久化 track id。
- 抽帧推理：按 `INFERENCE_INTERVAL_SEC` 节流；非推理帧复用上一次结果，降本提效。
- WebSocket(JSON)：每帧推送
  - 目标列表 objects（含 bbox、id、class、conf、行为标注）
  - 六类行为人数统计 `behavior_counts`
- MJPEG 画面流：`/video.mjpg`，叠加了检测框与标签，便于直观看值守。
- 前端可视化：ECharts 横向柱状图，实时展示每帧六类行为的人数。

---

## 行为类别约定

六类行为与输出 code 的映射如下（固定顺序以便前端展示）：

| 行为 | 英文类名(参考训练集) | code |
|---|---|---|
| 抬头 | LookingUp | u |
| 低头 | LookingDown | d |
| 趴桌 | LyingOnDesk | c |
| 回头 | LookingBack | b |
| 使用手机 | UsingPhone | p |
| 站立 | Standing | s |

- 后端会尝试将模型类名映射为上述 code，并在每个目标的 `behavior` 字段中给出中英标签与 code。
- 每帧汇总 `behavior_counts = {u,d,c,b,p,s}`，用于前端绘图。

---

## 目录与关键文件

- `server_app_Version2.py`：后端主服务（Flask + WebSocket + YOLO + MJPEG）
- `requirements.txt`：依赖列表（建议创建）

示例 `requirements.txt` 内容：
```txt
Flask==3.0.3
flask-sock==0.7.0
simple-websocket==1.0.0
ultralytics>=8.3.0
opencv-python>=4.9.0.80
```

---

## 环境要求

- Python 3.9+（推荐）
- 可选 GPU（CUDA）以获得更高推理速度
- 你自己的 YOLO11 权重文件（`MODEL_PATH`）

---

## 安装

```bash
# 1) 创建虚拟环境（可选）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2) 安装依赖
pip install -r requirements.txt
```

---

## 配置

编辑 `server_app_Version2.py` 顶部配置：
```python
MODEL_PATH = r"C:\path\to\your\yolo11_weights.pt"
SOURCE = r"input/your_video.mp4"  # 或 0 / rtsp://...
TRACKER_CFG = "botsort.yaml"

INFERENCE_INTERVAL_SEC = 0.01  # 抽帧推理间隔（秒）
CONF_THRES = 0.25
IOU_THRES = 0.30
PERSIST_TRACK = True
DEVICE = None  # "cuda:0" / "cpu" / None(自动)
```

如需在 JSON 中携带图像（体积大、一般不建议）：
```python
INCLUDE_IMAGE_IN_JSON = True
```

---

## 运行

```bash
python server_app_Version2.py
```

访问：
- 演示页（视频 + 叠加 + ECharts 柱状图 + 日志）：http://localhost:8000/
- MJPEG 处理后视频：http://localhost:8000/video.mjpg
- WebSocket(JSON)：ws://localhost:8000/ws
- 健康检查：http://localhost:8000/health
- 配置回显：http://localhost:8000/config

---

## HTTP 与 WebSocket 接口

- GET `/video.mjpg`：叠加检测框的 MJPEG 流
- WS `/ws`：后端以广播方式推送每帧 JSON，客户端只需接收即可
- GET `/health`：状态
- GET `/config`：当前服务配置（只读）

---

## JSON 消息格式

每帧推送示例（节选）：
```json
{
  "type": "frame",
  "source": "input/xxx.mp4",
  "frame_index": 120,
  "time_ms": 1739948450123,
  "fps": 28.7,
  "objects": [
    {
      "id": 7,
      "class_id": 0,
      "class_name": "LookingUp",
      "conf": 0.91,
      "bbox": { "x1": 324, "y1": 180, "x2": 412, "y2": 420 },
      "behavior": { "code": "u", "zh": "抬头", "en": "LookingUp" }
    },
    {
      "id": 9,
      "class_id": 3,
      "class_name": "UsingPhone",
      "conf": 0.88,
      "bbox": { "x1": 600, "y1": 200, "x2": 690, "y2": 420 },
      "behavior": { "code": "p", "zh": "使用手机", "en": "UsingPhone" }
    }
  ],
  "behavior_counts": {
    "u": 3, "d": 5, "c": 1, "b": 0, "p": 2, "s": 0
  },
  "behavior_order": ["u", "d", "c", "b", "p", "s"],
  "behavior_legend": {
    "u": "抬头", "d": "低头", "c": "趴桌", "b": "回头", "p": "使用手机", "s": "站立"
  }
}
```

字段说明：
- `objects[].behavior`：每个目标的行为标注，包含 `code/zh/en`
- `behavior_counts`：该帧六类人数统计，用于前端绘图
- `behavior_order`：固定顺序，方便前端按序渲染
- `behavior_legend`：后端提供的 code → 中文名映射

---

## 前端对接（ECharts 横向柱状图）

下面给出一个最小示例，仅使用 WebSocket 数据更新六类行为人数，并用 ECharts 横向柱状图展示。

```html
<div id="chart" style="width:600px;height:360px;"></div>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script>
const chart = echarts.init(document.getElementById('chart'));
const ORDER = ["u","d","c","b","p","s"];
const LABEL = {"u":"抬头","d":"低头","c":"趴桌","b":"回头","p":"使用手机","s":"站立"};

function updateChart(counts) {
  const data = ORDER.map(k => counts[k] ?? 0);
  const yCats = ORDER.map(k => `${LABEL[k]} (${k})`);
  chart.setOption({
    animation: false,
    grid: {left: 90, right: 20, top: 20, bottom: 20},
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: yCats, axisTick: {show:false} },
    series: [{
      type: 'bar',
      data,
      label: { show: true, position: 'right' },
      itemStyle: { color: '#4CAF50' }
    }]
  }, { notMerge: true, lazyUpdate: true });
}

// 连接 WebSocket，实时更新图表
const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(wsProto + '://' + location.host + '/ws');

ws.onmessage = (ev) => {
  try {
    const payload = JSON.parse(ev.data);
    const counts = payload.behavior_counts || (() => {
      // 兜底：如后端未提供 behavior_counts，则从 objects 聚合
      const c = {u:0,d:0,c:0,b:0,p:0,s:0};
      (payload.objects||[]).forEach(o => {
        const code = o.behavior?.code;
        if (code && c.hasOwnProperty(code)) c[code]++;
      });
      return c;
    })();
    updateChart(counts);
  } catch (e) {
    console.error('WS parse error', e);
  }
};
</script>
```

若需要同时播放处理后视频，可在页面中加入：
```html
<img src="/video.mjpg" style="width:720px;border:1px solid #ccc;" />
```

如需在画面上叠加检测框，可使用 `<canvas>` 覆盖并按 `objects[].bbox` 绘制（参考 `server_app_Version2.py` 中 `/` 的演示页）。

---

## 性能与延迟

- 将 `INFERENCE_INTERVAL_SEC` 调小可接近逐帧推理，但会增加算力开销。
- 多前端同时观看，优先推荐 MJPEG（浏览器原生支持，简单稳定）。
- 需要更低延迟/更高画质：建议引入 WebRTC/RTSP/LL-HLS 承载音视频，WebSocket 继续承载 JSON 元数据。

---

## 生产部署建议

- 使用 `gunicorn + gevent` 或 `waitress` 部署 Flask 服务。
- 如需 HTTPS/WSS，请置于反向代理（Nginx/Caddy）之后并配置证书。
- 增加日志、鉴权、限流与跨域（CORS）策略。
- 模型与视频源路径使用环境变量或配置文件管理。

---

## 常见问题（FAQ）

- Q：JSON 中看不到 `behavior` 或统计不对？
  - A：确保你的模型类名与上表能正确映射；可在 `_map_behavior` 中补充别名；也可直接让训练集类名使用 `LookingUp/LookingDown/...`。
- Q：坐标系不匹配导致前端绘制偏移？
  - A：请确保 MJPEG 的尺寸与推理原始尺寸一致；或在前端根据显示尺寸做比例缩放。
- Q：CPU 占用高？
  - A：增大 `INFERENCE_INTERVAL_SEC`（抽帧更稀疏）；降低 MJPEG 推送帧率 `MJPEG_FPS`；关闭 `INCLUDE_IMAGE_IN_JSON`。

---

## 许可证

根据你的实际需要填写（例如 MIT/Apache-2.0/internal）。

---