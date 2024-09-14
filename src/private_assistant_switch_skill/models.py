import re

from pydantic import ValidationInfo, field_validator
from sqlmodel import Field, SQLModel
from sqlmodel._compat import SQLModelConfig

# Define a regex pattern for a valid MQTT topic
MQTT_TOPIC_REGEX = re.compile(r"[\$#\+\s\0-\31]+")  # Disallow '+', '#', whitespace, and control characters


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
    def validate_topic(cls, value: str, info: ValidationInfo):
        # Check for any invalid characters in the topic
        if MQTT_TOPIC_REGEX.findall(value):
            raise ValueError("must not contain '+', '#', whitespace, or control characters.")
        if len(value) > 128:
            raise ValueError("Topic length exceeds maximum allowed limit (128 characters).")

        # Trim any leading or trailing whitespace just in case
        return value.strip()
