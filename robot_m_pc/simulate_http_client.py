"""Simulate the PC decision app calling the board HTTP robot service."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any, Dict


def request_json(method: str, url: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=None) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"ok": False, "status": exc.code, "error": text}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="模拟电脑端调用抓药 HTTP 服务")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="板卡 HTTP 服务地址")
    parser.add_argument("--health", action="store_true", help="检查服务是否在线")
    parser.add_argument("--slots", action="store_true", help="查看药仓配置")
    parser.add_argument("--pick-slot", type=int, help="抓取指定药仓，会控制真机")
    parser.add_argument("--pick-slots", help="批量抓药，例如 2,11,5，会控制真机")
    parser.add_argument("--select-slots", help="让视觉画面只显示指定药仓，例如 1,3,5；空字符串表示显示全部")
    parser.add_argument("--get-selection", action="store_true", help="读取当前视觉药仓选择")
    parser.add_argument("--stop", action="store_true", help="发送急停")
    parser.add_argument("--disable", action="store_true", help="失能夹爪和机械臂")
    parser.add_argument("--disable-after", action="store_true", help="抓药完成后自动失能")
    parser.add_argument("--serial-port", default="/dev/ttyACM0", help="板卡上的机械臂串口")
    parser.add_argument("--baudrate", type=int, default=115200, help="串口波特率")
    parser.add_argument("--tolerance", type=float, default=2.0, help="等待到位容差")
    parser.add_argument("--move-timeout", type=float, default=30.0, help="每段运动超时")
    parser.add_argument("--visual-timeout", type=float, default=2.0, help="每次等待示意图的最长时间")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")

    if args.health:
        result = request_json("GET", f"{base_url}/health")
    elif args.slots:
        result = request_json("GET", f"{base_url}/slots")
    elif args.get_selection:
        result = request_json("GET", f"{base_url}/vision/selection")
    elif args.select_slots is not None:
        selected = [] if not args.select_slots.strip() else [int(value) for value in args.select_slots.split(",")]
        result = request_json(
            "POST",
            f"{base_url}/vision/selection",
            {"slot_indices": selected},
        )
    elif args.stop:
        result = request_json("POST", f"{base_url}/stop", {"serial_port": args.serial_port, "baudrate": args.baudrate})
    elif args.disable:
        result = request_json("POST", f"{base_url}/disable", {"serial_port": args.serial_port, "baudrate": args.baudrate})
    elif args.pick_slot is not None:
        result = request_json(
            "POST",
            f"{base_url}/pick",
            {
                "slot_index": args.pick_slot,
                "serial_port": args.serial_port,
                "baudrate": args.baudrate,
                "tolerance": args.tolerance,
                "move_timeout": args.move_timeout,
                "visual_timeout": args.visual_timeout,
                "disable_after": args.disable_after,
            },
        )
    elif args.pick_slots:
        slot_indices = [int(value) for value in args.pick_slots.split(",")]
        result = request_json(
            "POST",
            f"{base_url}/pick-batch",
            {
                "slot_indices": slot_indices,
                "serial_port": args.serial_port,
                "baudrate": args.baudrate,
                "tolerance": args.tolerance,
                "move_timeout": args.move_timeout,
                "visual_timeout": args.visual_timeout,
                "disable_after": args.disable_after,
            },
        )
    else:
        raise SystemExit(
            "请指定 --health、--slots、--select-slots、--get-selection、"
            "--pick-slot、--pick-slots、--stop 或 --disable"
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
