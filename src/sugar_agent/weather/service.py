"""Weather service for fetching forecasts.

Supports multiple providers:
- Seniverse (心知天气) - recommended for China
- OpenWeatherMap
"""

from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger


@dataclass
class WeatherForecast:
    """Structured weather forecast data."""

    date: str
    location: str
    temperature_high: float
    temperature_low: float
    condition: str  # e.g. "晴", "多云", "雨"
    humidity: int
    wind_speed: float
    wind_direction: str = ""
    rain_probability: int = 0  # 0-100
    suggestion: Optional[str] = None  # e.g. "适合户外活动"


class WeatherService:
    """Weather API client with multiple provider support."""

    def __init__(self, provider: str = "seniverse", api_key: str = "", location: str = "北京"):
        self.provider = provider
        self.api_key = api_key
        self.location = location
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10))
        return self._client

    async def get_forecast(self, days: int = 3, location: str = "") -> list[WeatherForecast]:
        """获取天气预报。

        Args:
            days: 天数 (1-7)
            location: 城市名，如"北京""上海""昌平"。为空则用配置的默认值
        """
        loc = location or self.location
        if not self.api_key:
            logger.warning("No weather API key configured")
            return []

        try:
            if self.provider == "seniverse":
                return await self._seniverse_forecast(days, loc)
            elif self.provider == "openweathermap":
                return await self._owm_forecast(days, loc)
            else:
                logger.warning(f"Unknown weather provider: {self.provider}")
                return []
        except Exception as e:
            logger.error(f"Weather API error: {e}")
            return []

    async def _seniverse_forecast(self, days: int = 3, location: str = "") -> list[WeatherForecast]:
        """心知天气 API。location 支持中文名(北京)、拼音(beijing)、ID。"""
        client = await self._get_client()
        loc = location or self.location
        response = await client.get(
            "https://api.seniverse.com/v3/weather/daily.json",
            params={
                "key": self.api_key,
                "location": loc,
                "language": "zh-Hans",
                "unit": "c",
                "start": 0,
                "days": days,
            },
        )
        response.raise_for_status()
        data = response.json()

        forecasts = []
        for result in data.get("results", []):
            loc_name = result.get("location", {}).get("name", self.location)
            for day_data in result.get("daily", []):
                forecasts.append(
                    WeatherForecast(
                        date=day_data.get("date", ""),
                        location=loc_name,
                        temperature_high=float(day_data.get("high", 0)),
                        temperature_low=float(day_data.get("low", 0)),
                        condition=day_data.get("text_day", "未知"),
                        humidity=int(day_data.get("humidity", 0)),
                        wind_speed=float(day_data.get("wind_speed", 0)),
                        wind_direction=day_data.get("wind_direction", ""),
                        rain_probability=int(day_data.get("rain_probability", 0)),
                    )
                )

        return forecasts

    async def _owm_forecast(self, days: int = 3, location: str = "") -> list[WeatherForecast]:
        """OpenWeatherMap API。"""
        client = await self._get_client()
        loc = location or self.location

        geo_response = await client.get(
            "https://api.openweathermap.org/geo/1.0/direct",
            params={"q": loc, "limit": 1, "appid": self.api_key},
        )
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if not geo_data:
            logger.error(f"Location not found: {self.location}")
            return []

        lat = geo_data[0]["lat"]
        lon = geo_data[0]["lon"]
        loc_name = geo_data[0].get("local_names", {}).get("zh", self.location)

        # Get forecast
        fc_response = await client.get(
            "https://api.openweathermap.org/data/3.0/onecall",
            params={
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric",
                "lang": "zh_cn",
                "exclude": "minutely,hourly,alerts",
            },
        )
        fc_response.raise_for_status()
        fc_data = fc_response.json()

        forecasts = []
        for day_data in fc_data.get("daily", [])[:days]:
            weather = day_data.get("weather", [{}])[0]
            forecasts.append(
                WeatherForecast(
                    date=str(day_data.get("dt", "")),
                    location=loc_name,
                    temperature_high=float(day_data.get("temp", {}).get("max", 0)),
                    temperature_low=float(day_data.get("temp", {}).get("min", 0)),
                    condition=weather.get("description", "未知"),
                    humidity=int(day_data.get("humidity", 0)),
                    wind_speed=float(day_data.get("wind_speed", 0)),
                    rain_probability=int(day_data.get("pop", 0) * 100),
                )
            )

        return forecasts

    async def get_today_forecast(self) -> Optional[WeatherForecast]:
        """Get today's forecast only."""
        forecasts = await self.get_forecast(days=1)
        return forecasts[0] if forecasts else None

    async def has_rain_warning(self) -> bool:
        """Check if there's a rain warning for today."""
        today = await self.get_today_forecast()
        if today is None:
            return False
        rain_keywords = ["雨", "雪", "暴", "雷", "阵雨", "小雨", "中雨", "大雨", "暴雨"]
        return any(kw in today.condition for kw in rain_keywords) or today.rain_probability > 50

    async def needs_umbrella(self) -> tuple[bool, str]:
        """Check if an umbrella is needed and return a message."""
        today = await self.get_today_forecast()
        if today is None:
            return False, ""

        rain_keywords = ["雨", "雪", "暴", "雷"]
        needs = any(kw in today.condition for kw in rain_keywords) or today.rain_probability > 60

        if needs:
            return True, f"今天{today.condition}，降水概率{today.rain_probability}%，记得带伞哦！"
        return False, ""

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
