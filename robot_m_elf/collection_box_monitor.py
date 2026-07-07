"""Second D435 process that counts medicine boxes in the collection area."""

from __future__ import annotations

import argparse
import time
from collections import Counter, deque
from typing import Deque, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except ImportError as exc:
    raise SystemExit(
        "当前 Python 环境缺少 cv2。请退出未安装 OpenCV 的 .venv，"
        "或在该环境安装 opencv-python。"
    ) from exc

from collection_status import LATEST_IMAGE, read_status, update_detected_count
from image_store import write_jpeg_atomic
from realsense_camera import RealSenseCamera
from rknn_medicine_vision import Detection, NPU_CORE_MASKS, RknnYoloDetector


def parse_roi(value: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    if value is None:
        return None
    parts = [int(item.strip()) for item in value.split(",")]
    if len(parts) != 4:
        raise ValueError("ROI 格式必须是 x1,y1,x2,y2")
    x1, y1, x2, y2 = parts
    if x2 <= x1 or y2 <= y1:
        raise ValueError("ROI 的 x2/y2 必须大于 x1/y1")
    return x1, y1, x2, y2


def filter_roi(
    detections: Sequence[Detection],
    roi: Optional[Tuple[int, int, int, int]],
) -> List[Detection]:
    if roi is None:
        return list(detections)
    x1, y1, x2, y2 = roi
    return [
        detection
        for detection in detections
        if x1 <= detection.center[0] <= x2 and y1 <= detection.center[1] <= y2
    ]


def stable_count(history: Sequence[int], minimum_samples: int, ratio: float) -> Tuple[int, bool]:
    if not history:
        return 0, False
    count, occurrences = Counter(history).most_common(1)[0]
    stable = len(history) >= minimum_samples and occurrences / len(history) >= ratio
    return int(count), stable


def draw_monitor_frame(
    image: np.ndarray,
    detections: Sequence[Detection],
    roi: Optional[Tuple[int, int, int, int]],
    detected_count: int,
    stable: bool,
) -> np.ndarray:
    output = image.copy()
    if roi is not None:
        x1, y1, x2, y2 = roi
        cv2.rectangle(output, (x1, y1), (x2, y2), (255, 180, 0), 2)

    for index, detection in enumerate(detections, start=1):
        x1, y1, x2, y2 = detection.box.astype(int)
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 220, 0), 2)
        cv2.putText(
            output,
            f"box {index} {detection.score:.2f}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 220, 0),
            2,
        )

    status = read_status()
    expected = int(status.get("expected_count", 0))
    complete = bool(status.get("active") and stable and detected_count == expected)
    color = (0, 220, 0) if complete else (0, 180, 255)
    cv2.putText(
        output,
        f"count:{detected_count}/{expected} stable:{stable} complete:{complete}",
        (10, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        color,
        2,
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第二个 D435 收药盒数量监控")
    parser.add_argument("--model", default="models/medicine_fp.rknn", help="RKNN 模型路径")
    parser.add_argument("--camera-serial", required=True, help="收药监控 D435 的设备序列号")
    parser.add_argument("--confidence", type=float, default=0.35, help="置信度阈值")
    parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU 阈值")
    parser.add_argument("--roi", help="只统计指定区域，格式 x1,y1,x2,y2")
    parser.add_argument("--window", type=int, default=15, help="稳定计数帧窗口")
    parser.add_argument("--stable-ratio", type=float, default=0.8, help="众数占比达到该值视为稳定")
    parser.add_argument("--width", type=int, default=640, help="画面宽度")
    parser.add_argument("--height", type=int, default=480, help="画面高度")
    parser.add_argument("--fps", type=int, default=30, help="帧率")
    parser.add_argument("--no-preview", action="store_true", help="无窗口后台运行")
    parser.add_argument("--npu-core", choices=NPU_CORE_MASKS, default="1", help="使用的 RK3588 NPU 核")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.window < 1:
        raise SystemExit("--window 必须大于等于 1")
    if not 0 < args.stable_ratio <= 1:
        raise SystemExit("--stable-ratio 必须在 0 到 1 之间")

    roi = parse_roi(args.roi)
    history: Deque[int] = deque(maxlen=args.window)
    last_status_write = 0.0

    with RknnYoloDetector(
        args.model,
        args.confidence,
        args.iou,
        core_mask=NPU_CORE_MASKS[args.npu_core],
    ) as detector:
        with RealSenseCamera(
            color_width=args.width,
            color_height=args.height,
            fps=args.fps,
            enable_depth=False,
            device_serial=args.camera_serial,
        ) as camera:
            print("收药盒监控已启动；按 q/ESC 退出")
            while True:
                color_image, _ = camera.read()
                detections = filter_roi(detector.detect(color_image), roi)
                history.append(len(detections))
                detected_count, stable = stable_count(
                    list(history),
                    minimum_samples=args.window,
                    ratio=args.stable_ratio,
                )

                now = time.monotonic()
                if now - last_status_write >= 0.2:
                    update_detected_count(detected_count, stable)
                    last_status_write = now

                display = draw_monitor_frame(
                    color_image,
                    detections,
                    roi,
                    detected_count,
                    stable,
                )
                write_jpeg_atomic(LATEST_IMAGE, display, quality=55)

                if args.no_preview:
                    continue
                cv2.imshow("Collection Box Monitor", display)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
