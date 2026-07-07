"""Shared prescription collection-count state."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict


STATUS_FILE = Path(__file__).resolve().parent / "collection_status.json"
LATEST_IMAGE = Path(__file__).resolve().parent / "collection_latest.jpg"


def write_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    temporary = STATUS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, STATUS_FILE)
    return payload


def start_collection(expected_count: int) -> Dict[str, Any]:
    if expected_count < 1:
        raise ValueError("expected_count 必须大于等于 1")
    return write_status(
        {
            "task_id": uuid.uuid4().hex,
            "expected_count": int(expected_count),
            "detected_count": 0,
            "stable": False,
            "complete": False,
            "active": True,
            "updated_at": time.time(),
        }
    )


def update_detected_count(detected_count: int, stable: bool) -> Dict[str, Any]:
    status = read_status()
    expected_count = int(status.get("expected_count", 0))
    active = bool(status.get("active", False))
    status.update(
        {
            "detected_count": int(detected_count),
            "stable": bool(stable),
            "complete": bool(active and stable and detected_count == expected_count),
            "updated_at": time.time(),
        }
    )
    return write_status(status)


def read_status() -> Dict[str, Any]:
    if not STATUS_FILE.exists():
        return {
            "task_id": None,
            "expected_count": 0,
            "detected_count": 0,
            "stable": False,
            "complete": False,
            "active": False,
            "updated_at": None,
        }
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        return {
            "task_id": None,
            "expected_count": 0,
            "detected_count": 0,
            "stable": False,
            "complete": False,
            "active": False,
            "updated_at": None,
        }


def clear_collection() -> Dict[str, Any]:
    return write_status(
        {
            "task_id": None,
            "expected_count": 0,
            "detected_count": 0,
            "stable": False,
            "complete": False,
            "active": False,
            "updated_at": time.time(),
        }
    )
