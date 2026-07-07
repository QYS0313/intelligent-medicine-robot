"""RealSense camera utility for previewing and capturing frames.

Examples:
    python3 realsense_camera.py --preview
    python3 realsense_camera.py --save-color /tmp/color.jpg
    python3 realsense_camera.py --save-color /tmp/color.jpg --save-depth /tmp/depth.png
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pyrealsense2 as rs

try:
    import cv2
except ImportError as exc:
    raise SystemExit(
        "当前 Python 环境缺少 cv2/OpenCV。\n"
        "如果你在 .venv 里运行，请安装：pip install opencv-python\n"
        "如果系统 Python 已经有 cv2，也可以退出虚拟环境后运行：deactivate && python3 realsense_camera.py --preview"
    ) from exc


class RealSenseCamera:
    def __init__(
        self,
        color_width: int = 640,
        color_height: int = 480,
        depth_width: int = 640,
        depth_height: int = 480,
        fps: int = 30,
        enable_depth: bool = True,
    ) -> None:
        self.color_width = color_width
        self.color_height = color_height
        self.depth_width = depth_width
        self.depth_height = depth_height
        self.fps = fps
        self.enable_depth = enable_depth
        self.pipeline = rs.pipeline()
        self.config = rs.config()
        self.align = rs.align(rs.stream.color)
        self.profile = None

    def start(self) -> None:
        self.config.enable_stream(
            rs.stream.color,
            self.color_width,
            self.color_height,
            rs.format.bgr8,
            self.fps,
        )
        if self.enable_depth:
            self.config.enable_stream(
                rs.stream.depth,
                self.depth_width,
                self.depth_height,
                rs.format.z16,
                self.fps,
            )
        self.profile = self.pipeline.start(self.config)

        # Let auto exposure settle a little before using frames.
        for _ in range(10):
            self.pipeline.wait_for_frames()

    def stop(self) -> None:
        self.pipeline.stop()

    def __enter__(self) -> "RealSenseCamera":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()

    def read(self) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        frames = self.pipeline.wait_for_frames()
        if self.enable_depth:
            frames = self.align.process(frames)

        color_frame = frames.get_color_frame()
        if not color_frame:
            raise RuntimeError("未读取到 RealSense 彩色帧")

        color_image = np.asanyarray(color_frame.get_data())
        depth_image = None
        if self.enable_depth:
            depth_frame = frames.get_depth_frame()
            if depth_frame:
                depth_image = np.asanyarray(depth_frame.get_data())

        return color_image, depth_image

    def get_depth_scale(self) -> Optional[float]:
        if not self.enable_depth or self.profile is None:
            return None
        depth_sensor = self.profile.get_device().first_depth_sensor()
        return float(depth_sensor.get_depth_scale())


def save_frame(path: str, image: np.ndarray) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(output_path), image)
    if not ok:
        raise RuntimeError(f"保存图片失败：{output_path}")


def preview(camera: RealSenseCamera, window_name: str = "RealSense") -> None:
    print("按 q 或 ESC 退出预览")
    while True:
        color_image, depth_image = camera.read()
        display = color_image
        if depth_image is not None:
            depth_colormap = cv2.applyColorMap(
                cv2.convertScaleAbs(depth_image, alpha=0.03),
                cv2.COLORMAP_JET,
            )
            display = np.hstack((color_image, depth_colormap))

        cv2.imshow(window_name, display)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
    cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RealSense 摄像头启动/采集脚本")
    parser.add_argument("--preview", action="store_true", help="打开预览窗口")
    parser.add_argument("--save-color", help="保存一张彩色图，例如 /tmp/color.jpg")
    parser.add_argument("--save-depth", help="保存一张 16-bit 深度图，例如 /tmp/depth.png")
    parser.add_argument("--no-depth", action="store_true", help="只开启彩色流")
    parser.add_argument("--width", type=int, default=640, help="彩色图宽度")
    parser.add_argument("--height", type=int, default=480, help="彩色图高度")
    parser.add_argument("--fps", type=int, default=30, help="帧率")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not any([args.preview, args.save_color, args.save_depth]):
        raise SystemExit("请指定 --preview、--save-color 或 --save-depth")

    with RealSenseCamera(
        color_width=args.width,
        color_height=args.height,
        depth_width=args.width,
        depth_height=args.height,
        fps=args.fps,
        enable_depth=not args.no_depth,
    ) as camera:
        depth_scale = camera.get_depth_scale()
        if depth_scale is not None:
            print(f"Depth scale: {depth_scale} meter/unit")

        if args.preview:
            preview(camera)

        if args.save_color or args.save_depth:
            # Give the camera one more moment after preview or startup.
            time.sleep(0.1)
            color_image, depth_image = camera.read()
            if args.save_color:
                save_frame(args.save_color, color_image)
                print(f"Saved color image: {args.save_color}")
            if args.save_depth:
                if depth_image is None:
                    raise RuntimeError("深度流未开启，无法保存深度图")
                save_frame(args.save_depth, depth_image)
                print(f"Saved depth image: {args.save_depth}")


if __name__ == "__main__":
    main()
