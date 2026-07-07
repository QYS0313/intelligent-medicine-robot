from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.ai import ConsultationAI
from app.config import settings
from app.logging_config import configure_logging
from app.robot import RobotClient
from app.schemas import (
    ExecutionResponse,
    ChatRequest,
    ChatResponse,
    StatusResponse,
)
from app.store import MemoryStore

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
LOG_PATH = configure_logging()
logger = logging.getLogger("app")

app = FastAPI(title="岐黄智取 · 远程问诊抓药端", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

store = MemoryStore()
ai = ConsultationAI(settings, store)
robot = RobotClient(settings)
background_tasks: set[asyncio.Task] = set()


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    return StatusResponse(
        model=settings.qwen_model,
        api_key_configured=bool(settings.dashscope_api_key),
        robot_mode="real-auto",
        robot_base_url=settings.robot_base_url,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session = await store.session(request.session_id)
    async with session.lock:
        try:
            reply, plan = await ai.chat(
                request.session_id, session, request.message, request.image_data_url
            )
            execution = None
            if plan:
                # 先把方案返回页面，再在后台驱动机械臂，避免界面等待整个动作结束。
                plan.status = "executing"
                execution = ExecutionResponse(
                    plan_id=plan.plan_id,
                    status=plan.status,
                    results=[],
                    arm_state="working",
                    report_status="waiting",
                )
                plan.arm_state = "working"
                task = asyncio.create_task(execute_plan(plan))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
            return ChatResponse(
                reply=reply,
                pending_plan=plan,
                execution=execution,
            )
        except RuntimeError as exc:
            logger.error("chat_config_error | session=%s error=%s", request.session_id, exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("chat_error | session=%s", request.session_id)
            raise HTTPException(status_code=502, detail=f"模型调用失败：{exc}") from exc


@app.get("/api/sessions/{session_id}/pending")
async def pending(session_id: str):
    return await store.current_plan(session_id)


@app.get("/api/plans/{plan_id}/status", response_model=ExecutionResponse)
async def execution_status(plan_id: str) -> ExecutionResponse:
    execution = await store.execution(plan_id)
    if not execution:
        raise HTTPException(status_code=404, detail="方案不存在")
    return execution


@app.get("/api/robot/captures/{filename}")
async def robot_capture(filename: str) -> Response:
    try:
        body, content_type = await robot.fetch_capture(filename)
        return Response(
            content=body,
            media_type=content_type,
            headers={"Cache-Control": "no-store"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("capture_proxy_failed | filename=%s error=%s", filename, exc)
        raise HTTPException(status_code=502, detail=f"读取板卡示意图失败：{exc}") from exc


async def execute_plan(plan) -> ExecutionResponse:
    """比赛演示：一次提交整组药仓，并在板端完成连续抓取与失能。"""
    plan.status = "executing"
    plan.arm_state = "working"
    slot_indices = [item.slot_index for item in plan.items]
    logger.info(
        "plan_start | session=%s plan=%s items=%s",
        plan.session_id,
        plan.plan_id,
        [(item.slot_index, item.medicine_name, item.count) for item in plan.items],
    )
    batch = await robot.pick_batch(slot_indices, plan.plan_id, plan.session_id)
    results = batch.results
    plan.captures = batch.captures
    plan.robot_log = batch.logs
    for result in results:
        await store.append_result(plan.plan_id, result)

    if batch.ok:
        plan.status = "completed"
        plan.arm_state = "disabled"
        plan.arm_detail = "批量任务已完成，板端已执行释放使能"
        logger.info(
            "plan_completed | session=%s plan=%s picks=%s captures=%s arm_state=disabled",
            plan.session_id,
            plan.plan_id,
            len(results),
            len(plan.captures),
        )
    else:
        plan.status = "failed"
        logger.error(
            "plan_failed | session=%s plan=%s detail=%s",
            plan.session_id,
            plan.plan_id,
            results[0].detail if results else "批量接口失败",
        )
        disabled, disable_detail = await robot.disable(plan.plan_id, plan.session_id)
        plan.arm_state = "disabled" if disabled else "disable_failed"
        plan.arm_detail = disable_detail

    plan.report_status = "generating"
    try:
        try:
            plan.report = await asyncio.wait_for(
                ai.generate_report(plan, results), timeout=15
            )
        except TimeoutError:
            logger.warning(
                "report_timeout_retry | session=%s plan=%s",
                plan.session_id,
                plan.plan_id,
            )
            plan.report = await asyncio.wait_for(
                ai.generate_report(plan, results, compact=True), timeout=10
            )
        plan.report_status = "completed"
        logger.info(
            "report_completed | session=%s plan=%s",
            plan.session_id,
            plan.plan_id,
        )
    except Exception as exc:
        logger.exception(
            "report_generation_failed | session=%s plan=%s",
            plan.session_id,
            plan.plan_id,
        )
        plan.report = "抓药已完成。\n\n" + await ai.build_local_report(plan, results)
        plan.report_status = "completed"
        logger.warning(
            "report_fallback_used | session=%s plan=%s error=%s",
            plan.session_id,
            plan.plan_id,
            exc,
        )

    return ExecutionResponse(
        plan_id=plan.plan_id,
        status=plan.status,
        results=results,
        arm_state=plan.arm_state,
        arm_detail=plan.arm_detail,
        report_status=plan.report_status,
        report=plan.report,
        captures=plan.captures,
        robot_log=plan.robot_log,
    )
