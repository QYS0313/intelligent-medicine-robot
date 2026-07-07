"""Shared robot task status for the dashboard and HTTP service."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


STATUS_FILE = Path(__file__).resolve().parent / "robot_task_status.json"


def update_task_status(
    phase: str,
    message: str,
    current_slot: Optional[int] = None,
    current_index: int = 0,
    total: int = 0,
    error: Optional[str] = None,
    slot_indices: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    previous = read_task_status()
    payload = {
        "phase": phase,
        "message": message,
        "current_slot": current_slot,
        "current_index": current_index,
        "total": total,
        "error": error,
        "slot_indices": (
            [int(value) for value in slot_indices]
            if slot_indices is not None
            else previous.get("slot_indices", [])
        ),
        "started_at": previous.get("started_at"),
        "updated_at": time.time(),
    }
    if phase == "starting" or payload["started_at"] is None:
        payload["started_at"] = time.time()
    temporary = STATUS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, STATUS_FILE)
    return payload


def read_task_status() -> Dict[str, Any]:
    if not STATUS_FILE.exists():
        return {
            "phase": "idle",
            "message": "等待任务",
            "current_slot": None,
            "current_index": 0,
            "total": 0,
            "error": None,
            "slot_indices": [],
            "started_at": None,
            "updated_at": None,
        }
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        return {
            "phase": "unknown",
            "message": "任务状态文件不可读",
            "current_slot": None,
            "current_index": 0,
            "total": 0,
            "error": None,
            "slot_indices": [],
            "started_at": None,
            "updated_at": None,
        }


def reset_task_status() -> Dict[str, Any]:
    payload = {
        "phase": "idle",
        "message": "等待任务",
        "current_slot": None,
        "current_index": 0,
        "total": 0,
        "error": None,
        "slot_indices": [],
        "started_at": None,
        "updated_at": time.time(),
    }
    temporary = STATUS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, STATUS_FILE)
    return payload
