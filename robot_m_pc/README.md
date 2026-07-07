# 岐黄智取：电脑端问诊与抓药协作台

一个比赛演示用的本地 Web App：浏览器负责模拟问诊和摄像头，Python/FastAPI 在电脑本地调用百炼 `qwen3.7-plus`。模型生成药仓方案后，程序立即自动调用飞凌板卡的 `/pick-batch` 批量接口，不包含人工审核步骤。

桌面上的“岐黄智取”快捷方式可一键启动电脑端服务并自动打开浏览器。它会复用已经运行的服务，避免重复启动。

## 自动执行流程

模型的 Function Calling 生成演示抓药方案后，页面会立即显示方案和高亮药仓；电脑一次提交全部药仓，板端连续完成观察、示意图采集、抓取、回退、放置和释放使能：

```http
POST http://10.24.104.54:8000/pick-batch
Content-Type: application/json

{"slot_indices": [2, 5, 11], "disable_after": true, "visual_timeout": 5}
```

每次问诊通常选择约 3 味药材，硬上限为 4 味；同一药仓会被自动去重并且最多抓取一次。批量请求设置 `disable_after=true`，正常完成时由板端直接释放使能；只有批量任务失败时，电脑端才额外调用兜底释放接口：

```http
POST http://10.24.104.54:8000/disable
Content-Type: application/json

{}
```

板卡的 `http_robot_server.py` 需要让该接口真正发送机械臂释放使能指令并返回 2xx。若板卡使用其他路径，在 `.env` 修改 `ROBOT_DISABLE_PATH`。

批量返回中的 `captures` 会通过电脑端图片代理读取，并显示在左侧药仓面板下方；采集超时、未检测到目标和成功框选会分别标注。由于整批机械臂动作可能持续数分钟，电脑端默认超时为 240 秒。

板卡需要在两个终端分别启动视觉进程和 HTTP 服务。视觉脚本不要传固定 `--slots`，否则它不会响应 HTTP 创建的逐仓截图请求：

```bash
python3 rknn_medicine_vision.py
python3 http_robot_server.py --host 0.0.0.0 --port 8000
```

抓取和释放使能完成后，对话会先显示“抓药已完成，AI 正在生成详细总结报告”。随后系统使用关闭深度思考的 Qwen 对本轮问诊结论和实际动作结果进行总结，包含患者问题、望诊观察、演示辨析、实际抓药结果、逐味对应关系和使用方式。报告调用设置了超时与一次精简重试；两次均失败时才使用本地事实报告兜底。

系统没有仿真开关：每次生成方案都会真实请求板卡。抓取 POST 不自动重试，避免网络响应丢失导致重复抓药；任何一次失败都会停止后续动作，并写入 `logs/app.log`。

> 这是比赛演示装置，不是医疗器械、互联网诊疗或自动处方系统。所有问诊数据均应为模拟案例，机械臂抓取物仅作舞台展示，请勿服用。

## 运行

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，填入**新轮换的** `DASHSCOPE_API_KEY`。不要把 Key 写进代码或提交 Git。然后启动：

```powershell
python run.py
```

浏览器打开 <http://127.0.0.1:18080>。浏览器只允许安全来源访问摄像头，本机 `localhost/127.0.0.1` 可以正常使用。若端口冲突，可修改 `.env` 中的 `APP_PORT`。

## 板卡联调

1. 电脑先执行 `Test-NetConnection 10.24.104.54 -Port 8000`。
2. 确认板卡启动命令包含 `--port 8000`，且电脑和板卡路由、防火墙互通。
3. 手工核对 1～12 号药仓映射、机械臂动作范围和急停装置。
4. 启动本应用。模型一旦生成方案，机械臂会立即真实动作。

## 日志

运行日志写入 `logs/app.log`，单文件达到 5 MB 后轮转，保留 5 个历史文件。每次抓取会记录：

- 会话 ID、方案 ID、动作序号、药仓和药材名；
- 实际请求 URL、HTTP 状态码及板卡响应；
- HTTP 错误正文、连接失败、超时或其他网络异常；
- 整个方案开始、完成或在哪一步失败。

日志不会主动记录百炼 API Key。查看最新日志：

```powershell
Get-Content .\logs\app.log -Encoding UTF8 -Tail 100 -Wait
```

机械臂请求使用直连模式，不读取电脑的 `HTTP_PROXY/HTTPS_PROXY`，避免局域网板卡请求被代理转发而返回 502。

正确地址是 `http://10.24.104.54:8000`；`10.24.104.54/24` 中的 `/24` 是 CIDR 子网掩码，不属于 URL。

## 当前药仓映射

| 仓位 | 药材 | 仓位 | 药材 |
|---:|---|---:|---|
| 1 | 山楂 | 7 | 当归 |
| 2 | 大枣 | 8 | 陈皮 |
| 3 | 酸枣仁 | 9 | 茯苓 |
| 4 | 黄芪 | 10 | 甘草 |
| 5 | 菊花 | 11 | 麦冬 |
| 6 | 枸杞 | 12 | 桑叶 |

## 接口

- `GET /api/status`：模型、模式和药仓状态
- `POST /api/chat`：多轮问诊，可附一帧摄像头 Data URL
- `GET /api/sessions/{session_id}/pending`：查看当前尚未执行的方案
- `GET /api/plans/{plan_id}/status`：读取批量机械臂任务状态、结果、日志和示意图
- `GET /api/robot/captures/{filename}`：代理读取板卡生成的抓取示意图
- `GET /docs`：FastAPI 自动接口文档

当前会话与方案存于内存，重启即清空，适合比赛演示。
