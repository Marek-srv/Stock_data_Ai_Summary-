"""Local upstream-improvement review API."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_url: HttpUrl
    revision: str = Field(min_length=7, max_length=64)
    release: str | None = Field(default=None, max_length=100)
    license: str = Field(min_length=1, max_length=100)
    relevance: str = Field(min_length=3, max_length=1000)
    change_summary: str = Field(min_length=3, max_length=2000)
    compatibility: str = Field(min_length=3, max_length=1000)
    expected_benefit: str = Field(min_length=3, max_length=1000)
    source_links: list[HttpUrl] = Field(min_length=1, max_length=10)
    change_sha256: str = Field(min_length=64, max_length=64)


class MonitorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[Candidate] = Field(max_length=10)


class ConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    whitelist: list[HttpUrl] = Field(max_length=25)
    discovery_limit: int = Field(ge=1, le=10)


class TestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["isolated-contract", "isolated-regression"]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(min_length=64, max_length=64)
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=3, max_length=1000)


class IntegrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(min_length=64, max_length=64)


def routes(app):
    router = APIRouter(prefix="/api/v1/improvements")

    @router.get("")
    def recent(): return app.state.improvements.recent()

    @router.get("/config")
    def config(): return app.state.improvements.config()

    @router.put("/config")
    def configure(body: ConfigRequest):
        return app.state.improvements.configure([str(item) for item in body.whitelist], body.discovery_limit)

    @router.post("/monitor", status_code=201)
    def monitor(body: MonitorRequest):
        return app.state.improvements.monitor([{**item.model_dump(mode="json")} for item in body.candidates])

    @router.get("/{proposal_id}")
    def proposal(proposal_id: UUID): return app.state.improvements.get(str(proposal_id))

    @router.post("/{proposal_id}/assess")
    def assess(proposal_id: UUID): return app.state.improvements.assess(str(proposal_id))

    @router.post("/{proposal_id}/test")
    def test(proposal_id: UUID, body: TestRequest): return app.state.improvements.test(str(proposal_id), body.profile)

    @router.post("/{proposal_id}/decision")
    def decide(proposal_id: UUID, body: DecisionRequest):
        return app.state.improvements.decide(str(proposal_id), body.fingerprint, body.decision, body.reason)

    @router.post("/{proposal_id}/integrated")
    def integrated(proposal_id: UUID, body: IntegrationRequest):
        return app.state.improvements.mark_integrated(str(proposal_id), body.fingerprint)

    @router.get("/{proposal_id}/report", response_class=PlainTextResponse)
    def report(proposal_id: UUID): return app.state.improvements.read_report(str(proposal_id))

    app.include_router(router)
