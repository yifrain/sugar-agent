"""Tests for the blood glucose Chinese NL parser."""

import pytest
from sugar_agent.health.parser import BloodGlucoseParser


class TestBloodGlucoseParser:
    """Test the blood glucose parser with various Chinese messages."""

    def setup_method(self):
        self.parser = BloodGlucoseParser(default_unit="mmol/L")

    def test_basic_bg_patterns(self):
        """Test basic blood glucose patterns."""
        cases = [
            ("血糖7.8", 7.8),
            ("血糖 5.2", 5.2),
            ("血糖: 8.0", 8.0),
            ("糖7.8", 7.8),
            ("血糖是6.2", 6.2),
            ("血糖值5.5", 5.5),
            ("测了血糖7.8", 7.8),
        ]
        for text, expected in cases:
            result = self.parser.parse(text)
            assert result is not None, f"Should parse: {text}"
            assert result.value_mmol == expected, f"{text}: expected {expected}, got {result.value_mmol}"

    def test_context_detection(self):
        """Test measurement context detection."""
        cases = [
            ("空腹血糖5.2", "fasting"),
            ("餐前血糖6.1", "before_meal"),
            ("餐后2小时血糖8.9", "after_meal"),
            ("晚饭后血糖9.5", "after_meal"),
            ("睡前血糖6.7", "bedtime"),
            ("早上血糖4.5", "fasting"),
            ("午餐后血糖12.3", "after_meal"),
        ]
        for text, expected_context in cases:
            result = self.parser.parse(text)
            assert result is not None, f"Should parse: {text}"
            assert result.context == expected_context, (
                f"{text}: expected context '{expected_context}', got '{result.context}'"
            )

    def test_non_bg_messages(self):
        """Test that non-blood-sugar messages are not parsed."""
        cases = [
            "今天天气真好",
            "晚上吃什么",
            "我今天很开心",
            "在干嘛呢",
            "想你了",
        ]
        for text in cases:
            result = self.parser.parse(text)
            assert result is None, f"Should NOT parse as BG: {text}"

    def test_out_of_range_values(self):
        """Test that out-of-range values are rejected."""
        # 0.1 is too low to be a real blood sugar
        result = self.parser.parse("血糖0.1")
        assert result is None, "0.1 should be rejected as too low"

        # 50.0 is unrealistically high
        result = self.parser.parse("血糖50.0")
        assert result is None, "50.0 should be rejected as too high"

    def test_alert_levels(self):
        """Test alert level classification."""
        from sugar_agent.health.models import BloodGlucoseReading, convert_to_mmol

        # Urgent low
        reading = BloodGlucoseReading(value=2.5, unit="mmol/L", value_mmol=2.5)
        assert reading.is_urgent_low
        assert reading.alert_level == "urgent_low"

        # Low
        reading = BloodGlucoseReading(value=3.5, unit="mmol/L", value_mmol=3.5)
        assert reading.is_low
        assert reading.alert_level == "low"

        # Normal
        reading = BloodGlucoseReading(value=5.5, unit="mmol/L", value_mmol=5.5)
        assert reading.is_normal
        assert reading.alert_level == "normal"

        # High
        reading = BloodGlucoseReading(value=12.0, unit="mmol/L", value_mmol=12.0)
        assert reading.is_high
        assert reading.alert_level == "high"

        # Urgent high
        reading = BloodGlucoseReading(value=18.0, unit="mmol/L", value_mmol=18.0)
        assert reading.is_urgent_high
        assert reading.alert_level == "urgent_high"

    def test_unit_conversion(self):
        """Test unit conversion from mg/dL to mmol/L."""
        from sugar_agent.health.models import convert_to_mmol

        # 180 mg/dL ≈ 10.0 mmol/L
        mmol = convert_to_mmol(180, "mg/dL")
        assert round(mmol, 1) == 10.0

        # 90 mg/dL ≈ 5.0 mmol/L
        mmol = convert_to_mmol(90, "mg/dL")
        assert round(mmol, 1) == 5.0

    def test_trend_report(self):
        """Test trend analysis."""
        from sugar_agent.health.analyzer import BloodGlucoseAnalyzer
        from sugar_agent.health.models import BloodGlucoseReading

        analyzer = BloodGlucoseAnalyzer()

        # Create some sample readings
        readings = [
            BloodGlucoseReading(value=5.0, unit="mmol/L", value_mmol=5.0, context="fasting"),
            BloodGlucoseReading(value=6.0, unit="mmol/L", value_mmol=6.0, context="fasting"),
            BloodGlucoseReading(value=8.5, unit="mmol/L", value_mmol=8.5, context="after_meal"),
            BloodGlucoseReading(value=4.5, unit="mmol/L", value_mmol=4.5, context="fasting"),
            BloodGlucoseReading(value=5.5, unit="mmol/L", value_mmol=5.5, context="fasting"),
        ]

        report = analyzer.analyze_trend(readings, days=7)

        assert report.total_readings == 5
        assert 4.5 <= report.avg_value <= 8.5
        assert report.min_value == 4.5
        assert report.max_value == 8.5
        assert len(report.readings_by_context) >= 2
