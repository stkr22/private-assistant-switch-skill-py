import uuid
from unittest.mock import AsyncMock, Mock

import jinja2
import pytest
from private_assistant_commons import IntentType

from private_assistant_switch_skill.models import SwitchSkillDevice
from private_assistant_switch_skill.switch_skill import (
    DeviceLocation,
    Parameters,
    SwitchSkill,
    SwitchSkillDependencies,
)


def create_test_device(alias: str, room: str = "living room", topic: str = "test/topic") -> SwitchSkillDevice:
    """Create a test SwitchSkillDevice with all required fields."""
    return SwitchSkillDevice(
        id=uuid.uuid4(),
        alias=alias,
        room=room,
        topic=topic,
        payload_on="ON",
        payload_off="OFF",
    )


@pytest.fixture
def switch_skill():
    # Create a mock environment with our templates
    env = jinja2.Environment(
        loader=jinja2.PackageLoader(
            "private_assistant_switch_skill",
            "templates",
        ),
    )

    # Create minimal mocks required for SwitchSkill initialization
    mock_config = Mock()
    mock_config.client_id = "test_switch_skill"
    mock_mqtt = AsyncMock()
    mock_db = AsyncMock()
    mock_task_group = AsyncMock()
    mock_logger = Mock()

    # Create dependencies and SwitchSkill instance
    dependencies = SwitchSkillDependencies(
        db_engine=mock_db,
        template_env=env,
    )
    # Templates are already loaded in __init__, no need to manually load them
    return SwitchSkill(
        config_obj=mock_config,
        mqtt_client=mock_mqtt,
        dependencies=dependencies,
        task_group=mock_task_group,
        logger=mock_logger,
    )


@pytest.mark.parametrize(
    "intent_type, targets, current_room, expected_output",
    [
        # Test with a single device in current room
        (
            IntentType.DEVICE_ON,
            [DeviceLocation(device=create_test_device(alias="Living Room Light"), found_room="living room")],
            "living room",
            "The device Living Room Light has been turned on.",
        ),
        # Test with a single device in different room
        (
            IntentType.DEVICE_ON,
            [DeviceLocation(device=create_test_device(alias="Bedroom Fan"), found_room="bedroom")],
            "living room",
            "The device Bedroom Fan (found in bedroom) has been turned on.\n",
        ),
        # Test with no devices
        (IntentType.DEVICE_ON, [], "living room", "No devices matching the request were found."),
        # Test with multiple devices in different rooms
        (
            IntentType.DEVICE_ON,
            [
                DeviceLocation(device=create_test_device(alias="Living Room Light"), found_room="living room"),
                DeviceLocation(device=create_test_device(alias="Bedroom Fan"), found_room="bedroom"),
            ],
            "living room",
            "The devices Living Room Light and Bedroom Fan (found in bedroom) have been turned on.",
        ),
        # Test with multiple devices in different rooms (three devices)
        (
            IntentType.DEVICE_OFF,
            [
                DeviceLocation(device=create_test_device(alias="Living Room Light"), found_room="living room"),
                DeviceLocation(device=create_test_device(alias="Bedroom Fan"), found_room="bedroom"),
                DeviceLocation(device=create_test_device(alias="Kitchen Light"), found_room="kitchen"),
            ],
            "living room",
            "The devices Living Room Light, Bedroom Fan (found in bedroom) and Kitchen Light (found in kitchen)"
            " have been turned off.\n",
        ),
    ],
)
def test_state_command(switch_skill, intent_type, targets, current_room, expected_output):
    parameters = Parameters(targets=targets, current_room=current_room, is_room_wide=False)
    result = switch_skill._render_response(intent_type, parameters)
    assert result.strip() == expected_output.strip()


@pytest.mark.parametrize(
    "intent_type, targets, rooms, expected_output",
    [
        # Single room, devices found
        (
            IntentType.DEVICE_ON,
            [
                DeviceLocation(device=create_test_device(alias="Main Light"), found_room="living room"),
                DeviceLocation(device=create_test_device(alias="Secondary Light"), found_room="living room"),
            ],
            ["living room"],
            "Turned on all lights in living room.",
        ),
        # Multiple rooms, devices found
        (
            IntentType.DEVICE_OFF,
            [
                DeviceLocation(device=create_test_device(alias="Living Light"), found_room="living room"),
                DeviceLocation(device=create_test_device(alias="Bedroom Light"), found_room="bedroom"),
            ],
            ["living room", "bedroom", "kitchen"],
            "Turned off all lights in living room, bedroom and kitchen.",
        ),
        # No devices found
        (
            IntentType.DEVICE_ON,
            [],
            ["living room"],
            "I couldn't find any lights in this room.",
        ),
        # No devices found in multiple rooms
        (
            IntentType.DEVICE_OFF,
            [],
            ["living room", "bedroom"],
            "I couldn't find any lights in these rooms.",
        ),
    ],
)
def test_room_state_command(switch_skill, intent_type, targets, rooms, expected_output):
    parameters = Parameters(targets=targets, current_room=rooms[0], rooms=rooms, is_room_wide=True)
    result = switch_skill._render_response(intent_type, parameters)
    assert result.strip() == expected_output.strip()
