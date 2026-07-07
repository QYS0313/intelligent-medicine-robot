from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.medicines import MEDICINES


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)
    image_data_url: str | None = None

    @field_validator("image_data_url")
    @classmethod
    def validate_image(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.startswith(("data:image/jpeg;base64,", "data:image/png;base64,")):
            raise ValueError("仅支持 JPEG/PNG Data URL")
        if len(value) > 2_500_000:
            raise ValueError("图片过大，请降低分辨率后重试")
        return value


class PlanItem(BaseModel):
    slot_index: int = Field(ge=1, le=12)
    count: int = Field(default=1, ge=1)
    medicine_name: str


class CaptureResult(BaseModel):
    request_id: str | None = None
    slot_index: int = Field(ge=1, le=12)
    image_url: str | None = None
    detected: bool = False
    timed_out: bool = False
    created_at: float | None = None


class PendingPlan(BaseModel):
    plan_id: str
    session_id: str
    items: list[PlanItem]
    rationale: str
    created_at: float
    expires_at: float
    status: str = "pending"
    arm_state: str = "waiting"
    arm_detail: str | None = None
    report_status: str = "waiting"
    report: str | None = None
    captures: list[CaptureResult] = Field(default_factory=list)
    robot_log: list[str] = Field(default_factory=list)


class PickResult(BaseModel):
    slot_index: int
    medicine_name: str
    sequence: int
    ok: bool
    detail: str
    raw_detail: str | None = None


class ExecutionResponse(BaseModel):
    plan_id: str
    status: str
    results: list[PickResult]
    arm_state: str = "waiting"
    arm_detail: str | None = None
    report_status: str = "waiting"
    report: str | None = None
    captures: list[CaptureResult] = Field(default_factory=list)
    robot_log: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    pending_plan: PendingPlan | None = None
    execution: ExecutionResponse | None = None


class StatusResponse(BaseModel):
    model: str
    api_key_configured: bool
    robot_mode: str
    robot_base_url: str
    medicines: dict[int, str] = MEDICINES
