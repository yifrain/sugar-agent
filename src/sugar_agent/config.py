"""Configuration system for Sugar Agent.

Loads YAML config files and overlays environment variables.
Priority: env vars > production.yaml > default.yaml
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env file first so os.environ picks it up
load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"


class AppConfig(BaseModel):
    name: str = "sugar-agent"
    env: str = "development"
    log_level: str = "DEBUG"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    webhook_path: str = "/api/v1/webhook/message"


class WeChatBridgeConfig(BaseModel):
    type: str = "mock"  # http | mock
    base_url: str = "http://localhost:9001"
    api_key: str = ""
    target_user_id: str = "test_user_001"
    target_user_name: str = "宝宝"
    poll_interval: int = 3
    webhook: dict = Field(default_factory=lambda: {"secret_token": ""})


class LlmFallbackConfig(BaseModel):
    provider: str = "qwen"
    model: str = "qwen/qwen-turbo"
    temperature: float = 0.8
    max_tokens: int = 1024


class LlmConfig(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek/deepseek-chat"
    temperature: float = 0.8
    max_tokens: int = 1024
    timeout: int = 30
    fallback: LlmFallbackConfig = Field(default_factory=LlmFallbackConfig)
    tool_choice: str = "auto"


class WeatherConfig(BaseModel):
    provider: str = "seniverse"
    api_key: str = ""
    location: str = "北京"
    location_id: str = ""
    units: str = "metric"


class MemoryConfig(BaseModel):
    backend: str = "file"
    dir: str = "data/memories"
    max_context_memories: int = 10
    auto_extract: bool = True


class HealthConfig(BaseModel):
    bg_unit: str = "mmol/L"
    low_threshold: float = 3.9
    high_threshold: float = 10.0
    urgent_low: float = 3.0
    urgent_high: float = 16.0
    target_low: float = 3.9
    target_high: float = 7.0


class ScheduleTaskConfig(BaseModel):
    enabled: bool = True
    cron_hour: int = 7
    cron_minute: int = 30
    cron_day: Optional[int] = None


class ScheduleTasksConfig(BaseModel):
    weather_reminder: ScheduleTaskConfig = Field(default_factory=ScheduleTaskConfig)
    afternoon_checkin: ScheduleTaskConfig = Field(
        default_factory=lambda: ScheduleTaskConfig(cron_hour=15, cron_minute=0)
    )
    evening_summary: ScheduleTaskConfig = Field(
        default_factory=lambda: ScheduleTaskConfig(cron_hour=21, cron_minute=0)
    )
    weekly_health: ScheduleTaskConfig = Field(
        default_factory=lambda: ScheduleTaskConfig(cron_day=0, cron_hour=10, cron_minute=0)
    )


class ScheduleConfig(BaseModel):
    timezone: str = "Asia/Shanghai"
    tasks: ScheduleTasksConfig = Field(default_factory=ScheduleTasksConfig)


class AdminConfig(BaseModel):
    username: str = "admin"
    password: str = ""
    enabled: bool = True


class Config(BaseModel):
    model_config = {"extra": "allow"}  # Allow dynamic attributes like prompts_dir

    app: AppConfig = Field(default_factory=AppConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    wechat_bridge: WeChatBridgeConfig = Field(default_factory=WeChatBridgeConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(config_dict: dict, prefix: str = "SUGAR__") -> dict:
    """Apply environment variable overrides using the SUGAR__SECTION__KEY pattern."""
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        # SUGAR__LLM__TEMPERATURE -> ["llm", "temperature"]
        parts = env_key[len(prefix):].lower().split("__")
        if len(parts) < 2:
            continue

        # Navigate to the right nested dict
        current = config_dict
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Try to cast the value
        last_key = parts[-1]
        try:
            if env_val.lower() in ("true", "false"):
                current[last_key] = env_val.lower() == "true"
            elif "." in env_val:
                current[last_key] = float(env_val)
            else:
                current[last_key] = int(env_val)
        except ValueError:
            current[last_key] = env_val

    return config_dict


def load_config() -> Config:
    """Load configuration from YAML files and environment variables.

    Priority (lowest to highest):
    1. config/default.yaml
    2. config/production.yaml (if SUGAR_ENV=production)
    3. Environment variables (SUGAR__SECTION__KEY pattern)
    4. Direct env vars for secrets (DEEPSEEK_API_KEY, etc.)
    """
    # Load default config
    with open(CONFIG_DIR / "default.yaml", "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    # Overlay production config if in production mode
    env = os.environ.get("SUGAR_ENV", config_dict.get("app", {}).get("env", "development"))
    if env == "production":
        prod_path = CONFIG_DIR / "production.yaml"
        if prod_path.exists():
            with open(prod_path, "r", encoding="utf-8") as f:
                prod_dict = yaml.safe_load(f)
            config_dict = _deep_merge(config_dict, prod_dict)

    # Apply environment variable overrides (SUGAR__ pattern)
    config_dict = _apply_env_overrides(config_dict)

    # Map direct environment variables to config
    _map_secret_env_vars(config_dict)

    return Config(**config_dict)


def _map_secret_env_vars(config_dict: dict) -> None:
    """Map well-known environment variables to config keys."""
    secret_mappings = {
        "DEEPSEEK_API_KEY": ("llm", "api_key_deepseek"),
        "DASHSCOPE_API_KEY": ("llm", "api_key_qwen"),
        "ANTHROPIC_API_KEY": ("llm", "api_key_anthropic"),
        "SENIVERSE_API_KEY": ("weather", "api_key"),
        "OPENWEATHER_API_KEY": ("weather", "api_key"),
        "BRIDGE_BASE_URL": ("wechat_bridge", "base_url"),
        "BRIDGE_API_KEY": ("wechat_bridge", "api_key"),
        "WEBHOOK_SECRET_TOKEN": ("wechat_bridge", "webhook", "secret_token"),
        "ADMIN_PASSWORD": ("admin", "password"),
    }
    for env_key, config_path in secret_mappings.items():
        if env_key in os.environ:
            # Navigate nested dict
            current = config_dict
            for part in config_path[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[config_path[-1]] = os.environ[env_key]
