"""Read-only local startup integration status API."""

from fastapi import APIRouter


def routes(app):
    router = APIRouter(prefix="/api/v1/startup")

    @router.get("")
    def status():
        return app.state.startup.status(inspect_service=False)

    app.include_router(router)
