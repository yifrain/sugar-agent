"""Chinese natural language parser for blood glucose values.

Two-stage parsing:
1. Fast regex-based extraction (covers >90% of common patterns)
2. LLM-based fallback for ambiguous or novel formats
"""

import re
from datetime import datetime
from typing import Optional

from loguru import logger

from sugar_agent.health.models import BloodGlucoseReading, convert_to_mmol


# Regex patterns for blood glucose extraction
BG_PATTERNS = [
    # "血糖7.8", "血糖 5.2", "血糖: 8.0", "糖7.8"
    r"(?:血?糖)\s*[：:]\s*(\d+\.?\d*)",
    # "血糖是7.8", "血糖值5.2"
    r"(?:血?糖[值是]?)\s*(\d+\.?\d*)",
    # "BG 7.8", "bs 5.2" (case insensitive)
    r"(?i)(?:bg|bs|glucose)\s*[：:]?\s*(\d+\.?\d*)",
    # "测了血糖7.8"
    r"测了?血糖\s*(\d+\.?\d*)",
    # Just a number after context words (looser pattern, lower priority)
    r"(?:血糖|测糖|测了)\D{0,5}?(\d+\.?\d{1,2})",
]

# Context detection patterns
CONTEXT_PATTERNS = {
    "fasting": r"空腹|早起|早饭?前|早上|起床|清晨",
    "before_meal": r"餐前|饭前|吃饭前|午饭前|晚饭前|晚餐前",
    "after_meal": r"餐后|饭后|餐\d*后|吃饭后|午饭后|晚饭后|晚餐后|吃了|吃完",
    "bedtime": r"睡前|睡觉前|睡前|晚上睡觉|准备睡",
}

# Unit detection patterns
UNIT_MGDL_PATTERN = r"mg\s*[\\/]?\s*d[lL]|毫克"
UNIT_MMOL_PATTERN = r"mmol|毫摩尔"


class BloodGlucoseParser:
    """Parses blood glucose values from Chinese natural language messages."""

    def __init__(self, default_unit: str = "mmol/L"):
        self.default_unit = default_unit

    def parse(self, text: str, recorded_at: Optional[datetime] = None) -> Optional[BloodGlucoseReading]:
        """Extract a blood glucose reading from a text message.

        Args:
            text: The message text to parse
            recorded_at: Optional timestamp of when the reading was taken

        Returns:
            BloodGlucoseReading if found, None otherwise
        """
        result = self._parse_regex(text)
        if result is None:
            return None

        value, unit, context = result

        # Add recorded_at if provided
        extra = {}
        if recorded_at:
            extra["recorded_at"] = recorded_at

        return self._create_reading(value, unit, context, text, **extra)

    def _parse_regex(self, text: str) -> Optional[tuple[float, str, Optional[str]]]:
        """First-stage: regex-based parsing."""
        # Try each blood glucose pattern
        for pattern in BG_PATTERNS:
            match = re.search(pattern, text)
            if match:
                value_str = match.group(1)
                try:
                    value = float(value_str)
                except ValueError:
                    continue

                # Validate: blood glucose should be 1.0-40.0 mmol/L or 18-720 mg/dL
                unit = self._detect_unit(text)
                if unit == "mg/dL":
                    if not (18 <= value <= 720):
                        logger.debug(f"BG value {value} mg/dL out of range")
                        continue
                else:
                    if not (1.0 <= value <= 40.0):
                        logger.debug(f"BG value {value} mmol/L out of range")
                        continue

                # Detect context
                context = self._detect_context(text)

                # Detect unit
                unit = self._detect_unit(text)

                logger.debug(
                    f"Parsed BG: value={value}, unit={unit}, context={context}"
                )
                return (value, unit, context)

        return None

    def _detect_context(self, text: str) -> Optional[str]:
        """Detect the measurement context from the text."""
        # Check for explicit context mentions
        for context_name, pattern in CONTEXT_PATTERNS.items():
            if re.search(pattern, text):
                return context_name
        return None

    def _detect_unit(self, text: str) -> str:
        """Detect the blood glucose unit."""
        if re.search(UNIT_MGDL_PATTERN, text, re.IGNORECASE):
            return "mg/dL"
        # mmol is the default for China
        return self.default_unit

    def _create_reading(
        self,
        value: float,
        unit: str,
        context: Optional[str],
        raw_text: str,
        **extra,
    ) -> BloodGlucoseReading:
        """Create a BloodGlucoseReading with normalized values."""
        value_mmol = convert_to_mmol(value, unit)

        return BloodGlucoseReading(
            value=value,
            unit=unit,
            value_mmol=value_mmol,
            context=context,
            notes=raw_text[:200],  # Store original message as notes
            **extra,
        )

    async def parse_with_llm(
        self, text: str, llm_client=None
    ) -> Optional[BloodGlucoseReading]:
        """Second-stage: use LLM to extract blood glucose from ambiguous text.

        Args:
            text: The message text
            llm_client: LLMClient instance for the fallback extraction

        Returns:
            BloodGlucoseReading if found, None otherwise
        """
        if llm_client is None:
            return None

        extraction_prompt = f"""从以下消息中尝试提取血糖信息。

消息: "{text}"

如果消息中包含血糖数值，返回JSON格式:
{{"found": true, "value": 数值, "unit": "mmol/L或mg/dL", "context": "fasting/before_meal/after_meal/bedtime/random", "notes": "额外信息"}}

如果消息中不包含血糖信息，返回:
{{"found": false}}

只返回JSON，不要其他内容。"""

        try:
            response = await llm_client.simple_chat(
                [{"role": "user", "content": extraction_prompt}],
                temperature=0.0,
                max_tokens=200,
            )

            # Parse JSON from response
            import json

            # Clean response - might have markdown code blocks
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]

            data = json.loads(clean)

            if data.get("found"):
                value = float(data["value"])
                unit = data.get("unit", "mmol/L")
                value_mmol = convert_to_mmol(value, unit)
                return BloodGlucoseReading(
                    value=value,
                    unit=unit,
                    value_mmol=value_mmol,
                    context=data.get("context"),
                    notes=data.get("notes"),
                )

        except Exception as e:
            logger.debug(f"LLM BG extraction failed: {e}")

        return None
