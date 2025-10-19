import os
import time
import json
import base64
import threading
from queue import Queue

import cv2
from flask import Flask, Response, jsonify
from flask_sock import Sock
from ultralytics import YOLO

# =========================
# 用户配置
# =========================
MODEL_PATH = r"C:\Users\fuyou\Desktop\ClassVision\ClassVision\class-pose\xanylabeling_models\best_1200_pre.pt"
# SOURCE 可为：视频文件路径、摄像头索引(0)、或 RTSP/HTTP 地址
SOURCE = r"input/3-311+2025-05-28+16_12_00+2025-05-28+16+15+00_学生.mp4"
TRACKER_CFG = "botsort.yaml"

# 推理节流：每隔多少秒推理一帧（抽帧）
INFERENCE_INTERVAL_SEC = 0.01
CONF_THRES = 0.25
IOU_THRES = 0.30
PERSIST_TRACK = True
DEVICE = None     # "cuda:0" / "cpu" / None(自动)
VERBOSE = False

# 输出控制
INCLUDE_IMAGE_IN_JSON = False  # 若为 True，会把 JPEG(base64) 塞进 JSON（带宽较大）
JPEG_QUALITY = 80
MJPEG_FPS = 20
# =========================


app = Flask(__name__)
sock = Sock(app)

# ---------------- 行为类别映射（重要） ----------------
# 需求映射：抬头:u  低头:d  趴桌:c  回头:b  使用手机:p  站立:s
# 训练集类名（英文）与中文描述都做了兼容
_BEHAVIOR_ENG_KEYS = {
    "lookingup":   ("u", "抬头",   "LookingUp"),
    "lookingdown": ("d", "低头",   "LookingDown"),
    "lyingondesk": ("c", "趴桌",   "LyingOnDesk"),
    "lookingback": ("b", "回头",   "LookingBack"),
    "usingphone":  ("p", "使用手机", "UsingPhone"),
    "standing":    ("s", "站立",   "Standing"),
}
_BEHAVIOR_ORDER = ["u", "d", "c", "b", "p", "s"]  # 固定顺序，便于前端绘图

def _map_behavior(name: str):
    """将模型类名/中文名映射到 (code, zh, en)。无法识别返回 None。"""
    if not name:
        return None
    raw = str(name).strip()
    key = raw.lower().replace(" ", "").replace("_", "")
    # 英文优先
    if key in _BEHAVIOR_ENG_KEYS:
        return _BEHAVIOR_ENG_KEYS[key]
    # 常见别名
    alias = {
        "lookinguplook": "lookingup",
        "up": "lookingup",
        "raisehead": "lookingup",
        "down": "lookingdown",
        "desk": "lyingondesk",
        "back": "lookingback",
        "phone": "usingphone",
        "stand": "standing",
    }
    if key in alias and alias[key] in _BEHAVIOR_ENG_KEYS:
        return _BEHAVIOR_ENG_KEYS[alias[key]]
    # 中文关键字兜底
    if "抬头" in raw:   return _BEHAVIOR_ENG_KEYS["lookingup"]
    if "低头" in raw:   return _BEHAVIOR_ENG_KEYS["lookingdown"]
    if ("趴" in raw) or ("趴桌" in raw) or ("伏" in raw):  return _BEHAVIOR_ENG_KEYS["lyingondesk"]
    if "回头" in raw or "后" in raw: return _BEHAVIOR_ENG_KEYS["lookingback"]
    if "手机" in raw:   return _BEHAVIOR_ENG_KEYS["usingphone"]
    if "站" in raw:     return _BEHAVIOR_ENG_KEYS["standing"]
    return None
# -----------------------------------------------------


# 连接管理：每个 WS 客户端一个 Queue，后台线程投递最新消息
class WSManager:
    def __init__(self):
        self._conns = {}  # ws -> Queue[str]
        self._lock = threading.Lock()

    def add(self, ws):
        q = Queue(maxsize=2)
        with self._lock:
            self._conns[ws] = q
        return q

    def remove(self, ws):
        with self._lock:
            self._conns.pop(ws, None)

    def broadcast(self, message_str: str):
        # 非阻塞广播；队列满则丢弃旧消息，保持最新
        drop_list = []
        with self._lock:
            for ws, q in self._conns.items():
                try:
                    if q.full():
                        _ = q.get_nowait()
                    q.put_nowait(message_str)
                except Exception:
                    drop_list.append(ws)
            for ws in drop_list:
                self._conns.pop(ws, None)

ws_manager = WSManager()

# 共享的“最新 JPEG 帧”
_latest_jpeg = None
_latest_jpeg_lock = threading.Lock()
_latest_size = (0, 0)  # (w, h)

def _encode_jpeg(frame, quality=80):
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return None
    return buf.tobytes()

def _draw_detections(frame, result, class_names):
    if result is None or result.boxes is None:
        return frame
    for box in result.boxes:
        xyxy = box.xyxy[0].cpu().numpy().astype(int)
        x1, y1, x2, y2 = xyxy.tolist()
        class_id = int(box.cls[0]) if box.cls is not None else -1
        track_id = int(box.id[0]) if (box.id is not None) else -1
        conf = float(box.conf[0]) if box.conf is not None else None

        # 行为标签用于可视化
        name = class_names.get(class_id, str(class_id))
        beh = _map_behavior(name)
        beh_code = beh[0] if beh else ""
        beh_zh = beh[1] if beh else ""

        color = (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"ID {track_id if track_id is not None else '-'} {beh_code}"
        if beh_zh:
            label += f" {beh_zh}"
        if conf is not None:
            label += f" {conf:.2f}"
        cv2.putText(frame, label, (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, lineType=cv2.LINE_AA)
    return frame

def _result_to_payload(result, frame_index, t_ms, fps, src, class_names, image_b64=None):
    # 初始化六类计数
    behavior_counts = {k: 0 for k in _BEHAVIOR_ORDER}
    objects = []

    if result is not None and result.boxes is not None:
        for box in result.boxes:
            xyxy = box.xyxy[0].cpu().numpy().tolist()
            class_id = int(box.cls[0]) if box.cls is not None else -1
            name = class_names.get(class_id, str(class_id))
            track_id = int(box.id[0]) if (box.id is not None) else None
            conf = float(box.conf[0]) if box.conf is not None else None

            beh = _map_behavior(name)
            behavior = None
            if beh:
                behavior = {"code": beh[0], "zh": beh[1], "en": beh[2]}
                if beh[0] in behavior_counts:
                    behavior_counts[beh[0]] += 1

            objects.append({
                "id": track_id,
                "class_id": class_id,
                "class_name": name,
                "conf": conf,
                "bbox": {
                    "x1": int(xyxy[0]),
                    "y1": int(xyxy[1]),
                    "x2": int(xyxy[2]),
                    "y2": int(xyxy[3]),
                },
                "behavior": behavior  # 新增：行为标注（含 code/中英）
            })

    payload = {
        "type": "frame",
        "source": str(src),
        "frame_index": frame_index,
        "time_ms": t_ms,
        "fps": round(fps, 2),
        "objects": objects,
        # 新增：每帧六类人数统计 + 固定顺序（便于前端直接映射到横向柱状图）
        "behavior_counts": behavior_counts,
        "behavior_order": _BEHAVIOR_ORDER,
        # 可选：提供 code->中文 的图例，前端直接使用
        "behavior_legend": {
            "u": "抬头", "d": "低头", "c": "趴桌", "b": "回头", "p": "使用手机", "s": "站立"
        }
    }
    if image_b64 is not None:
        payload["image_jpeg_base64"] = image_b64
    return payload

def processing_loop():
    global _latest_jpeg, _latest_size
    os.environ["ULTRALYTICS_HIDE_VERSION_WARNING"] = "1"

    model = YOLO(MODEL_PATH)
    if DEVICE:
        model.to(DEVICE)
    try:
        class_names = model.names if hasattr(model, "names") else {}
    except Exception:
        class_names = {}

    cap = cv2.VideoCapture(SOURCE)
    if not cap.isOpened():
        print(f"[ERR] 无法打开视频源: {SOURCE}")
        return

    fps_cap = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
    _latest_size = (width, height)
    interval_frames = max(1, int(fps_cap * INFERENCE_INTERVAL_SEC))

    print(f"[INFO] 推理启动: source={SOURCE}, fps≈{fps_cap:.2f}, size=({width}x{height}), 每 {interval_frames} 帧推理一次")

    frame_index = 0
    last_result = None
    infer_count = 0
    start_t = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        do_infer = (frame_index % interval_frames == 0)

        if do_infer:
            results = model.track(
                source=frame,
                tracker=TRACKER_CFG,
                persist=PERSIST_TRACK,
                stream=False,
                show=False,
                verbose=VERBOSE,
                conf=CONF_THRES,
                iou=IOU_THRES,
                save=False,
                show_conf=False,
            )
            if results:
                last_result = results[0]
                infer_count += 1

        # 叠加绘制（用于 MJPEG 或可选内嵌 JSON 图像）
        drawn = frame.copy()
        drawn = _draw_detections(drawn, last_result, class_names)
        jpeg_bytes = _encode_jpeg(drawn, JPEG_QUALITY)
        if jpeg_bytes:
            with _latest_jpeg_lock:
                _latest_jpeg = jpeg_bytes

        # 组织并广播 JSON
        elapsed = time.time() - start_t
        proc_fps = (frame_index + 1) / elapsed if elapsed > 0 else 0.0
        now_ms = int(time.time() * 1000)
        image_b64 = base64.b64encode(jpeg_bytes).decode("ascii") if (INCLUDE_IMAGE_IN_JSON and jpeg_bytes) else None
        payload = _result_to_payload(
            last_result, frame_index, now_ms, proc_fps, SOURCE, class_names, image_b64=image_b64
        )
        try:
            ws_manager.broadcast(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

        frame_index += 1

    cap.release()
    print(f"[INFO] 推理结束: 总帧 {frame_index}, 推理次数 {infer_count}")

# 启动后台线程
_processing_thread = threading.Thread(target=processing_loop, name="yolo-worker", daemon=True)
_processing_thread.start()

@app.get("/health")
def health():
    return jsonify({"status": "ok", "model": os.path.basename(MODEL_PATH), "source": str(SOURCE)})

@app.get("/config")
def config():
    w, h = _latest_size
    return jsonify({
        "model_path": MODEL_PATH,
        "source": str(SOURCE),
        "tracker": TRACKER_CFG,
        "include_image_in_json": INCLUDE_IMAGE_IN_JSON,
        "jpeg_quality": JPEG_QUALITY,
        "mjpeg_fps": MJPEG_FPS,
        "frame_size": {"width": w, "height": h}
    })

@app.route("/")
def index():
    # 简易演示页：左侧 MJPEG 帧，右侧 ECharts 横向柱状图 + WS JSON 日志；Canvas 覆盖绘制框
    html = """
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>YOLO Stream (Flask + WS + ECharts)</title>
<style>
  body { font-family: sans-serif; display:flex; gap:16px; }
  #left { position:relative; }
  #mjpeg { border:1px solid #ccc; max-width: 720px; }
  #overlay { position:absolute; left:0; top:0; pointer-events:none; }
  #right { display:flex; flex-direction:column; gap:12px; }
  #chart { width:560px; height:360px; border:1px solid #eee; }
  #log { width:560px; height:280px; border:1px solid #ccc; overflow:auto; white-space:pre; }
</style>
</head>
<body>
  <div id="left">
    <img id="mjpeg" src="/video.mjpg" />
    <canvas id="overlay"></canvas>
  </div>
  <div id="right">
    <div id="chart"></div>
    <div>
      <h3 style="margin:6px 0;">WebSocket JSON (sample)</h3>
      <div id="log"></div>
    </div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<script>
const img = document.getElementById('mjpeg');
const canvas = document.getElementById('overlay');
const ctx = canvas.getContext('2d');
const logDiv = document.getElementById('log');
const chart = echarts.init(document.getElementById('chart'));

const BEH_ORDER = ["u","d","c","b","p","s"];
const BEH_LABEL_ZH = { "u":"抬头", "d":"低头", "c":"趴桌", "b":"回头", "p":"使用手机", "s":"站立" };

function resizeCanvas() {
  canvas.width = img.clientWidth;
  canvas.height = img.clientHeight;
}
img.addEventListener('load', resizeCanvas);
window.addEventListener('resize', resizeCanvas);
setInterval(resizeCanvas, 1000);

function drawBoxes(objects) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = 'lime';
  ctx.lineWidth = 2;
  ctx.font = '12px sans-serif';
  ctx.fillStyle = 'rgba(0,0,0,0.5)';
  for (const o of objects) {
    const {x1,y1,x2,y2} = o.bbox;
    const w = x2-x1, h = y2-y1;
    ctx.strokeRect(x1,y1,w,h);
    const code = o.behavior?.code ?? "";
    const zh = o.behavior?.zh ?? "";
    const conf = (typeof o.conf === 'number') ? o.conf.toFixed(2) : '';
    const label = `ID ${o.id ?? '-'} ${code} ${zh} ${conf}`;
    const tw = ctx.measureText(label).width + 6;
    ctx.fillRect(x1, Math.max(0, y1-16), tw, 16);
    ctx.fillStyle = 'white';
    ctx.fillText(label, x1+3, Math.max(10, y1-4));
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
  }
}

function ensureCounts(payload) {
  // 优先使用后端提供的 behavior_counts；否则从 objects 计算
  if (payload.behavior_counts) return payload.behavior_counts;
  const counts = {u:0,d:0,c:0,b:0,p:0,s:0};
  if (Array.isArray(payload.objects)) {
    for (const o of payload.objects) {
      const code = o.behavior?.code;
      if (code && counts.hasOwnProperty(code)) counts[code] += 1;
    }
  }
  return counts;
}

function updateChart(counts) {
  const data = BEH_ORDER.map(k => counts[k] ?? 0);
  const yCats = BEH_ORDER.map(k => `${BEH_LABEL_ZH[k]} (${k})`);
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

function appendLog(text) {
  const atBottom = logDiv.scrollTop + logDiv.clientHeight >= logDiv.scrollHeight - 4;
  logDiv.textContent = text + "\\n" + logDiv.textContent;
  if (atBottom) logDiv.scrollTop = logDiv.scrollHeight;
}

const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
const ws = new WebSocket(wsProto + '://' + location.host + '/ws');
ws.onopen = () => appendLog('WS connected');
ws.onclose = () => appendLog('WS closed');
ws.onerror = (e) => appendLog('WS error');
ws.onmessage = (ev) => {
  try {
    const data = JSON.parse(ev.data);
    drawBoxes(data.objects || []);
    const counts = ensureCounts(data);
    updateChart(counts);
    if (data.frame_index % 10 === 0) appendLog(JSON.stringify({frame_index: data.frame_index, behavior_counts: counts}));
  } catch (e) {
    appendLog('parse error: ' + e);
  }
};
</script>
</body>
</html>
    """
    return Response(html, mimetype="text/html")

@app.route("/video.mjpg")
def mjpeg_stream():
    boundary = "frameboundary"
    def gen():
        interval = 1.0 / max(1, MJPEG_FPS)
        while True:
            time.sleep(interval)
            with _latest_jpeg_lock:
                data = _latest_jpeg
            if data is None:
                continue
            yield (
                f"--{boundary}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(data)}\r\n\r\n"
            ).encode("utf-8") + data + b"\r\n"

    headers = {
        "Cache-Control": "no-cache, private",
        "Pragma": "no-cache",
        "Age": "0",
        "Content-Type": f"multipart/x-mixed-replace; boundary=--{boundary}"
    }
    return Response(gen(), headers=headers)

@sock.route("/ws")
def ws(ws):
    # 为此连接创建独立队列
    q = ws_manager.add(ws)
    try:
        # 只发不收；若需心跳可 ws.receive(timeout=...) 并忽略
        while True:
            msg = q.get()  # 阻塞等待新消息
            ws.send(msg)
    except Exception:
        pass
    finally:
        ws_manager.remove(ws)

if __name__ == "__main__":
    # 直接用 Flask 内置服务器即可运行（开发用途）
    # 生产建议用 gunicorn + gevent 或 waitress 等部署
    app.run(host="0.0.0.0", port=8000, threaded=True)