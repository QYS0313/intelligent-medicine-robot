"""HTTP network service for robot medicine picking.

Run on the embedded board:
    python3 http_robot_server.py --host 0.0.0.0 --port 8000

Example from the PC:
    curl -X POST http://BOARD_IP:8000/pick \
      -H 'Content-Type: application/json' \
      -d '{"slot_index": 1}'
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

from medicine_picker import (
    FAST_SPEED,
    BACK_OBSERVE_POSITION,
    FRONT_OBSERVE_POSITION,
    HOME_POSITION,
    MEDICINE_SLOTS,
    PICK_SPEED,
    PLACE_APPROACH_POSITION,
    PLACE_POSITION,
    get_observe_position,
    move_and_wait,
    pick_medicine_by_slot,
)
from robot_arm_serial import RobotArmSerial, SerialConfig
from vision_selection import (
    CAPTURE_DIRECTORY,
    create_capture_request,
    read_capture_result,
    read_selected_slots,
    write_selected_slots,
)


DEFAULT_SERIAL_PORT = "/dev/ttyACM0"
DEFAULT_BAUDRATE = 115200

robot_lock = threading.Lock()


def slot_to_dict(slot) -> Dict[str, Any]:
    return {
        "index": slot.index,
        "retreat_position": slot.retreat_position,
        "grasp_position": slot.grasp_position,
    }


def slots_payload() -> Dict[str, Any]:
    return {
        "fast_speed": FAST_SPEED,
        "pick_speed": PICK_SPEED,
        "place_position": PLACE_POSITION,
        "place_approach_position": PLACE_APPROACH_POSITION,
        "front_observe_position": FRONT_OBSERVE_POSITION,
        "back_observe_position": BACK_OBSERVE_POSITION,
        "home_position": HOME_POSITION,
        "slots": [slot_to_dict(slot) for slot in MEDICINE_SLOTS],
    }


def pick_slot(payload: Dict[str, Any]) -> Dict[str, Any]:
    slot_index = int(payload["slot_index"])
    batch_payload = dict(payload)
    batch_payload["slot_indices"] = [slot_index]
    result = pick_slots(batch_payload)
    return {
        "slot_index": slot_index,
        "logs": result["logs"],
        "captures": result["captures"],
    }


def wait_for_visual_capture(slot_index: int, timeout: float) -> Dict[str, Any]:
    request_id = create_capture_request(slot_index)
    deadline = time.monotonic() + max(timeout, 0.0)
    while time.monotonic() < deadline:
        result = read_capture_result(request_id)
        if result is not None:
            image_path = result.get("image_path")
            if image_path:
                result["image_url"] = f"/vision/captures/{Path(image_path).name}"
            result["timed_out"] = False
            return result
        time.sleep(0.05)
    return {
        "request_id": request_id,
        "slot_index": slot_index,
        "image_path": None,
        "image_url": None,
        "detected": False,
        "timed_out": True,
    }


def pick_slots(payload: Dict[str, Any]) -> Dict[str, Any]:
    slot_indices = [int(value) for value in payload["slot_indices"]]
    if not slot_indices:
        raise ValueError("slot_indices 不能为空")
    if any(value < 1 or value > 12 for value in slot_indices):
        raise ValueError("slot_indices 中的药仓编号必须在 1 到 12 之间")

    serial_port = str(payload.get("serial_port", DEFAULT_SERIAL_PORT))
    baudrate = int(payload.get("baudrate", DEFAULT_BAUDRATE))
    tolerance = float(payload.get("tolerance", 2.0))
    move_timeout = float(payload.get("move_timeout", 30.0))
    visual_timeout = float(payload.get("visual_timeout", 2.0))
    disable_after = bool(payload.get("disable_after", False))

    logs: List[str] = []
    captures: List[Dict[str, Any]] = []
    try:
        with RobotArmSerial(SerialConfig(port=serial_port, baudrate=baudrate)) as arm:
            first_observe_position = get_observe_position(slot_indices[0])
            logs.append(f"前往第一个观察位：{first_observe_position}")
            move_and_wait(
                arm,
                first_observe_position,
                FAST_SPEED,
                tolerance=tolerance,
                timeout=move_timeout,
                log=logs.append,
            )

            for index, slot_index in enumerate(slot_indices):
                logs.append(f"观察 {slot_index} 号药仓并请求抓取示意图")
                capture = wait_for_visual_capture(slot_index, visual_timeout)
                captures.append(capture)
                if capture["timed_out"]:
                    logs.append("视觉示意图超时，继续执行固定坐标抓取")
                elif not capture["detected"]:
                    logs.append("示意图未检测到目标框，继续执行固定坐标抓取")
                else:
                    logs.append(f"已生成示意图：{capture['image_path']}")

                is_last = index == len(slot_indices) - 1
                completion_position = (
                    HOME_POSITION
                    if is_last
                    else get_observe_position(slot_indices[index + 1])
                )
                pick_medicine_by_slot(
                    arm,
                    slot_index,
                    tolerance=tolerance,
                    timeout=move_timeout,
                    log=logs.append,
                    completion_position=completion_position,
                )

            if disable_after:
                logs.append("失能夹爪")
                arm.hand_disable()
                logs.append("失能机械臂")
                arm.disable()
    finally:
        write_selected_slots([])

    return {"slot_indices": slot_indices, "logs": logs, "captures": captures}


def emergency_stop(payload: Dict[str, Any]) -> Dict[str, Any]:
    serial_port = str(payload.get("serial_port", DEFAULT_SERIAL_PORT))
    baudrate = int(payload.get("baudrate", DEFAULT_BAUDRATE))
    with RobotArmSerial(SerialConfig(port=serial_port, baudrate=baudrate)) as arm:
        arm.stop()
    return {"message": "sent !STOP"}


def disable_robot(payload: Dict[str, Any]) -> Dict[str, Any]:
    serial_port = str(payload.get("serial_port", DEFAULT_SERIAL_PORT))
    baudrate = int(payload.get("baudrate", DEFAULT_BAUDRATE))
    with RobotArmSerial(SerialConfig(port=serial_port, baudrate=baudrate)) as arm:
        arm.hand_disable()
        arm.disable()
    return {"message": "sent !HAND_DIS and !DISABLE"}


class RobotHttpHandler(BaseHTTPRequestHandler):
    server_version = "RobotMedicineHTTP/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self.write_json(200, {"ok": True, "service": "robot-medicine-picker"})
            return
        if self.path == "/slots":
            self.write_json(200, {"ok": True, "data": slots_payload()})
            return
        if self.path == "/vision/selection":
            self.write_json(200, {"ok": True, "data": {"slot_indices": read_selected_slots()}})
            return
        if self.path.startswith("/vision/captures/"):
            filename = self.path.removeprefix("/vision/captures/")
            if not filename or Path(filename).name != filename:
                self.write_json(400, {"ok": False, "error": "invalid capture filename"})
                return
            image_path = CAPTURE_DIRECTORY / filename
            if not image_path.is_file():
                self.write_json(404, {"ok": False, "error": "capture not found"})
                return
            self.write_bytes(200, image_path.read_bytes(), "image/jpeg")
            return
        self.write_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            if self.path in ("/pick", "/pick-batch"):
                if not robot_lock.acquire(blocking=False):
                    self.write_json(409, {"ok": False, "error": "robot is busy"})
                    return
                try:
                    result = pick_slot(payload) if self.path == "/pick" else pick_slots(payload)
                finally:
                    robot_lock.release()
                self.write_json(200, {"ok": True, "data": result})
                return
            if self.path == "/stop":
                result = emergency_stop(payload)
                self.write_json(200, {"ok": True, "data": result})
                return
            if self.path == "/disable":
                result = disable_robot(payload)
                self.write_json(200, {"ok": True, "data": result})
                return
            if self.path == "/vision/selection":
                selected = write_selected_slots(payload.get("slot_indices", []))
                self.write_json(200, {"ok": True, "data": {"slot_indices": selected}})
                return
            self.write_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            self.write_json(500, {"ok": False, "error": str(exc)})

    def read_json(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode("utf-8"))

    def write_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt: str, *args: Tuple[Any, ...]) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="机械臂抓药 HTTP 网络服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), RobotHttpHandler)
    print(f"Robot medicine HTTP server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping HTTP server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
