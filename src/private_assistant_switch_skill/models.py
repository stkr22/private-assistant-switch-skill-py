import re
from uuid import UUID

from private_assistant_commons.database.models import GlobalDevice
from pydantic import BaseModel, field_validator

# AIDEV-NOTE: MQTT topic validation - strict validation prevents zigbee2mqtt communication issues
MQTT_TOPIC_REGEX = re.compile(r"[\$#\+\s\0-\31]+")  # Disallow '+', '#', whitespace, and control characters
MQTT_TOPIC_MAX_LENGTH = 128


class SwitchSkillDevice(BaseModel):
    """Pydantic model for smart home devices controlled by the switch skill.

    Represents a zigbee2mqtt device that can be controlled via MQTT commands.
    This is a transformation layer over GlobalDevice for type-safe, validated access
    to skill-specific device attributes.

    Attributes:
        id: Unique device identifier (from GlobalDevice)
        alias: Human-readable device name for voice commands (from GlobalDevice.name)
        room: Room location for context-aware device resolution (from GlobalDevice.room.name)
        topic: MQTT topic for device control (from device_attributes, validated)
        payload_on: MQTT payload to turn device on (default "ON")
        payload_off: MQTT payload to turn device off (default "OFF")
    """

    id: UUID
    alias: str
    room: str
    topic: str
    payload_on: str = "ON"
    payload_off: str = "OFF"

    @classmethod
    def from_global_device(cls, global_device: GlobalDevice) -> "SwitchSkillDevice":
        """Transform GlobalDevice to SwitchSkillDevice.

        Extracts MQTT-specific attributes from device_attributes and room name from
        the eagerly-loaded room relationship.

        Args:
            global_device: GlobalDevice instance with eagerly loaded room relationship

        Returns:
            SwitchSkillDevice: Validated device model with MQTT attributes

        Raises:
            ValueError: If required attributes are missing or invalid
        """
        attrs = global_device.device_attributes or {}

        # Extract room name from eagerly-loaded relationship
        room_name = global_device.room.name if global_device.room else ""

        return cls(
            id=global_device.id,
            alias=global_device.name,
            room=room_name,
            topic=attrs.get("topic", ""),
            payload_on=attrs.get("payload_on", "ON"),
            payload_off=attrs.get("payload_off", "OFF"),
        )

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
