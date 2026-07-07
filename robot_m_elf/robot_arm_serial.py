"""Low-level serial control wrapper for the robot arm.

This module only knows how to format and send the controller's serial
commands. Higher-level medicine picking workflows should call these methods
instead of building command strings directly.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, Union


Number = Union[int, float]
_NUMBER_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def _is_number_token(token: str) -> bool:
    return bool(_NUMBER_RE.match(token.strip()))


def _parse_numbers(line: str) -> Optional[List[float]]:
    text = line.replace("\x00", "").strip()
    if not text:
        return None
    if text.lower().startswith("ok "):
        text = text[3:].strip()
    elif text.lower() == "ok":
        return None
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    text = text.replace(",", " ")
    parts = [part for part in text.split() if part]
    if not parts:
        return None
    if not all(_is_number_token(part) for part in parts):
        return None
    return [float(part) for part in parts]


def _looks_like_pose(line: str) -> bool:
    numbers = _parse_numbers(line)
    return numbers is not None and len(numbers) >= 6


def _looks_like_joint(line: str) -> bool:
    numbers = _parse_numbers(line)
    return numbers is not None and len(numbers) >= 6


def _normalize_numbers(line: str) -> str:
    numbers = _parse_numbers(line)
    if numbers is None:
        return ""
    return " ".join(f"{value:.6f}".rstrip("0").rstrip(".") for value in numbers)


@dataclass(frozen=True)
class SerialConfig:
    port: str = "/dev/ttyACM0"
    baudrate: int = 115200
    timeout: float = 0.1
    write_timeout: float = 1.0
    reply_wait: float = 0.02
    reply_timeout: float = 1.5
    terminator: str = "\r\n"
    encoding: str = "utf-8"


class RobotArmSerial:
    """Robot arm command client over a serial port."""

    def __init__(self, config: Optional[SerialConfig] = None) -> None:
        self.config = config or SerialConfig()
        self._serial = None
        self._serial_lock = threading.Lock()
        self._robot_enabled = False
        self._gripper_enabled = False

    @property
    def is_open(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def open(self) -> None:
        """Open the serial port."""
        if self.is_open:
            return

        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("缺少 pyserial，请先安装：pip install pyserial") from exc

        self._serial = serial.Serial(
            port=self.config.port,
            baudrate=self.config.baudrate,
            timeout=self.config.timeout,
            write_timeout=self.config.write_timeout,
        )

    def close(self) -> None:
        """Close the serial port."""
        if self._serial:
            self._serial.close()
            self._serial = None
        self._robot_enabled = False
        self._gripper_enabled = False

    def __enter__(self) -> "RobotArmSerial":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def send_command(self, command: str, read_response: bool = True) -> Optional[str]:
        """Send a raw command string.

        Args:
            command: Command without line terminator, for example ``!HOME``.
            read_response: Whether to wait for the controller reply after writing.
        """
        if not self.is_open:
            self.open()

        command = command.strip()
        if not command:
            raise ValueError("command 不能为空")

        payload = f"{command}{self.config.terminator}".encode(self.config.encoding)
        with self._serial_lock:
            self._serial.reset_input_buffer()
            self._serial.write(payload)
            self._serial.flush()

            if not read_response:
                return None

            time.sleep(self.config.reply_wait)
            reply, ignored, read_error = self._read_reply_until_match(command)
            if read_error:
                raise RuntimeError(read_error)

        if ignored:
            print(f"[WARN] ignored serial replies: {ignored}", file=sys.stderr)

        if not reply:
            if command.startswith("#GETLPOS"):
                raise RuntimeError("no valid pose reply")
            if command.startswith("#GETJPOS"):
                raise RuntimeError("no valid joint reply")
            return None

        if command.startswith("#GETLPOS") or command.startswith("#GETJPOS"):
            normalized = _normalize_numbers(reply)
            if not normalized:
                raise RuntimeError(f"invalid data format: {reply}")
            return normalized

        return reply

    def _read_reply_until_match(self, command: str) -> Tuple[str, List[str], str]:
        deadline = time.time() + self.config.reply_timeout
        ignored_lines: List[str] = []
        is_pose_query = command.startswith("#GETLPOS")
        is_joint_query = command.startswith("#GETJPOS")

        while time.time() < deadline:
            try:
                raw = self._serial.readline()
            except Exception as exc:
                return "", ignored_lines, f"serial read failed: {exc}"

            line = raw.decode(self.config.encoding, errors="ignore").strip()
            if not line:
                continue

            if is_pose_query:
                if _looks_like_pose(line):
                    return line, ignored_lines, ""
                ignored_lines.append(line)
                continue

            if is_joint_query:
                if _looks_like_joint(line):
                    return line, ignored_lines, ""
                ignored_lines.append(line)
                continue

            return line, ignored_lines, ""

        return "", ignored_lines, ""

    # 1. Basic commands

    def stop(self) -> None:
        """!STOP: emergency stop."""
        self.send_command("!STOP")
        self._robot_enabled = False
        self._gripper_enabled = False

    def start(self) -> None:
        """!START: enable robot."""
        self.send_command("!START")
        self._robot_enabled = True

    def home(self) -> None:
        """!HOME: return to home position."""
        self._ensure_robot_enabled()
        self.send_command("!HOME")

    def calibration(self) -> None:
        """!CALIBRATION: calibrate home offset."""
        self._ensure_robot_enabled()
        self.send_command("!CALIBRATION")

    def reset(self) -> None:
        """!RESET: move to resting/reset posture."""
        self._ensure_robot_enabled()
        self.send_command("!RESET")

    def disable(self) -> None:
        """!DISABLE: disable robot."""
        self.send_command("!DISABLE")
        self._robot_enabled = False
        self._gripper_enabled = False

    # 2. Gripper commands

    def hand_open_current(self) -> None:
        """!HAND_C: open gripper in current mode."""
        self._ensure_gripper_enabled()
        self.send_command("!HAND_C")

    def hand_close_current(self) -> None:
        """!HAND_O: close gripper in current mode."""
        self._ensure_gripper_enabled()
        self.send_command("!HAND_O")

    def hand_enable(self) -> None:
        """!HAND_EN: enable gripper."""
        self._ensure_robot_enabled()
        self.send_command("!HAND_EN")
        self._gripper_enabled = True

    def hand_disable(self) -> None:
        """!HAND_DIS: disable gripper."""
        self._ensure_robot_enabled()
        self.send_command("!HAND_DIS")
        self._gripper_enabled = False

    def hand_zero(self) -> None:
        """!HAND_ZERO: calibrate gripper zero/travel."""
        self._ensure_gripper_enabled()
        self.send_command("!HAND_ZERO")

    def hand_position(self, position: int) -> None:
        """!HAND_POS <1-100>: set gripper position."""
        self._require_range("position", position, 1, 100)
        self._ensure_gripper_enabled()
        self.send_command(f"!HAND_POS {position}")

    def hand_current(self, current: Number) -> None:
        """!HAND_I <0-2.0>: set gripper current parameter."""
        self._require_range("current", current, 0, 2.0)
        self._ensure_gripper_enabled()
        self.send_command(f"!HAND_I {self._fmt_number(current)}")

    # 3. Parameter/query commands

    def get_joint_position(self) -> Optional[str]:
        """#GETJPOS: read joint angles."""
        return self.send_command("#GETJPOS", read_response=True)

    def get_joint_values(self) -> List[float]:
        """#GETJPOS: read joint angles as float values."""
        response = self.get_joint_position()
        if not response:
            raise RuntimeError("empty joint position response")
        values = _parse_numbers(response)
        if values is None or len(values) < 6:
            raise RuntimeError(f"invalid joint position response: {response}")
        return values[:6]

    def get_linear_position(self) -> Optional[str]:
        """#GETLPOS: read end-effector pose."""
        return self.send_command("#GETLPOS", read_response=True)

    def wait_until_joint_position(
        self,
        target: Sequence[Number],
        tolerance: float = 2.0,
        timeout: float = 30.0,
        poll_interval: float = 0.1,
    ) -> List[float]:
        """Wait until the first six joint angles are close to target.

        This is used before immediate commands such as gripper operations or
        disable, because those commands are not necessarily part of the motion
        queue.
        """
        if len(target) != 6:
            raise ValueError("target 必须包含 6 个关节角")

        deadline = time.time() + timeout
        target_values = [float(value) for value in target]
        last_values: List[float] = []

        while time.time() < deadline:
            try:
                last_values = self.get_joint_values()
            except RuntimeError as exc:
                print(f"[WARN] read joint position failed, retrying: {exc}", file=sys.stderr)
                time.sleep(poll_interval)
                continue
            if all(abs(current - wanted) <= tolerance for current, wanted in zip(last_values, target_values)):
                return last_values
            time.sleep(poll_interval)

        raise TimeoutError(f"等待关节到位超时，目标={target_values}，最后位置={last_values}")

    def set_command_mode(self, mode: Union[int, str]) -> None:
        """#CMDMODE <mode>: set command mode."""
        self._ensure_robot_enabled()
        self.send_command(f"#CMDMODE {mode}")

    def set_dce_kv(self, node: int, value: Number) -> None:
        """#SET_DCE_KV <node> <value>."""
        self._send_node_value("#SET_DCE_KV", node, value)

    def set_dce_kp(self, node: int, value: Number) -> None:
        """#SET_DCE_KP <node> <value>."""
        self._send_node_value("#SET_DCE_KP", node, value)

    def set_dce_ki(self, node: int, value: Number) -> None:
        """#SET_DCE_KI <node> <value>."""
        self._send_node_value("#SET_DCE_KI", node, value)

    def set_dce_kd(self, node: int, value: Number) -> None:
        """#SET_DCE_KD <node> <value>."""
        self._send_node_value("#SET_DCE_KD", node, value)

    def reboot_node(self, node: int) -> None:
        """#REBOOT <node>: reboot a motor node."""
        self._require_node(node)
        self._ensure_robot_enabled()
        self.send_command(f"#REBOOT {node}")

    def set_home_offset_for_node(self, node: int) -> None:
        """#OFFSET_J <node>: set current position as the node's home offset."""
        self._require_node(node)
        self._ensure_robot_enabled()
        self.send_command(f"#OFFSET_J {node}")

    def set_joint_acceleration(self, node: int, value: Number) -> None:
        """#ACC_J <node> <value>: set acceleration."""
        self._send_node_value("#ACC_J", node, value)

    def set_joint_speed_limit(self, node: int, value: Number) -> None:
        """#SPEED_J <node> <value>: set speed limit."""
        self._send_node_value("#SPEED_J", node, value)

    def set_joint_current_limit(self, node: int, value: Number) -> None:
        """#I_LIMIT_J <node> <value>: set current limit."""
        self._send_node_value("#I_LIMIT_J", node, value)

    # 4. Motion queue commands

    def enqueue_joint_motion(
        self,
        j1: Number,
        j2: Number,
        j3: Number,
        j4: Number,
        j5: Number,
        j6: Number,
        speed: Optional[Number] = None,
    ) -> None:
        """>j1,j2,j3,j4,j5,j6,speed: enqueue joint motion.

        The final speed field is optional according to the controller document.
        """
        values = [j1, j2, j3, j4, j5, j6]
        if speed is not None:
            values.append(speed)
        self._ensure_robot_enabled()
        self.send_command(">" + self._csv(values))

    def enqueue_cartesian_motion(
        self,
        x: Number,
        y: Number,
        z: Number,
        a: Number,
        b: Number,
        c: Number,
        speed: Optional[Number] = None,
    ) -> None:
        """@x,y,z,a,b,c,speed: enqueue Cartesian motion.

        The final speed field is optional according to the controller document.
        """
        values = [x, y, z, a, b, c]
        if speed is not None:
            values.append(speed)
        self._ensure_robot_enabled()
        self.send_command("@" + self._csv(values))

    def _send_node_value(self, command: str, node: int, value: Number) -> None:
        self._require_node(node)
        self._ensure_robot_enabled()
        self.send_command(f"{command} {node} {self._fmt_number(value)}")

    def _ensure_robot_enabled(self) -> None:
        if not self._robot_enabled:
            self.start()

    def _ensure_gripper_enabled(self) -> None:
        self._ensure_robot_enabled()
        if not self._gripper_enabled:
            self.hand_enable()

    @staticmethod
    def _require_node(node: int) -> None:
        if not isinstance(node, int) or node < 1:
            raise ValueError("node 必须是大于等于 1 的整数")

    @staticmethod
    def _require_range(name: str, value: Number, minimum: Number, maximum: Number) -> None:
        if value < minimum or value > maximum:
            raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")

    @classmethod
    def _csv(cls, values: Sequence[Number]) -> str:
        return ",".join(cls._fmt_number(value) for value in values)

    @staticmethod
    def _fmt_number(value: Number) -> str:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("数值参数必须是 int 或 float")
        return f"{value:g}"
