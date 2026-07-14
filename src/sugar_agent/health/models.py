"""Health data models for blood glucose tracking."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class BloodGlucoseReading(BaseModel):
    """A single blood glucose reading."""

    id: Optional[int] = None
    value: float = Field(..., description="Blood glucose value")
    unit: str = Field(default="mmol/L", description="Unit of measurement")
    value_mmol: float = Field(..., description="Value normalized to mmol/L")
    context: Optional[str] = Field(
        default=None,
        description="Measurement context: fasting, before_meal, after_meal, bedtime, random",
    )
    notes: Optional[str] = Field(default=None, description="Additional context from user")
    recorded_at: Optional[datetime] = Field(
        default=None, description="When the reading was taken"
    )
    source_message_id: Optional[int] = Field(
        default=None, description="Message ID that this reading was extracted from"
    )
    created_at: Optional[datetime] = None

    @property
    def is_low(self) -> bool:
        """Blood glucose is below 3.9 mmol/L (hypoglycemia)."""
        return self.value_mmol < 3.9

    @property
    def is_urgent_low(self) -> bool:
        """Blood glucose is critically low (< 3.0 mmol/L)."""
        return self.value_mmol < 3.0

    @property
    def is_high(self) -> bool:
        """Blood glucose is elevated (> 10.0 mmol/L)."""
        return self.value_mmol > 10.0

    @property
    def is_urgent_high(self) -> bool:
        """Blood glucose is dangerously high (> 16.0 mmol/L)."""
        return self.value_mmol > 16.0

    @property
    def is_normal(self) -> bool:
        """Blood glucose is in the target range (3.9-10.0 mmol/L)."""
        return 3.9 <= self.value_mmol <= 10.0

    @property
    def alert_level(self) -> str:
        """Get the alert level for this reading."""
        if self.is_urgent_low:
            return "urgent_low"
        elif self.is_low:
            return "low"
        elif self.is_urgent_high:
            return "urgent_high"
        elif self.is_high:
            return "high"
        else:
            return "normal"


def convert_to_mmol(value: float, unit: str) -> float:
    """Convert blood glucose to mmol/L.

    mg/dL to mmol/L: divide by 18.0182
    """
    unit_lower = unit.lower().strip()
    if "mg" in unit_lower or "mg/dl" in unit_lower:
        return round(value / 18.0182, 1)
    # Default: already in mmol/L
    return round(value, 1)


class TrendReport(BaseModel):
    """Blood glucose trend analysis report."""

    days: int
    total_readings: int
    avg_value: float
    min_value: float
    max_value: float
    std_dev: float
    time_in_range_pct: float  # 3.9-10.0 mmol/L
    time_low_pct: float  # < 3.9
    time_high_pct: float  # > 10.0
    readings_by_context: dict[str, list[float]] = Field(default_factory=dict)
    trend_direction: str = "stable"  # improving, stable, worsening
    summary: str = ""
