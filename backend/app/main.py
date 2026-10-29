from fastapi import APIRouter, FastAPI

from app.api import auth, procurements, profiles
from app.api.misc import organizations, results, score, tasks
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(
    title="Скоринг закупок",
    version="0.1.0",
    description="AI Procurement Copilot: оценка закупок ЕИС по параметрам поставщика.",
)
install_error_handlers(app)

api = APIRouter(prefix="/api")
for r in (auth.router, procurements.router, profiles.router, organizations, score, results, tasks):
    api.include_router(r)
app.include_router(api)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}
