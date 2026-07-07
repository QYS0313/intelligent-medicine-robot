from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    qwen_model: str = os.getenv("QWEN_MODEL", "qwen3.7-plus")
    qwen_base_url: str = os.getenv(
        "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    robot_base_url: str = os.getenv(
        "ROBOT_BASE_URL", "http://10.24.104.54:8000"
    ).rstrip("/")
    robot_pick_path: str = os.getenv("ROBOT_PICK_PATH", "/pick-batch")
    robot_disable_path: str = os.getenv("ROBOT_DISABLE_PATH", "/disable")
    robot_timeout_seconds: float = float(os.getenv("ROBOT_TIMEOUT_SECONDS", "240"))
    robot_visual_timeout_seconds: float = float(
        os.getenv("ROBOT_VISUAL_TIMEOUT_SECONDS", "5")
    )
    max_items_per_plan: int = int(os.getenv("MAX_ITEMS_PER_PLAN", "4"))
    plan_ttl_seconds: int = int(os.getenv("PLAN_TTL_SECONDS", "600"))


settings = Settings()
