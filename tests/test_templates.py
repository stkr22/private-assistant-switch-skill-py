from unittest.mock import AsyncMock, Mock

import jinja2
import pytest

from private_assistant_switch_skill.models import SwitchSkillDevice
from private_assistant_switch_skill.switch_skill import Action, DeviceLocation, Parameters, SwitchSkill


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
    mock_mqtt = AsyncMock()
    mock_db = AsyncMock()
    mock_task_group = AsyncMock()
    mock_logger = Mock()

    # Create SwitchSkill instance
    skill = SwitchSkill(
        config_obj=mock_config,
        mqtt_client=mock_mqtt,
        db_engine=mock_db,
        template_env=env,
        task_group=mock_task_group,
        logger=mock_logger,
    )

    # Load templates
    skill.action_to_answer[Action.HELP] = env.get_template("help.j2")
    skill.action_to_answer[Action.ON] = env.get_template("state.j2")
    skill.action_to_answer[Action.OFF] = env.get_template("state.j2")
    skill.action_to_answer[Action.LIST] = env.get_template("list.j2")

    return skill


@pytest.mark.parametrize(
    "targets, expected_output",
    [
        ([], "No devices were found.\n"),
        (
            [DeviceLocation(device=SwitchSkillDevice(alias="Living Room Light"), found_room="living room")],
            "The following devices are available: Living Room Light\n",
        ),
        (
            [
                DeviceLocation(device=SwitchSkillDevice(alias="Living Room Light"), found_room="living room"),
                DeviceLocation(device=SwitchSkillDevice(alias="Bedroom Fan"), found_room="living room"),
            ],
            "The following devices are available: Living Room Light and Bedroom Fan\n",
        ),
        (
            [
                DeviceLocation(device=SwitchSkillDevice(alias="Living Room Light"), found_room="living room"),
                DeviceLocation(device=SwitchSkillDevice(alias="Bedroom Fan"), found_room="living room"),
                DeviceLocation(device=SwitchSkillDevice(alias="Kitchen Light"), found_room="living room"),
            ],
            "The following devices are available: Living Room Light, Bedroom Fan and Kitchen Light\n",
        ),
    ],
)
def test_list_command(switch_skill, targets, expected_output, current_room="living room"):
    parameters = Parameters(targets=targets, current_room=current_room)
    result = switch_skill.get_answer(Action.LIST, parameters)
    assert result == expected_output


@pytest.mark.parametrize(
    "action, targets, current_room, expected_output",
    [
        # Test with a single device in current room
        (
            Action.ON,
            [DeviceLocation(device=SwitchSkillDevice(alias="Living Room Light"), found_room="living room")],
            "living room",
            "The device Living Room Light has been turned on.\n",
        ),
        # Test with a single device in different room
        (
            Action.ON,
            [DeviceLocation(device=SwitchSkillDevice(alias="Bedroom Fan"), found_room="bedroom")],
            "living room",
            "The device Bedroom Fan (found in bedroom) has been turned on.\n",
        ),
        # Test with no devices
        (Action.ON, [], "living room", "No devices matching the request were found.\n"),
        # Test with multiple devices in different rooms
        (
            Action.ON,
            [
                DeviceLocation(device=SwitchSkillDevice(alias="Living Room Light"), found_room="living room"),
                DeviceLocation(device=SwitchSkillDevice(alias="Bedroom Fan"), found_room="bedroom"),
            ],
            "living room",
            "The devices Living Room Light and Bedroom Fan (found in bedroom) have been turned on.\n",
        ),
        # Test with multiple devices in different rooms (three devices)
        (
            Action.OFF,
            [
                DeviceLocation(device=SwitchSkillDevice(alias="Living Room Light"), found_room="living room"),
                DeviceLocation(device=SwitchSkillDevice(alias="Bedroom Fan"), found_room="bedroom"),
                DeviceLocation(device=SwitchSkillDevice(alias="Kitchen Light"), found_room="kitchen"),
            ],
            "living room",
            "The devices Living Room Light, Bedroom Fan (found in bedroom) and Kitchen Light (found in kitchen)"
            " have been turned off.\n",
        ),
    ],
)
def test_state_command(switch_skill, action, targets, current_room, expected_output):
    parameters = Parameters(targets=targets, current_room=current_room)
    result = switch_skill.get_answer(action, parameters)
    assert result == expected_output


@pytest.mark.parametrize(
    "action, targets, rooms, expected_output",
    [
        # Single room, devices found
        (
            Action.ROOM_ON,
            [
                DeviceLocation(device=SwitchSkillDevice(alias="Main Light"), found_room="living room"),
                DeviceLocation(device=SwitchSkillDevice(alias="Secondary Light"), found_room="living room"),
            ],
            ["living room"],
            "Turned on all lights in living room.\n",
        ),
        # Multiple rooms, devices found
        (
            Action.ROOM_OFF,
            [
                DeviceLocation(device=SwitchSkillDevice(alias="Living Light"), found_room="living room"),
                DeviceLocation(device=SwitchSkillDevice(alias="Bedroom Light"), found_room="bedroom"),
            ],
            ["living room", "bedroom", "kitchen"],
            "Turned off all lights in living room, bedroom and kitchen.\n",
        ),
        # No devices found
        (
            Action.ROOM_ON,
            [],
            ["living room"],
            "I couldn't find any lights in this room.\n",
        ),
        # No devices found in multiple rooms
        (
            Action.ROOM_OFF,
            [],
            ["living room", "bedroom"],
            "I couldn't find any lights in these rooms.\n",
        ),
    ],
)
def test_room_state_command(switch_skill, action, targets, rooms, expected_output):
    parameters = Parameters(targets=targets, current_room=rooms[0], rooms=rooms)
    result = switch_skill.get_answer(action, parameters)
    assert result == expected_output
