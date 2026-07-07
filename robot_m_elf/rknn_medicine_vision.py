"""Detect medicine boxes from a RealSense D435 using an RKNN YOLO model.

Examples:
    python3 rknn_medicine_vision.py
    python3 rknn_medicine_vision.py --slots 1,3,5

Without ``--slots``, the current target slot is read from
``vision_selection.json``. Because the camera is mounted on the robot hand,
the detected box nearest the image center is treated as the current target.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from rknnlite.api import RKNNLite

try:
    import cv2
except ImportError as exc:
    raise SystemExit(
        "当前 Python 环境缺少 cv2。请退出未安装 OpenCV 的 .venv，"
        "或在该环境安装 opencv-python。"
    ) from exc

from realsense_camera import RealSenseCamera
from image_store import write_jpeg_atomic
from vision_selection import (
    CAPTURE_DIRECTORY,
    VISION_LATEST_IMAGE,
    normalize_slots,
    read_selection_state,
    write_capture_result,
)


MODEL_SIZE = 640
DFL_BINS = 16
NPU_CORE_MASKS = {
    "auto": RKNNLite.NPU_CORE_AUTO,
    "0": RKNNLite.NPU_CORE_0,
    "1": RKNNLite.NPU_CORE_1,
    "2": RKNNLite.NPU_CORE_2,
}


@dataclass
class Detection:
    box: np.ndarray
    score: float
    slot_index: Optional[int] = None

    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return (float(x1 + x2) / 2.0, float(y1 + y2) / 2.0)


class RknnYoloDetector:
    def __init__(
        self,
        model_path: str,
        confidence: float = 0.35,
        iou_threshold: float = 0.45,
        core_mask: int = RKNNLite.NPU_CORE_AUTO,
    ) -> None:
        self.model_path = model_path
        self.confidence = confidence
        self.iou_threshold = iou_threshold
        self.core_mask = core_mask
        self.rknn = RKNNLite()

    def start(self) -> None:
        result = self.rknn.load_rknn(self.model_path)
        if result != 0:
            raise RuntimeError(f"加载 RKNN 模型失败，错误码：{result}")
        result = self.rknn.init_runtime(core_mask=self.core_mask)
        if result != 0:
            raise RuntimeError(f"初始化 RKNN 运行时失败，错误码：{result}")

    def close(self) -> None:
        self.rknn.release()

    def __enter__(self) -> "RknnYoloDetector":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def detect(self, bgr_image: np.ndarray) -> List[Detection]:
        model_image, scale, pad_x, pad_y = letterbox(bgr_image, MODEL_SIZE)
        rgb_image = cv2.cvtColor(model_image, cv2.COLOR_BGR2RGB)
        model_input = np.expand_dims(rgb_image, axis=0)
        outputs = self.rknn.inference(inputs=[model_input], data_format="nhwc")
        if outputs is None:
            raise RuntimeError("RKNN 推理失败，未返回输出")
        if len(outputs) < 8:
            raise RuntimeError("RKNN 推理输出数量异常")

        boxes: List[np.ndarray] = []
        scores: List[np.ndarray] = []
        for box_index, score_index in ((0, 1), (3, 4), (6, 7)):
            branch_boxes, branch_scores = decode_branch(
                np.asarray(outputs[box_index]),
                np.asarray(outputs[score_index]),
            )
            boxes.append(branch_boxes)
            scores.append(branch_scores)

        all_boxes = np.concatenate(boxes, axis=0)
        all_scores = np.concatenate(scores, axis=0)
        keep = all_scores >= self.confidence
        all_boxes = all_boxes[keep]
        all_scores = all_scores[keep]
        if len(all_boxes) == 0:
            return []

        kept_indices = nms(all_boxes, all_scores, self.iou_threshold)
        height, width = bgr_image.shape[:2]
        detections: List[Detection] = []
        for index in kept_indices:
            box = all_boxes[index].astype(np.float32)
            box[[0, 2]] = (box[[0, 2]] - pad_x) / scale
            box[[1, 3]] = (box[[1, 3]] - pad_y) / scale
            box[[0, 2]] = np.clip(box[[0, 2]], 0, width - 1)
            box[[1, 3]] = np.clip(box[[1, 3]], 0, height - 1)
            detections.append(Detection(box=box, score=float(all_scores[index])))
        return detections


def letterbox(image: np.ndarray, size: int) -> Tuple[np.ndarray, float, int, int]:
    height, width = image.shape[:2]
    scale = min(size / width, size / height)
    resized_width = int(round(width * scale))
    resized_height = int(round(height * scale))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    pad_x = (size - resized_width) // 2
    pad_y = (size - resized_height) // 2
    output = np.full((size, size, 3), 114, dtype=np.uint8)
    output[pad_y : pad_y + resized_height, pad_x : pad_x + resized_width] = resized
    return output, scale, pad_x, pad_y


def decode_branch(box_output: np.ndarray, score_output: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    box_output = ensure_nchw(box_output, expected_channels=64)
    score_output = ensure_nchw(score_output, expected_channels=1)
    _, _, height, width = box_output.shape
    stride = MODEL_SIZE / height

    distributions = box_output.reshape(1, 4, DFL_BINS, height, width).astype(np.float32)
    distributions -= distributions.max(axis=2, keepdims=True)
    probabilities = np.exp(distributions)
    probabilities /= probabilities.sum(axis=2, keepdims=True)
    bins = np.arange(DFL_BINS, dtype=np.float32).reshape(1, 1, DFL_BINS, 1, 1)
    distances = (probabilities * bins).sum(axis=2)[0]

    grid_x, grid_y = np.meshgrid(np.arange(width), np.arange(height))
    center_x = grid_x.astype(np.float32) + 0.5
    center_y = grid_y.astype(np.float32) + 0.5
    x1 = (center_x - distances[0]) * stride
    y1 = (center_y - distances[1]) * stride
    x2 = (center_x + distances[2]) * stride
    y2 = (center_y + distances[3]) * stride
    boxes = np.stack((x1, y1, x2, y2), axis=-1).reshape(-1, 4)
    scores = score_output[0, 0].astype(np.float32).reshape(-1)
    return boxes, scores


def ensure_nchw(output: np.ndarray, expected_channels: int) -> np.ndarray:
    if output.ndim != 4:
        raise RuntimeError(f"不支持的 RKNN 输出形状：{output.shape}")
    if output.shape[1] == expected_channels:
        return output
    if output.shape[-1] == expected_channels:
        return output.transpose(0, 3, 1, 2)
    raise RuntimeError(f"RKNN 输出通道异常：{output.shape}，期望 {expected_channels}")


def nms(boxes: np.ndarray, scores: np.ndarray, threshold: float) -> List[int]:
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size > 0:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break
        remaining = order[1:]
        intersection_x1 = np.maximum(x1[current], x1[remaining])
        intersection_y1 = np.maximum(y1[current], y1[remaining])
        intersection_x2 = np.minimum(x2[current], x2[remaining])
        intersection_y2 = np.minimum(y2[current], y2[remaining])
        intersection = np.maximum(0, intersection_x2 - intersection_x1) * np.maximum(
            0, intersection_y2 - intersection_y1
        )
        union = areas[current] + areas[remaining] - intersection
        iou = intersection / np.maximum(union, 1e-6)
        order = remaining[iou <= threshold]
    return keep


def parse_slot_list(value: Optional[str]) -> Optional[List[int]]:
    if value is None:
        return None
    if not value.strip():
        return []
    return normalize_slots([int(item.strip()) for item in value.split(",")])


def draw_detections(
    image: np.ndarray,
    detections: Sequence[Detection],
    selected_slots: Sequence[int],
) -> Tuple[np.ndarray, bool]:
    output = image.copy()
    target_slot = selected_slots[0] if selected_slots else None
    target_found = False
    visible_detections: List[Detection] = []
    if target_slot is not None:
        target = choose_slot_target(
            detections,
            target_slot,
        )
        visible_detections = [target] if target is not None else []
        target_found = target is not None

    for detection in visible_detections:
        if target_slot is not None:
            label = f"target slot {target_slot} {detection.score:.2f}"
            color = (0, 220, 0)
        else:
            label = f"medicine box {detection.score:.2f}"
            color = (0, 180, 255)

        x1, y1, x2, y2 = detection.box.astype(int)
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        cv2.putText(output, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return output, target_found


def choose_slot_target(
    detections: Sequence[Detection],
    slot_index: int,
) -> Optional[Detection]:
    if not detections:
        return None

    if slot_index <= 9:
        if len(detections) < 3:
            return None
        x_centers = cluster_axis([item.center[0] for item in detections], 3)
        y_centers = cluster_axis([item.center[1] for item in detections], 3)
        target_row = (slot_index - 1) // 3
        target_column = (slot_index - 1) % 3
        candidates = [
            detection
            for detection in detections
            if nearest_cluster(detection.center[0], x_centers) == target_column
            and nearest_cluster(detection.center[1], y_centers) == target_row
        ]
    else:
        x_centers = cluster_axis([item.center[0] for item in detections], 3)
        target_column = slot_index - 10
        candidates = [
            detection
            for detection in detections
            if nearest_cluster(detection.center[0], x_centers) == target_column
        ]

    if not candidates:
        return None
    return max(candidates, key=lambda detection: detection.score)


def cluster_axis(values: Sequence[float], cluster_count: int) -> List[float]:
    values_array = np.asarray(values, dtype=np.float32)
    if len(values_array) == 0:
        return []
    if len(values_array) < cluster_count:
        minimum = float(values_array.min())
        maximum = float(values_array.max())
        return np.linspace(minimum, maximum, cluster_count).tolist()

    sorted_values = np.sort(values_array)
    initial_indices = np.linspace(0, len(sorted_values) - 1, cluster_count).round().astype(int)
    centers = sorted_values[initial_indices]
    for _ in range(20):
        distances = np.abs(values_array[:, None] - centers[None, :])
        labels = distances.argmin(axis=1)
        updated = np.array(
            [
                values_array[labels == index].mean() if np.any(labels == index) else centers[index]
                for index in range(cluster_count)
            ],
            dtype=np.float32,
        )
        if np.allclose(updated, centers):
            break
        centers = updated
    return sorted(float(value) for value in centers)


def nearest_cluster(value: float, centers: Sequence[float]) -> int:
    return min(range(len(centers)), key=lambda index: abs(value - centers[index]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D435 + RKNN 药盒识别与指定药仓框选")
    parser.add_argument("--model", default="models/best_fp.rknn", help="RKNN 模型路径")
    parser.add_argument("--confidence", type=float, default=0.35, help="置信度阈值")
    parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU 阈值")
    parser.add_argument("--slots", help="固定显示药仓，例如 1,3,5；不传则读取 HTTP 选择状态")
    parser.add_argument("--width", type=int, default=640, help="D435 彩色画面宽度")
    parser.add_argument("--height", type=int, default=480, help="D435 彩色画面高度")
    parser.add_argument("--fps", type=int, default=30, help="D435 帧率")
    parser.add_argument("--camera-serial", help="抓药观察 D435 的设备序列号")
    parser.add_argument("--npu-core", choices=NPU_CORE_MASKS, default="0", help="使用的 RK3588 NPU 核")
    parser.add_argument("--no-preview", action="store_true", help="无窗口后台运行")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixed_slots = parse_slot_list(args.slots)
    model_path = str(Path(args.model).resolve())
    previous_time = time.monotonic()
    handled_capture_request: Optional[str] = None

    with RknnYoloDetector(
        model_path,
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
            print("按 q/ESC 退出；抓药时自动只框选画面中心附近的当前目标药盒")
            while True:
                color_image, _ = camera.read()
                selection_state = read_selection_state()
                selected_slots = fixed_slots if fixed_slots is not None else selection_state["slot_indices"]
                if selected_slots:
                    detections = detector.detect(color_image)
                    display, target_found = draw_detections(color_image, detections, selected_slots)
                else:
                    detections = []
                    display = color_image.copy()
                    target_found = False

                now = time.monotonic()
                fps = 1.0 / max(now - previous_time, 1e-6)
                previous_time = now
                status = f"detected:{len(detections)}"
                selected_text = "all" if not selected_slots else ",".join(map(str, selected_slots))
                cv2.putText(
                    display,
                    f"{status} selected:{selected_text} FPS:{fps:.1f}",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                )

                capture_request_id = selection_state.get("capture_request_id")
                if (
                    fixed_slots is None
                    and capture_request_id
                    and capture_request_id != handled_capture_request
                    and selected_slots
                ):
                    CAPTURE_DIRECTORY.mkdir(parents=True, exist_ok=True)
                    image_path = CAPTURE_DIRECTORY / (
                        f"{capture_request_id}_slot_{selected_slots[0]}.jpg"
                    )
                    saved = write_jpeg_atomic(image_path, display)
                    if saved:
                        write_capture_result(
                            capture_request_id,
                            selected_slots[0],
                            str(image_path),
                            target_found,
                        )
                        handled_capture_request = capture_request_id
                write_jpeg_atomic(VISION_LATEST_IMAGE, display, quality=55)
                if args.no_preview:
                    continue
                cv2.imshow("Medicine Box Detection", display)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
