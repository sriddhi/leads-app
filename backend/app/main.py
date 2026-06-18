import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings

# Reject bodies larger than the max upload + a small envelope allowance, before the
# framework buffers them — protects against memory-exhaustion via oversized multipart
# fields (the file itself is also streamed-capped in storage.save_resume).
_MAX_BODY_BYTES = settings.MAX_UPLOAD_BYTES + 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: runs setup before serving and teardown on shutdown."""
    # Ensure the upload directory exists
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready at: %s", upload_dir.resolve())

    yield

    logger.info("Application shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Leads Management API",
        description=(
            "Backend API for collecting and managing attorney leads. "
            "Prospects submit their details via the public POST /api/v1/leads endpoint; "
            "authenticated attorneys can review and update lead status."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl is not None and cl.isdigit() and int(cl) > _MAX_BODY_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "Request body too large."},
            )
        return await call_next(request)

    # Ensure the upload directory exists (resumes are served via an AUTHENTICATED
    # endpoint — GET /api/v1/leads/{id}/resume — never as public static files, since
    # they are sensitive PII).
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    # Register API routes
    app.include_router(api_router)

    @app.get("/health", tags=["health"], summary="Health check")
    async def health_check() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
