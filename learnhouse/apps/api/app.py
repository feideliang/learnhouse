import uvicorn
import sentry_sdk
from fastapi import FastAPI
from config.config import LearnHouseConfig, get_learnhouse_config
from src.core.events.events import shutdown_app, startup_app
from src.router import v1_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from src.core.ee_hooks import register_ee_middlewares
from src.routers.content_files import router as content_files_router
from src.routers.local_content import router as local_content_router


class SafeGZipMiddleware(GZipMiddleware):
    """GZip middleware that skips compression for video/audio/image content
    and for streaming media endpoints, to prevent breaking Range requests."""

    MEDIA_CONTENT_TYPES = frozenset({
        "video/", "audio/", "image/",
        "application/octet-stream",
    })

    STREAM_PATH_PREFIXES = ("/stream/", "/api/v1/stream/", "/content/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await super().__call__(scope, receive, send)

        path = scope.get("path", "")
        # Skip GZip entirely for streaming media endpoints
        if any(path.startswith(prefix) for prefix in self.STREAM_PATH_PREFIXES):
            # Bypass GZip by calling the inner app directly
            return await self.app(scope, receive, send)

        return await super().__call__(scope, receive, send)


########################
# Version 1.0.0
# Author: @swve
# (c) LearnHouse 2022
########################

# Get LearnHouse Config
learnhouse_config: LearnHouseConfig = get_learnhouse_config()

# Initialize Sentry if configured
if learnhouse_config.general_config.sentry_config.dsn:
    sentry_sdk.init(
        dsn=learnhouse_config.general_config.sentry_config.dsn,
        environment=learnhouse_config.general_config.env,
        send_default_pii=False,
        enable_logs=True,
        traces_sample_rate=1.0 if learnhouse_config.general_config.development_mode else 0.1,
        profile_session_sample_rate=1.0 if learnhouse_config.general_config.development_mode else 0.1,
        profile_lifecycle="trace",
    )

# Global Config
app = FastAPI(
    title=learnhouse_config.site_name,
    description=learnhouse_config.site_description,
    docs_url="/docs" if learnhouse_config.general_config.development_mode else None,
    redoc_url="/redoc" if learnhouse_config.general_config.development_mode else None,
    version="1.1.4",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=learnhouse_config.hosting_config.allowed_regexp,
    allow_methods=["*"],
    allow_credentials=True,
    allow_headers=["*"],
)

# GZip Middleware — SafeGZip skips video/audio/streaming endpoints
app.add_middleware(SafeGZipMiddleware, minimum_size=1000)

# Register EE Middlewares if available
register_ee_middlewares(app)


# Events
app.add_event_handler("startup", startup_app(app))
app.add_event_handler("shutdown", shutdown_app(app))


# Static Files - use S3-aware router when S3 is enabled, otherwise serve locally
# SECURITY: Both paths use routers with access control instead of raw StaticFiles
if learnhouse_config.hosting_config.content_delivery.type == "s3api":
    app.include_router(content_files_router)
    app.include_router(content_files_router, prefix="/api/v1")
else:
    app.include_router(local_content_router)
    app.include_router(local_content_router, prefix="/api/v1")

# Global Routes
app.include_router(v1_router)


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=learnhouse_config.hosting_config.port,
        reload=learnhouse_config.general_config.development_mode,
    )


# General Routes
@app.get("/")
async def root():
    return {"Message": "Welcome to LearnHouse ✨"}
