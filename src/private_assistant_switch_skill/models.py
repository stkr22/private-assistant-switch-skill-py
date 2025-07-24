import re

from pydantic import field_validator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

# Define a regex pattern for a valid MQTT topic
MQTT_TOPIC_REGEX = re.compile(r"[\$#\+\s\0-\31]+")  # Disallow '+', '#', whitespace, and control characters
MQTT_TOPIC_MAX_LENGTH = 128


class SQLModelValidation(SQLModel):
    """
    Helper class to allow for validation in SQLModel classes with table=True
    """

    model_config = SQLModelConfig(from_attributes=True, validate_assignment=True)


class SwitchSkillDevice(SQLModelValidation, table=True):  # type: ignore
    id: int | None = Field(default=None, primary_key=True)
    topic: str
    alias: str
    room: str
    payload_on: str = "ON"
    payload_off: str = "OFF"

    # Validate the topic field to ensure it conforms to MQTT standards
    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str):
        # Check for any invalid characters in the topic
        if MQTT_TOPIC_REGEX.findall(value):
            raise ValueError("must not contain '+', '#', whitespace, or control characters.")
        if len(value) > MQTT_TOPIC_MAX_LENGTH:
            raise ValueError(f"Topic length exceeds maximum allowed limit ({MQTT_TOPIC_MAX_LENGTH} characters).")

        # Trim any leading or trailing whitespace just in case
        return value.strip()
