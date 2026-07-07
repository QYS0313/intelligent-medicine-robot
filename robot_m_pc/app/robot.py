from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import Settings
from app.medicines import medicine_name
from app.schemas import CaptureResult, PickResult


@dataclass
class BatchPickResult:
    ok: bool
    results: list[PickResult]
    captures: list[CaptureResult]
    logs: list[str]


class RobotClient:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def pick_batch(
        self,
        slot_indices: list[int],
        plan_id: str,
        session_id: str,
    ) -> BatchPickResult:
        url = f"{self.config.robot_base_url}/{self.config.robot_pick_path.lstrip('/')}"
        logger = logging.getLogger("robot")
        context = (
            f"session={session_id} plan={plan_id} slots={slot_indices} "
            f"url={url} disable_after=true"
        )
        logger.info("batch_pick_request | %s", context)
        try:
            async with httpx.AsyncClient(
                timeout=self.config.robot_timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(
                    url,
                    json={
                        "slot_indices": slot_indices,
                        "disable_after": True,
                        "visual_timeout": self.config.robot_visual_timeout_seconds,
                    },
                )
                response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise ValueError(
                    str(payload.get("error", "板卡返回了无效的批量结果"))
                    if isinstance(payload, dict)
                    else "板卡返回值不是 JSON 对象"
                )
            data = payload.get("data") or {}
            logs = [str(value) for value in data.get("logs", [])]
            captures: list[CaptureResult] = []
            for value in data.get("captures", []):
                if not isinstance(value, dict):
                    continue
                image_url = value.get("image_url")
                proxy_url = None
                if image_url:
                    filename = Path(str(image_url)).name
                    proxy_url = f"/api/robot/captures/{quote(filename)}"
                captures.append(
                    CaptureResult(
                        request_id=value.get("request_id"),
                        slot_index=int(value["slot_index"]),
                        image_url=proxy_url,
                        detected=bool(value.get("detected", False)),
                        timed_out=bool(value.get("timed_out", False)),
                        created_at=value.get("created_at"),
                    )
                )
            results = [
                PickResult(
                    slot_index=slot,
                    medicine_name=medicine_name(slot),
                    sequence=index,
                    ok=True,
                    detail="批量抓取执行成功",
                )
                for index, slot in enumerate(slot_indices, start=1)
            ]
            logger.info(
                "batch_pick_success | %s status=%s captures=%s logs=%s",
                context,
                response.status_code,
                len(captures),
                len(logs),
            )
            return BatchPickResult(True, results, captures, logs)
        except httpx.HTTPStatusError as exc:
            detail = (
                f"板卡批量接口返回 HTTP {exc.response.status_code}："
                f"{exc.response.text[:1000] or '无响应正文'}"
            )
        except httpx.TimeoutException as exc:
            detail = f"批量抓药超时（{self.config.robot_timeout_seconds} 秒）：{exc}"
        except httpx.ConnectError as exc:
            detail = f"无法连接板卡批量接口：{exc}"
        except (httpx.RequestError, OSError, ValueError, TypeError, KeyError) as exc:
            detail = f"批量抓药请求失败：{type(exc).__name__}: {exc}"
        logger.error("batch_pick_failed | %s detail=%s", context, detail)
        first_slot = slot_indices[0]
        return BatchPickResult(
            False,
            [
                PickResult(
                    slot_index=first_slot,
                    medicine_name=medicine_name(first_slot),
                    sequence=1,
                    ok=False,
                    detail=detail,
                )
            ],
            [],
            [],
        )

    async def fetch_capture(self, filename: str) -> tuple[bytes, str]:
        if not filename or Path(filename).name != filename:
            raise ValueError("无效的示意图文件名")
        url = f"{self.config.robot_base_url}/vision/captures/{quote(filename)}"
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(url)
            response.raise_for_status()
        return response.content, response.headers.get("content-type", "image/jpeg")

    async def pick(
        self,
        slot_index: int,
        sequence: int,
        plan_id: str,
        session_id: str,
    ) -> PickResult:
        name = medicine_name(slot_index)
        url = f"{self.config.robot_base_url}/{self.config.robot_pick_path.lstrip('/')}"
        logger = logging.getLogger("robot")
        context = (
            f"session={session_id} plan={plan_id} sequence={sequence} "
            f"slot={slot_index} medicine={name} url={url}"
        )
        logger.info("pick_request | %s", context)
        try:
            # 局域网板卡必须直连；禁止 HTTP_PROXY/HTTPS_PROXY 接管私网请求。
            async with httpx.AsyncClient(
                timeout=self.config.robot_timeout_seconds,
                trust_env=False,
            ) as client:
                # 抓取类 POST 不能自动重试，否则响应丢失时可能重复抓药。
                response = await client.post(url, json={"slot_index": slot_index})
                response.raise_for_status()
            raw_text = response.text
            raw_detail: str | None = None
            try:
                payload = response.json()
                raw_detail = json.dumps(payload, ensure_ascii=False, indent=2)[:20_000]
                logs = payload.get("data", {}).get("logs", []) if isinstance(payload, dict) else []
                if isinstance(payload, dict) and payload.get("ok") is False:
                    detail = str(payload.get("message") or payload.get("error") or "板卡报告执行失败")
                    logger.error("pick_board_error | %s detail=%s", context, detail)
                    return PickResult(
                        slot_index=slot_index,
                        medicine_name=name,
                        sequence=sequence,
                        ok=False,
                        detail=detail,
                        raw_detail=raw_detail,
                    )
                detail = f"板卡执行成功，共 {len(logs)} 条动作记录" if logs else "板卡执行成功"
            except (ValueError, TypeError, AttributeError):
                detail = raw_text[:160] or "板卡返回成功"
                raw_detail = raw_text[:20_000] if len(raw_text) > 160 else None
            logger.info(
                "pick_success | %s status=%s response=%r",
                context,
                response.status_code,
                detail,
            )
            return PickResult(
                slot_index=slot_index,
                medicine_name=name,
                sequence=sequence,
                ok=True,
                detail=detail,
                raw_detail=raw_detail,
            )
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000]
            diagnostic_headers = {
                name: value
                for name, value in exc.response.headers.items()
                if name.lower() in {"server", "via", "x-powered-by", "x-request-id"}
            }
            detail = (
                f"板卡返回 HTTP {exc.response.status_code}：{body or '无响应正文'}"
                f"；响应头={diagnostic_headers or '无诊断响应头'}"
            )
            logger.error(
                "pick_http_error | %s detail=%s headers=%r",
                context,
                detail,
                dict(exc.response.headers),
            )
            raw_detail = body or None
        except httpx.TimeoutException as exc:
            detail = f"请求板卡超时（{self.config.robot_timeout_seconds} 秒）：{exc}"
            logger.error("pick_timeout | %s detail=%s", context, detail)
            raw_detail = None
        except httpx.ConnectError as exc:
            detail = f"无法连接板卡，请检查 IP、端口、服务和网络：{exc}"
            logger.error("pick_connect_error | %s detail=%s", context, detail)
            raw_detail = None
        except httpx.RequestError as exc:
            detail = f"板卡网络请求失败：{type(exc).__name__}: {exc}"
            logger.exception("pick_request_error | %s", context)
            raw_detail = None
        except OSError as exc:
            detail = f"本地网络错误：{type(exc).__name__}: {exc}"
            logger.exception("pick_os_error | %s", context)
            raw_detail = None

        return PickResult(
            slot_index=slot_index,
            medicine_name=name,
            sequence=sequence,
            ok=False,
            detail=detail,
            raw_detail=raw_detail,
        )

    async def disable(self, plan_id: str, session_id: str) -> tuple[bool, str]:
        """整单结束后释放机械臂使能；无论抓取成功或失败都应调用。"""
        url = f"{self.config.robot_base_url}/{self.config.robot_disable_path.lstrip('/')}"
        logger = logging.getLogger("robot")
        context = f"session={session_id} plan={plan_id} url={url}"
        logger.info("disable_request | %s", context)
        try:
            async with httpx.AsyncClient(
                timeout=self.config.robot_timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(url, json={})
                response.raise_for_status()
            detail = response.text[:1000] or "机械臂已释放使能"
            logger.info(
                "disable_success | %s status=%s response=%r",
                context,
                response.status_code,
                detail,
            )
            return True, detail
        except httpx.HTTPStatusError as exc:
            detail = (
                f"释放使能接口返回 HTTP {exc.response.status_code}："
                f"{exc.response.text[:1000] or '无响应正文'}"
            )
        except httpx.TimeoutException as exc:
            detail = f"释放使能请求超时：{exc}"
        except httpx.ConnectError as exc:
            detail = f"释放使能时无法连接板卡：{exc}"
        except (httpx.RequestError, OSError) as exc:
            detail = f"释放使能请求失败：{type(exc).__name__}: {exc}"
        logger.error("disable_failed | %s detail=%s", context, detail)
        return False, detail
