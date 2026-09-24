"""Control-centre contracts: the specialist's decisions and the assistant proxy (docs/api.md §6)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SubjectKind = Literal["alert", "patient"]
SpecialistAction = Literal["accept", "decline", "clarify", "confirm", "postpone"]


class SpecialistDecisionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    origin: dt.date = Field(description="publication origin the demo runs on")
    run_id: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="simulation run the decision belongs to; a restart of the simulation starts a new run, and "
        "the control centre replays only the decisions of its current run",
    )
    sim_day: int = Field(ge=0, le=60, description="day of the simulation when the decision was taken (0 = origin)")
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=64, description="signal id or synthetic referral id")
    region_code: str | None = Field(default=None, max_length=4)
    org_code: str | None = Field(default=None, max_length=8)
    profile_code: str | None = Field(default=None, max_length=8)
    action: SpecialistAction = Field(
        description="alerts: accept | decline | clarify; admission requests: confirm | decline | postpone"
    )
    comment: str | None = Field(default=None, max_length=4000)
    actor: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="client-generated per submission; resending the same key returns the stored row with 200",
    )


class SpecialistDecision(SpecialistDecisionCreate):
    id: int
    created_at: dt.datetime
    api_key_label: str | None = Field(description="label of the API key that submitted the decision")


class AssistantStatus(BaseModel):
    configured: bool = Field(description="an external model is configured on the server")
    provider: str | None = Field(description="groq | openrouter | gemini | openai-compatible")
    model: str | None


class AssistantSubject(BaseModel):
    kind: SubjectKind
    id: str = Field(max_length=64)
    hospital: str = Field(max_length=300)


class AssistantRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    lang: Literal["ru", "kk"] = "ru"
    question: str = Field(min_length=1, max_length=2000)
    facts: list[str] = Field(default_factory=list, max_length=40)
    explanation: list[str] = Field(default_factory=list, max_length=12)
    subject: AssistantSubject


class AssistantReply(BaseModel):
    text: str
    provider: str
    model: str
