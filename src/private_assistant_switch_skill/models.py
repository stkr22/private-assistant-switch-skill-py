import re

from pydantic import field_validator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

# AIDEV-NOTE: MQTT topic validation - strict validation prevents zigbee2mqtt communication issues
MQTT_TOPIC_REGEX = re.compile(r"[\$#\+\s\0-\31]+")  # Disallow '+', '#', whitespace, and control characters
MQTT_TOPIC_MAX_LENGTH = 128


class SQLModelValidation(SQLModel):
    """Helper class to enable Pydantic validation in SQLModel table classes.

    Provides validation configuration for SQLModel classes with table=True,
    enabling field validation and assignment validation.
    """

    model_config = SQLModelConfig(from_attributes=True, validate_assignment=True)


class SwitchSkillDevice(SQLModelValidation, table=True):  # type: ignore
    """Database model for smart home devices controlled by the switch skill.

    Represents a zigbee2mqtt device that can be controlled via MQTT commands.
    Includes validation for MQTT topic format and length restrictions.

    Attributes:
        id: Primary key, auto-generated
        topic: MQTT topic for device control (validated)
        alias: Human-readable device name for voice commands
        room: Room location for context-aware device resolution
        payload_on: MQTT payload to turn device on (default "ON")
        payload_off: MQTT payload to turn device off (default "OFF")
    """

    id: int | None = Field(default=None, primary_key=True)
    topic: str
    alias: str
    room: str
    payload_on: str = "ON"
    payload_off: str = "OFF"

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        """Validate MQTT topic format and length.

        Ensures topic conforms to MQTT standards by checking for invalid characters
        and enforcing length limits.

        Args:
            value: The MQTT topic string to validate

        Returns:
            str: The validated and trimmed topic string

        Raises:
            ValueError: If topic contains invalid characters or exceeds length limit
        """
        if MQTT_TOPIC_REGEX.findall(value):
            raise ValueError("must not contain '+', '#', whitespace, or control characters.")
        if len(value) > MQTT_TOPIC_MAX_LENGTH:
            raise ValueError(f"Topic length exceeds maximum allowed limit ({MQTT_TOPIC_MAX_LENGTH} characters).")

        return value.strip()

    @field_validator("alias", "room")
    @classmethod
    def validate_non_empty_strings(cls, value: str) -> str:
        """Validate that alias and room are non-empty strings.

        Args:
            value: The string value to validate

        Returns:
            str: The validated and trimmed string

        Raises:
            ValueError: If string is empty or only whitespace
        """
        if not value or not value.strip():
            raise ValueError("Field cannot be empty or only whitespace.")
        return value.strip()

