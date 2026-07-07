"""Shared selected-slot state for the HTTP service and vision process."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


SELECTION_FILE = Path(__file__).resolve().parent / "vision_selection.json"
CAPTURE_RESULT_FILE = Path(__file__).resolve().parent / "vision_capture_result.json"
CAPTURE_DIRECTORY = Path(__file__).resolve().parent / "vision_captures"
VISION_LATEST_IMAGE = Path(__file__).resolve().parent / "vision_latest.jpg"


def normalize_slots(slot_indices: Sequence[int]) -> List[int]:
    slots = sorted(set(int(value) for value in slot_indices))
    if any(value < 1 or value > 12 for value in slots):
        raise ValueError("slot_indices 中的药仓编号必须在 1 到 12 之间")
    return slots


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def write_selected_slots(
    slot_indices: Sequence[int],
    capture_request_id: Optional[str] = None,
) -> List[int]:
    slots = normalize_slots(slot_indices)
    atomic_write_json(
        SELECTION_FILE,
        {
            "slot_indices": slots,
            "capture_request_id": capture_request_id,
            "updated_at": time.time(),
        },
    )
    return slots


def read_selection_state() -> Dict[str, Any]:
    if not SELECTION_FILE.exists():
        return {"slot_indices": [], "capture_request_id": None}
    try:
        payload = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
        return {
            "slot_indices": normalize_slots(payload.get("slot_indices", [])),
            "capture_request_id": payload.get("capture_request_id"),
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"slot_indices": [], "capture_request_id": None}


def read_selected_slots() -> List[int]:
    return read_selection_state()["slot_indices"]


def create_capture_request(slot_index: int) -> str:
    normalize_slots([slot_index])
    request_id = uuid.uuid4().hex
    write_selected_slots([slot_index], capture_request_id=request_id)
    return request_id


def write_capture_result(
    request_id: str,
    slot_index: int,
    image_path: str,
    detected: bool,
) -> None:
    atomic_write_json(
        CAPTURE_RESULT_FILE,
        {
            "request_id": request_id,
            "slot_index": slot_index,
            "image_path": image_path,
            "detected": detected,
            "created_at": time.time(),
        },
    )


def read_capture_result(request_id: str) -> Optional[Dict[str, Any]]:
    if not CAPTURE_RESULT_FILE.exists():
        return None
    try:
        payload = json.loads(CAPTURE_RESULT_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        return None
    if payload.get("request_id") != request_id:
        return None
    return payload


def clear_capture_images() -> None:
    if CAPTURE_DIRECTORY.exists():
        for path in CAPTURE_DIRECTORY.glob("*.jpg"):
            try:
                path.unlink()
            except OSError:
                pass
    try:
        CAPTURE_RESULT_FILE.unlink()
    except FileNotFoundError:
        pass
