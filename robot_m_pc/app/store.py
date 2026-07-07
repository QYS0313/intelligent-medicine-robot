from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.schemas import ExecutionResponse, PendingPlan, PickResult


@dataclass
class Session:
    conversation: list[dict] = field(default_factory=list)
    pending_plan_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MemoryStore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.plans: dict[str, PendingPlan] = {}
        self.results: dict[str, list[PickResult]] = {}
        self._lock = asyncio.Lock()

    async def session(self, session_id: str) -> Session:
        async with self._lock:
            return self.sessions.setdefault(session_id, Session())

    async def put_plan(self, plan: PendingPlan) -> None:
        async with self._lock:
            self.plans[plan.plan_id] = plan
            self.results[plan.plan_id] = []
            self.sessions.setdefault(plan.session_id, Session()).pending_plan_id = plan.plan_id

    async def get_plan(self, plan_id: str) -> PendingPlan | None:
        async with self._lock:
            plan = self.plans.get(plan_id)
            if plan and plan.status == "pending" and plan.expires_at <= time.time():
                plan.status = "expired"
            return plan

    async def append_result(self, plan_id: str, result: PickResult) -> None:
        async with self._lock:
            self.results.setdefault(plan_id, []).append(result)

    async def execution(self, plan_id: str) -> ExecutionResponse | None:
        async with self._lock:
            plan = self.plans.get(plan_id)
            if not plan:
                return None
            return ExecutionResponse(
                plan_id=plan_id,
                status=plan.status,
                results=list(self.results.get(plan_id, [])),
                arm_state=plan.arm_state,
                arm_detail=plan.arm_detail,
                report_status=plan.report_status,
                report=plan.report,
                captures=plan.captures,
                robot_log=plan.robot_log,
            )

    async def current_plan(self, session_id: str) -> PendingPlan | None:
        session = await self.session(session_id)
        if not session.pending_plan_id:
            return None
        plan = await self.get_plan(session.pending_plan_id)
        return plan if plan and plan.status == "pending" else None
