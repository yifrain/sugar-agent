"""FastAPI application entry point for Sugar Agent.

Provides:
- WeChat webhook endpoint for receiving messages
- Admin API for managing memories, prompts, blood sugar data
- Static file serving for the admin web UI
- Health check endpoint
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from sugar_agent.config import load_config, PROJECT_ROOT, DATA_DIR
from sugar_agent.db.models import create_tables, init_db

# Global state accessible via app.state
config = load_config()

# Add prompts_dir to config for easy access
config.prompts_dir = PROJECT_ROOT / "src" / "sugar_agent" / "prompts"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # === Startup ===
    logger.info(f"Starting {config.app.name} v0.1.0 in {config.app.env} mode")

    # Set up data directories
    memories_dir = DATA_DIR / "memories"
    logs_dir = DATA_DIR / "logs"
    memories_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Configure loguru
    logger.remove()
    logger.add(
        sys.stdout,
        level=config.app.log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    )
    logger.add(
        logs_dir / "sugar-agent_{time:YYYY-MM-DD}.log",
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    )

    # Initialize database
    db_path = DATA_DIR / "sugar-agent.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    engine = init_db(db_url)
    await create_tables(engine)
    logger.info("Database initialized")

    # Create async session factory
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Store engine and config on app state
    app.state.engine = engine
    app.state.config = config
    app.state.session_factory = session_factory

    # Initialize WeChat bridge
    bridge = _create_bridge(config)
    app.state.bridge = bridge
    if bridge:
        await bridge.start()
        logger.info(f"WeChat bridge initialized: {type(bridge).__name__}")

    # Initialize Memory store
    from sugar_agent.memory.store import MemoryStore

    memory_store = MemoryStore(
        storage_dir=str(memories_dir),
        db_session_factory=session_factory,
    )
    app.state.memory_store = memory_store
    logger.info("Memory store initialized")

    # Initialize Weather service
    from sugar_agent.weather.service import WeatherService

    weather_service = None
    if config.weather.api_key:
        weather_service = WeatherService(
            provider=config.weather.provider,
            api_key=config.weather.api_key,
            location=config.weather.location or "北京",
        )
        logger.info(f"Weather service initialized: {config.weather.provider}")
    else:
        logger.warning("No weather API key configured, weather features disabled")
    app.state.weather_service = weather_service

    # Initialize LLM client
    from sugar_agent.llm.client import LLMClient

    llm_client = LLMClient(
        primary_model=config.llm.model,
        fallback_model=config.llm.fallback.model,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
        timeout=config.llm.timeout,
    )
    app.state.llm_client = llm_client
    logger.info(f"LLM client initialized: {config.llm.model}")

    # Initialize Agent
    from sugar_agent.agent import Agent

    agent = Agent(
        config=config,
        llm_client=llm_client,
        bridge=bridge,
        memory_store=memory_store,
        weather_service=weather_service,
        db_session_factory=session_factory,
    )
    app.state.agent = agent
    logger.info("Agent initialized")

    # Initialize Scheduler
    from sugar_agent.scheduler.tasks import TaskScheduler

    scheduler = TaskScheduler(
        config=config.schedule,
        agent=agent,
        bridge=bridge,
        weather_service=weather_service,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Scheduler initialized")

    logger.info("✅ Sugar Agent is ready!")

    yield  # App runs here

    # === Shutdown ===
    logger.info("Shutting down...")
    if app.state.scheduler:
        app.state.scheduler.stop()
    if app.state.bridge:
        await app.state.bridge.stop()
    if app.state.weather_service:
        await app.state.weather_service.close()
    if app.state.engine:
        await app.state.engine.dispose()
    logger.info("Sugar Agent stopped.")


def _create_bridge(config):
    """Create the appropriate WeChat bridge based on configuration."""
    bridge_type = config.wechat_bridge.type

    # 企业微信"客户联系"模式（推荐：零封禁 + 无限制主动推送）
    if bridge_type == "wecom" and config.wecom.enabled:
        from sugar_agent.wechat.wecom_bridge import WeComBridge
        return WeComBridge(
            corp_id=config.wecom.corp_id,
            agent_id=config.wecom.agent_id,
            secret=config.wecom.secret,
            token=config.wecom.token,
            encoding_aes_key=config.wecom.encoding_aes_key,
            service_userid=config.wecom.service_userid,
        )

    # Mock 模式（开发调试）
    if bridge_type == "mock":
        from sugar_agent.wechat.mock_bridge import MockWeChatBridge
        return MockWeChatBridge(
            target_user_id=config.wechat_bridge.target_user_id,
            target_user_name=config.wechat_bridge.target_user_name,
        )

    # HTTP 桥接模式
    if bridge_type == "http":
        from sugar_agent.wechat.http_bridge import HttpBridgeConfig, HttpWeChatBridge
        bridge_config = HttpBridgeConfig(
            base_url=config.wechat_bridge.base_url,
            api_key=config.wechat_bridge.api_key,
        )
        return HttpWeChatBridge(bridge_config)

    # 默认：开发环境用 mock
    logger.warning(f"Unknown bridge type '{bridge_type}' or not configured, using mock bridge")
    from sugar_agent.wechat.mock_bridge import MockWeChatBridge
    return MockWeChatBridge()

        return MockWeChatBridge()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Sugar Agent",
        description="WeChat-based AI personal assistant for health and companionship",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for admin UI
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check
    @app.get("/api/v1/health")
    async def health_check():
        """Health check endpoint."""
        bridge_status = None
        if app.state.bridge:
            try:
                bridge_status = await app.state.bridge.get_bridge_status()
            except Exception:
                bridge_status = {"connected": False}

        return {
            "status": "ok",
            "version": "0.1.0",
            "env": config.app.env,
            "bridge": bridge_status,
        }

    # Mount static files for admin UI at /admin/
    static_dir = PROJECT_ROOT / "static"
    app.mount("/admin", StaticFiles(directory=str(static_dir), html=True), name="admin")

    # Import and register API routes
    from sugar_agent.api.webhook import router as webhook_router
    from sugar_agent.api.admin import router as admin_router
    from sugar_agent.api.wecom import router as wecom_router

    app.include_router(webhook_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(wecom_router, prefix="/api/v1")

    return app


# Create the app instance
app = create_app()


def main():
    """Entry point for running the server directly."""
    import uvicorn

    uvicorn.run(
        "sugar_agent.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.app.env == "development",
        log_level=config.app.log_level.lower(),
    )


if __name__ == "__main__":
    main()
