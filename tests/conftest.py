"""Shared test fixtures for Sugar Agent."""

import pytest


@pytest.fixture
def sample_chinese_messages():
    """Sample Chinese messages for testing blood sugar parsing."""
    return [
        # (message, expected_value_mmol, expected_context)
        ("血糖7.8", 7.8, None),
        ("血糖 5.2", 5.2, None),
        ("血糖: 8.0", 8.0, None),
        ("糖7.8", 7.8, None),
        ("空腹血糖5.2", 5.2, "fasting"),
        ("餐前血糖6.1", 6.1, "before_meal"),
        ("餐后2小时血糖8.9", 8.9, "after_meal"),
        ("晚饭后血糖9.5", 9.5, "after_meal"),
        ("睡前血糖6.7", 6.7, "bedtime"),
        ("早上血糖4.5 有点低", 4.5, "fasting"),
        ("测了血糖7.8", 7.8, None),
        ("午餐后血糖12.3 太高了", 12.3, "after_meal"),
        ("今天血糖一直不好 刚测了3.2", 3.2, None),
        ("血糖是6.2", 6.2, None),
        ("血糖值5.5", 5.5, None),
        # Should NOT parse as blood sugar
        ("今天天气真好", None, None),
        ("晚上吃什么", None, None),
        ("我今天买了个新血糖仪", None, None),
        # Edge cases
        ("血糖15.5", 15.5, None),
        ("空腹血糖3.8", 3.8, "fasting"),
    ]
