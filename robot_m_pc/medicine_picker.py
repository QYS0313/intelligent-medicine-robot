"""High-level medicine picking workflow built on robot arm serial commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

from robot_arm_serial import Number, RobotArmSerial


JointPosition = Tuple[float, float, float, float, float, float]

PLACE_POSITION: JointPosition = (-5, 16, 102, 5, 36, -5)
HOME_POSITION: JointPosition = (0.0, -75.0, 180.0, 0.0, 0.0, 0.0)
PLACE_APPROACH_POSITION: JointPosition = (0.0, -44.0, 132.0, 0.0, 15.0, 0.0)
FRONT_OBSERVE_POSITION: JointPosition = (-3.0, -75.0, 98.0, 0.0, 86.0, 0.0)
BACK_OBSERVE_POSITION: JointPosition = (-3.0, -32.0, 105.0, 0.0, 87.0, 0.0)
FAST_SPEED = 50.0
PICK_SPEED = 25.0


@dataclass(frozen=True)
class MedicineSlot:
    index: int
    retreat_position: JointPosition
    grasp_position: JointPosition


MEDICINE_SLOTS = (
    MedicineSlot(1, (31.4, -11.1, 143.25, 45.9, -42.9, -30.9), (25.7, 14.5, 119.7, 43.0, -44.0, -31.0)),
    MedicineSlot(2, (-1.78, -22.8, 152.65, -2.6, -34.0, 0.0), (-1.78, 5.75, 125.1, -2.64, -33.8, 0.0)),
    MedicineSlot(3, (-36.86, -6.6, 147.1, -43.5, -55.4, 24.5), (-27.0, 14.0, 118.5, -41.2, -41.19, 28.9)),
    MedicineSlot(4, (34.8, -0.54, 152.75, 44.8, -55.6, -19.1), (25.4, 23.0, 126.2, 37.0, -51.45, -20.35)),
    MedicineSlot(5, (-1.87, -6.6, 167.0, -0.1, -62.7, -2.0), (-1.8, 19.62, 140.6, -1.0, -62.8, -2.1)),
    MedicineSlot(6, (-36.8, 3.2, 157.4, -37.0, -64.7, 10.44), (-26.5, 22.2, 130.3, -31.4, -55.74, 12.1)),
    # The Excel value is "132.829.8"; it is treated as "132.8, 29.8".
    MedicineSlot(7, (37, 30, 157, 39, -85, 7), (25.6, 38.5, 132.8, 29.8, -71.7, -5.76)),
    MedicineSlot(8, (1.34, 14.24, 179.8, 4.32, -93.5, -4.64), (0.74, 33.7, 143.0, 4.3, -76.2, -4.2)),
    MedicineSlot(9, (-40.12, 24.51, 160.1, -38.9, -83.94, -3.25), (-24.9, 41.2, 135.8, -21.4, -78.5, -1.8)),
    MedicineSlot(10, (24.1, 15.05, 95.86, -0.7, 63.8, 25.3), (21.67, 23.5, 120.1, 2.3, 35.0, 20.2)),
    MedicineSlot(11, (-0.5, 14.01, 91.6, 0.12, 74.62, -0.73), (-2.1, 14.2, 134.1, -0.9, 26.5, -2.5)),
    MedicineSlot(12, (-23.56, 21.3, 83.6, -1.9, 74.6, -21.95), (-26.5, 23.44, 121.06, 1.3, 32.75, -26.64)),
)


def normalize_joint_position(position: Sequence[Number]) -> JointPosition:
    if len(position) != 6:
        raise ValueError("坐标必须包含 6 个关节角")
    return tuple(float(value) for value in position)  # type: ignore[return-value]


def move_and_wait(
    arm: RobotArmSerial,
    position: Sequence[Number],
    speed: Number,
    tolerance: float = 2.0,
    timeout: float = 30.0,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    target = normalize_joint_position(position)
    if log:
        log(f"运动到 {target}，速度 {float(speed):g}")
    arm.enqueue_joint_motion(*target, speed=speed)
    if log:
        log(f"等待到位 {target}")
    reached = arm.wait_until_joint_position(target, tolerance=tolerance, timeout=timeout)
    if log:
        log(f"已到位 {tuple(round(value, 2) for value in reached)}")


def pick_medicine(
    arm: RobotArmSerial,
    retreat_position: Sequence[Number],
    grasp_position: Sequence[Number],
    tolerance: float = 2.0,
    timeout: float = 30.0,
    log: Optional[Callable[[str], None]] = None,
    use_place_approach: bool = True,
    completion_position: Sequence[Number] = HOME_POSITION,
) -> None:
    """Pick one medicine using fixed retreat/grasp positions.

    Flow:
    open gripper -> fast to retreat -> slow to grasp -> close gripper ->
    slow back to retreat -> fast to place approach -> fast to place ->
    open -> close -> fast to the requested completion position.
    """
    retreat = normalize_joint_position(retreat_position)
    grasp = normalize_joint_position(grasp_position)
    completion = normalize_joint_position(completion_position)

    if log:
        log("打开夹爪")
    arm.hand_open_current()
    move_and_wait(arm, retreat, FAST_SPEED, tolerance=tolerance, timeout=timeout, log=log)
    move_and_wait(arm, grasp, PICK_SPEED, tolerance=tolerance, timeout=timeout, log=log)
    if log:
        log("闭合夹爪")
    arm.hand_close_current()
    move_and_wait(arm, retreat, PICK_SPEED, tolerance=tolerance, timeout=timeout, log=log)
    if use_place_approach:
        move_and_wait(arm, PLACE_APPROACH_POSITION, FAST_SPEED, tolerance=tolerance, timeout=timeout, log=log)
    move_and_wait(arm, PLACE_POSITION, FAST_SPEED, tolerance=tolerance, timeout=timeout, log=log)
    if log:
        log("放药：打开夹爪")
    arm.hand_open_current()
    if log:
        log("放药后闭合夹爪")
    arm.hand_close_current()
    move_and_wait(arm, completion, FAST_SPEED, tolerance=tolerance, timeout=timeout, log=log)


def pick_medicine_by_slot(
    arm: RobotArmSerial,
    slot_index: int,
    tolerance: float = 2.0,
    timeout: float = 30.0,
    log: Optional[Callable[[str], None]] = None,
    completion_position: Sequence[Number] = HOME_POSITION,
) -> None:
    slot = get_slot(slot_index)
    use_place_approach = slot.index not in (10, 11, 12)
    if log:
        log(f"使用 {slot.index} 号药仓：回退点 {slot.retreat_position}，抓取点 {slot.grasp_position}")
        if not use_place_approach:
            log("10-12 号药仓跳过放置前避障点")
    pick_medicine(
        arm,
        slot.retreat_position,
        slot.grasp_position,
        tolerance=tolerance,
        timeout=timeout,
        log=log,
        use_place_approach=use_place_approach,
        completion_position=completion_position,
    )


def get_observe_position(slot_index: int) -> JointPosition:
    get_slot(slot_index)
    if slot_index <= 9:
        return FRONT_OBSERVE_POSITION
    return BACK_OBSERVE_POSITION


def get_slot(slot_index: int) -> MedicineSlot:
    for slot in MEDICINE_SLOTS:
        if slot.index == slot_index:
            return slot
    raise ValueError(f"未知药仓编号：{slot_index}")
