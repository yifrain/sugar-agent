"""Blood glucose trend analysis and alerting."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from sugar_agent.health.models import BloodGlucoseReading, TrendReport


class BloodGlucoseAnalyzer:
    """Analyzes blood glucose data for trends and alerts."""

    def __init__(
        self,
        low_threshold: float = 3.9,
        high_threshold: float = 10.0,
        urgent_low: float = 3.0,
        urgent_high: float = 16.0,
        target_low: float = 3.9,
        target_high: float = 7.0,
    ):
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self.urgent_low = urgent_low
        self.urgent_high = urgent_high
        self.target_low = target_low
        self.target_high = target_high

    def analyze_trend(self, readings: list[BloodGlucoseReading], days: int = 7) -> TrendReport:
        """Generate a trend report from recent readings.

        Args:
            readings: List of blood glucose readings
            days: Number of days to analyze

        Returns:
            TrendReport with statistics and analysis
        """
        if not readings:
            return TrendReport(
                days=days,
                total_readings=0,
                avg_value=0,
                min_value=0,
                max_value=0,
                std_dev=0,
                time_in_range_pct=0,
                time_low_pct=0,
                time_high_pct=0,
                trend_direction="no_data",
                summary="暂无血糖数据。",
            )

        values = [r.value_mmol for r in readings]
        total = len(values)

        # Basic statistics
        avg = sum(values) / total
        min_val = min(values)
        max_val = max(values)

        # Standard deviation
        variance = sum((v - avg) ** 2 for v in values) / total
        std = variance**0.5

        # Time in range calculations
        in_range = sum(1 for v in values if self.target_low <= v <= self.target_high)
        low_count = sum(1 for v in values if v < self.low_threshold)
        high_count = sum(1 for v in values if v > self.high_threshold)

        in_range_pct = round(in_range / total * 100, 1)
        low_pct = round(low_count / total * 100, 1)
        high_pct = round(high_count / total * 100, 1)

        # Group by context
        by_context: dict[str, list[float]] = {}
        for r in readings:
            ctx = r.context or "random"
            if ctx not in by_context:
                by_context[ctx] = []
            by_context[ctx].append(r.value_mmol)

        # Trend direction
        trend = self._calculate_trend(values)

        # Summary
        summary = self._generate_summary(
            total, avg, min_val, max_val, in_range_pct, low_pct, high_pct, trend
        )

        return TrendReport(
            days=days,
            total_readings=total,
            avg_value=round(avg, 1),
            min_value=round(min_val, 1),
            max_value=round(max_val, 1),
            std_dev=round(std, 2),
            time_in_range_pct=in_range_pct,
            time_low_pct=low_pct,
            time_high_pct=high_pct,
            readings_by_context=by_context,
            trend_direction=trend,
            summary=summary,
        )

    def _calculate_trend(self, values: list[float]) -> str:
        """Calculate if the trend is improving, stable, or worsening."""
        if len(values) < 6:
            return "insufficient_data"

        # Split into two halves and compare averages
        mid = len(values) // 2
        first_half_avg = sum(values[:mid]) / mid
        second_half_avg = sum(values[mid:]) / (len(values) - mid)

        diff = second_half_avg - first_half_avg

        # For blood glucose, lower (closer to target) is generally better
        # ...unless it's going too low
        if abs(diff) < 1.0:
            return "stable"
        elif diff < 0:
            # Going down - could be good or bad
            if second_half_avg < self.target_low:
                return "worsening_low"
            elif first_half_avg > self.target_high:
                return "improving"
            else:
                return "stable"
        else:
            # Going up
            if second_half_avg > self.target_high and first_half_avg <= self.target_high:
                return "worsening_high"
            elif first_half_avg < self.target_low:
                return "improving"
            else:
                return "worsening_high"

    def _generate_summary(
        self,
        total: int,
        avg: float,
        min_val: float,
        max_val: float,
        in_range_pct: float,
        low_pct: float,
        high_pct: float,
        trend: str,
    ) -> str:
        """Generate a human-readable summary in Chinese."""
        parts = [
            f"共{total}次记录",
            f"平均{avg:.1f} mmol/L",
        ]

        if in_range_pct >= 70:
            parts.append(f"达标率{in_range_pct}% ✅")
        elif in_range_pct >= 50:
            parts.append(f"达标率{in_range_pct}%，还需努力 💪")
        else:
            parts.append(f"达标率{in_range_pct}%，需要关注 ⚠️")

        if low_pct > 5:
            parts.append(f"低血糖占比{low_pct}%，要注意 ⚠️")

        trend_labels = {
            "improving": "整体趋势向好 📉",
            "stable": "整体稳定 📊",
            "worsening_high": "血糖有升高趋势，需要关注 ⚠️",
            "worsening_low": "血糖有降低趋势，注意预防低血糖 ⚠️",
            "insufficient_data": "数据不足，继续记录吧",
        }
        parts.append(trend_labels.get(trend, ""))

        return "；".join(parts)

    def check_alert(self, reading: BloodGlucoseReading) -> Optional[str]:
        """Check if a reading requires an alert and return the alert level.

        Returns:
            'urgent_low', 'low', 'high', 'urgent_high', or None for normal
        """
        v = reading.value_mmol
        if v < self.urgent_low:
            return "urgent_low"
        elif v < self.low_threshold:
            return "low"
        elif v > self.urgent_high:
            return "urgent_high"
        elif v > self.high_threshold:
            return "high"
        return None

    def get_alert_message(self, reading: BloodGlucoseReading) -> Optional[str]:
        """Generate a human-readable alert message for a reading.

        These are fallback messages if the LLM is unavailable.
        """
        alert = self.check_alert(reading)
        if not alert:
            return None

        messages = {
            "urgent_low": f"⚠️ 血糖严重偏低 ({reading.value_mmol} mmol/L)！请立即吃点糖或喝果汁，然后15分钟后再测一次！",
            "low": f"血糖有点偏低哦 ({reading.value_mmol} mmol/L)，记得吃点东西补充一下~",
            "high": f"血糖偏高 ({reading.value_mmol} mmol/L)，要不要测一下酮体？多喝水会有帮助~",
            "urgent_high": f"⚠️ 血糖严重偏高 ({reading.value_mmol} mmol/L)！请立即测酮体，如有酮体请及时就医！",
        }
        return messages[alert]
