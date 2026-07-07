"""Local web dashboard and supervisor for the robot medicine system."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from collection_status import LATEST_IMAGE as COLLECTION_IMAGE
from collection_status import read_status as read_collection_status
from robot_task_status import read_task_status, reset_task_status
from vision_selection import CAPTURE_DIRECTORY, VISION_LATEST_IMAGE, clear_capture_images


PROJECT_DIR = Path(__file__).resolve().parent
DASHBOARD_FILE = PROJECT_DIR / "dashboard.html"
ROBOT_API = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    label: str
    command: List[str]


class ProcessManager:
    def __init__(self) -> None:
        python = sys.executable
        self.specs = (
            ProcessSpec(
                "robot_http",
                "机械臂 HTTP 服务",
                [python, "-u", "http_robot_server.py", "--host", "0.0.0.0", "--port", "8000"],
            ),
            ProcessSpec(
                "pick_camera",
                "抓药观察相机",
                [
                    python,
                    "-u",
                    "rknn_medicine_vision.py",
                    "--camera-serial",
                    "213522072048",
                    "--npu-core",
                    "0",
                    "--no-preview",
                ],
            ),
            ProcessSpec(
                "collection_camera",
                "收药计数相机",
                [
                    python,
                    "-u",
                    "collection_box_monitor.py",
                    "--model",
                    "models/medicine_fp.rknn",
                    "--camera-serial",
                    "944622074239",
                    "--npu-core",
                    "1",
                    "--no-preview",
                ],
            ),
        )
        self.processes: Dict[str, subprocess.Popen[str]] = {}
        self.logs: Deque[Dict[str, Any]] = deque(maxlen=1000)
        self.log_sequence = 0
        self.lock = threading.RLock()

    def start_all(self) -> Dict[str, Any]:
        with self.lock:
            reset_task_status()
            clear_capture_images()
            for spec in self.specs:
                existing = self.processes.get(spec.name)
                if existing and existing.poll() is None:
                    continue
                process = subprocess.Popen(
                    spec.command,
                    cwd=str(PROJECT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                self.processes[spec.name] = process
                self._append_log(spec.name, f"进程已启动，PID={process.pid}")
                threading.Thread(
                    target=self._read_output,
                    args=(spec.name, process),
                    daemon=True,
                ).start()
                if spec.name == "robot_http":
                    time.sleep(0.3)
        return self.status()

    def stop_all(self) -> Dict[str, Any]:
        with self.lock:
            running = [process for process in self.processes.values() if process.poll() is None]
            for process in running:
                process.terminate()
            deadline = time.monotonic() + 3.0
            for process in running:
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    process.kill()
            self._append_log("system", "所有子进程已停止")
            reset_task_status()
        return self.status()

    def status(self) -> Dict[str, Any]:
        states = []
        for spec in self.specs:
            process = self.processes.get(spec.name)
            running = bool(process and process.poll() is None)
            states.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "running": running,
                    "pid": process.pid if running and process else None,
                    "returncode": process.poll() if process else None,
                }
            )
        return {"processes": states, "all_running": all(item["running"] for item in states)}

    def get_logs(self, after: int = 0) -> List[Dict[str, Any]]:
        with self.lock:
            return [entry for entry in self.logs if entry["id"] > after]

    def _read_output(self, name: str, process: subprocess.Popen[str]) -> None:
        if process.stdout:
            for line in process.stdout:
                self._append_log(name, line.rstrip())
        returncode = process.wait()
        self._append_log(name, f"进程已退出，返回码={returncode}")

    def _append_log(self, source: str, message: str) -> None:
        if not message:
            return
        with self.lock:
            self.log_sequence += 1
            self.logs.append(
                {
                    "id": self.log_sequence,
                    "time": time.strftime("%H:%M:%S"),
                    "source": source,
                    "message": message,
                }
            )


manager = ProcessManager()


def proxy_robot_api(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ROBOT_API + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=None) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def capture_list() -> List[Dict[str, Any]]:
    if not CAPTURE_DIRECTORY.exists():
        return []
    paths = sorted(CAPTURE_DIRECTORY.glob("*.jpg"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "name": path.name,
            "url": f"/captures/{path.name}",
            "updated_at": path.stat().st_mtime,
        }
        for path in paths[:12]
    ]


def camera_state(path: Path, process_name: str) -> Dict[str, Any]:
    process = manager.processes.get(process_name)
    running = bool(process and process.poll() is None)
    if not path.is_file():
        return {"running": running, "available": False, "updated_at": None, "age": None}
    updated_at = path.stat().st_mtime
    age = max(0.0, time.time() - updated_at)
    return {
        "running": running,
        "available": bool(running and age <= 2.0),
        "updated_at": updated_at,
        "age": age,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.write_bytes(200, DASHBOARD_FILE.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            self.write_json(
                200,
                {
                    "ok": True,
                    "processes": manager.status(),
                    "task": read_task_status(),
                    "collection": read_collection_status(),
                    "captures": capture_list(),
                    "cameras": {
                        "pick": camera_state(VISION_LATEST_IMAGE, "pick_camera"),
                        "collection": camera_state(COLLECTION_IMAGE, "collection_camera"),
                    },
                },
            )
            return
        if parsed.path == "/api/logs":
            after = int(parse_qs(parsed.query).get("after", ["0"])[0])
            self.write_json(200, {"ok": True, "logs": manager.get_logs(after)})
            return
        if parsed.path == "/camera/pick.jpg":
            self.serve_image(VISION_LATEST_IMAGE, max_age=2.0)
            return
        if parsed.path == "/camera/collection.jpg":
            self.serve_image(COLLECTION_IMAGE, max_age=2.0)
            return
        if parsed.path.startswith("/captures/"):
            filename = parsed.path.removeprefix("/captures/")
            if Path(filename).name != filename:
                self.write_json(400, {"ok": False, "error": "invalid filename"})
                return
            self.serve_image(CAPTURE_DIRECTORY / filename)
            return
        self.write_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            if self.path == "/api/start":
                self.write_json(200, {"ok": True, "data": manager.start_all()})
                return
            if self.path == "/api/stop":
                self.write_json(200, {"ok": True, "data": manager.stop_all()})
                return
            if self.path == "/api/pick":
                self.write_json(200, proxy_robot_api("/pick-batch", payload))
                return
            if self.path == "/api/emergency-stop":
                self.write_json(200, proxy_robot_api("/stop", {}))
                return
            if self.path == "/api/collection-reset":
                self.write_json(200, proxy_robot_api("/collection/reset", {}))
                return
            self.write_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            self.write_json(500, {"ok": False, "error": str(exc)})

    def read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def serve_image(self, path: Path, max_age: Optional[float] = None) -> None:
        if not path.is_file():
            self.write_json(404, {"ok": False, "error": "image not ready"})
            return
        if max_age is not None and time.time() - path.stat().st_mtime > max_age:
            self.write_json(503, {"ok": False, "error": "camera frame is stale"})
            return
        self.write_bytes(200, path.read_bytes(), "image/jpeg")

    def write_json(self, status: int, payload: Dict[str, Any]) -> None:
        self.write_bytes(
            status,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def write_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Tuple[Any, ...]) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="机器人抓药系统本地控制台")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clear_capture_images()
    reset_task_status()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Robot app: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop_all()
        server.server_close()


if __name__ == "__main__":
    main()
