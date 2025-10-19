(function () {
  const chartDom = document.getElementById("chart");
  const myChart = echarts.init(chartDom);

  // 初始图表配置
  const option = {
    title: { text: "实时数据（WebSocket + JSON）" },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    xAxis: { type: "time" },
    yAxis: { type: "value", scale: true },
    series: [
      {
        name: "random",
        type: "line",
        showSymbol: false,
        smooth: true,
        data: []
      }
    ]
  };
  myChart.setOption(option);

  const statusEl = document.getElementById("status");
  const intervalInput = document.getElementById("interval");
  const seriesInput = document.getElementById("series");
  const applyIntervalBtn = document.getElementById("apply-interval");
  const applySeriesBtn = document.getElementById("apply-series");

  let ws = null;
  let reconnectTimer = null;
  const maxPoints = 200;

  function setStatus(text, color = "") {
    statusEl.textContent = text;
    statusEl.style.color = color || "";
  }

  function connect() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setStatus("已连接", "green");
      // 同步前端控件状态到后端
      try {
        ws.send(JSON.stringify({ type: "set_interval", ms: parseInt(intervalInput.value, 10) || 1000 }));
        ws.send(JSON.stringify({ type: "set_series", name: seriesInput.value || "random" }));
      } catch (e) {}
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.type === "tick") {
          const name = msg.series || "random";
          const point = [msg.timestamp, msg.value];

          // 确保 series 名称匹配，若不匹配则更新
          const currSeries = myChart.getOption().series[0];
          if (currSeries.name !== name) {
            myChart.setOption({
              series: [
                {
                  name,
                  data: []
                }
              ]
            });
          }

          // 追加数据并裁剪长度
          const seriesData = myChart.getOption().series[0].data || [];
          seriesData.push(point);
          if (seriesData.length > maxPoints) {
            seriesData.splice(0, seriesData.length - maxPoints);
          }

          myChart.setOption({
            series: [
              {
                data: seriesData
              }
            ]
          });
        } else if (msg.type === "ack") {
          // 可根据需要提示
          // console.log("ACK:", msg);
        } else if (msg.type === "error") {
          console.warn("Server error:", msg.message);
        } else if (msg.type === "pong") {
          // 心跳响应
        }
      } catch (e) {
        console.warn("Invalid message:", evt.data);
      }
    };

    ws.onclose = () => {
      setStatus("已断开，重连中…", "orange");
      scheduleReconnect();
    };

    ws.onerror = () => {
      setStatus("错误，重连中…", "red");
      try {
        ws.close();
      } catch (e) {}
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, 1000);
  }

  applyIntervalBtn.addEventListener("click", () => {
    const ms = parseInt(intervalInput.value, 10);
    if (!Number.isInteger(ms) || ms < 50 || ms > 10000) {
      alert("间隔需在 50~10000ms 之间的整数");
      return;
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "set_interval", ms }));
    }
  });

  applySeriesBtn.addEventListener("click", () => {
    const name = (seriesInput.value || "").trim();
    if (!name || name.length > 32) {
      alert("序列名不能为空且不超过 32 个字符");
      return;
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "set_series", name }));
    }
  });

  // 可选：定时心跳，保持连接
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, 10000);

  // 初始化连接
  connect();

  // 自适应窗口大小
  window.addEventListener("resize", () => {
    myChart.resize();
  });
})();