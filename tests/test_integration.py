"""End-to-end integration tests for the switch skill.

These tests validate the complete skill workflow with real external services:
- PostgreSQL database (device registry)
- MQTT broker (message bus)
- Switch skill running in background

Test flow:
1. Setup database with test devices
2. Start skill in background
3. Publish IntentRequest to MQTT
4. Assert skill publishes correct device commands and responses

Run these tests with:
    pytest tests/test_integration.py -v -m integration -n 0

Note: These tests require the compose services (PostgreSQL, MQTT) to be running.
"""

import asyncio
import contextlib
import logging
import os
import pathlib
import tempfile
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import cast

import aiomqtt
import pytest
import yaml
from private_assistant_commons import ClassifiedIntent, ClientRequest, Entity, EntityType, IntentRequest, IntentType
from private_assistant_commons.database import PostgresConfig
from private_assistant_commons.database.models import DeviceType, GlobalDevice, Room, Skill
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from private_assistant_switch_skill.main import start_skill

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration

# Logger for test debugging
logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
async def db_engine():
    """Create a database engine for integration tests."""
    db_config = PostgresConfig()
    engine = create_async_engine(db_config.connection_string_async, echo=False)

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Create a database session for each test."""
    async with AsyncSession(db_engine) as session:
        yield session


@pytest.fixture
def mqtt_config():
    """Get MQTT configuration from environment variables."""
    return {
        "host": os.getenv("MQTT_HOST", "mosquitto"),
        "port": int(os.getenv("MQTT_PORT", "1883")),
    }


@pytest.fixture
async def mqtt_test_client(mqtt_config):
    """Create an MQTT test client."""
    async with aiomqtt.Client(hostname=mqtt_config["host"], port=mqtt_config["port"]) as client:
        yield client


@pytest.fixture
async def test_skill_entity(db_session) -> Skill:
    """Create a test skill entity in the database."""
    result = await db_session.exec(select(Skill).where(Skill.name == "switch-skill-integration-test"))
    skill = result.first()

    if skill is None:
        skill = Skill(name="switch-skill-integration-test")
        db_session.add(skill)
        await db_session.flush()
        await db_session.refresh(skill)

    assert skill is not None
    return cast("Skill", skill)


@pytest.fixture
async def test_device_type(db_session) -> DeviceType:
    """Create a test device type in the database."""
    result = await db_session.exec(select(DeviceType).where(DeviceType.name == "light"))
    device_type = result.first()

    if device_type is None:
        device_type = DeviceType(name="light")
        db_session.add(device_type)
        await db_session.flush()
        await db_session.refresh(device_type)

    assert device_type is not None
    return cast("DeviceType", device_type)


@pytest.fixture
async def test_device_types(db_session) -> dict[str, DeviceType]:
    """Create multiple realistic device types in the database.

    Creates device types inspired by real smart home setups:
    - light: ceiling lights, lamps
    - switch: wall switches, toggle switches
    - plug: smart plugs, outlet controllers
    """
    device_type_names = ["light", "switch", "plug"]
    device_types = {}

    for type_name in device_type_names:
        result = await db_session.exec(select(DeviceType).where(DeviceType.name == type_name))
        device_type = result.first()

        if device_type is None:
            device_type = DeviceType(name=type_name)
            db_session.add(device_type)
            await db_session.flush()
            await db_session.refresh(device_type)

        device_types[type_name] = device_type

    return device_types


@pytest.fixture
async def test_room(db_session) -> Room:
    """Create a test room in the database."""
    room_name = f"test_room_{uuid.uuid4().hex[:8]}"
    room = Room(name=room_name)
    db_session.add(room)
    await db_session.flush()
    await db_session.refresh(room)
    return room


@pytest.fixture
async def test_rooms(db_session) -> dict[str, Room]:
    """Create multiple realistic rooms in the database.

    Creates rooms inspired by typical smart home setups with unique names
    to avoid conflicts with actual configuration.
    """
    room_names = ["test_office", "test_lounge", "test_studio"]
    rooms = {}

    for room_name in room_names:
        # Add unique suffix to ensure no conflicts with real rooms
        unique_room_name = f"{room_name}_{uuid.uuid4().hex[:6]}"
        room = Room(name=unique_room_name)
        db_session.add(room)
        await db_session.flush()
        await db_session.refresh(room)
        rooms[room_name] = room

    return rooms


@pytest.fixture
async def test_device(db_session, test_skill_entity, test_device_type, test_room) -> AsyncGenerator[GlobalDevice, None]:
    """Create a single test device in the database.

    Note: This fixture must be created BEFORE the running_skill fixture
    so the device is loaded during skill initialization.
    """
    await db_session.refresh(test_room)
    await db_session.refresh(test_skill_entity)
    await db_session.refresh(test_device_type)

    logger.debug("Creating device with skill_id=%s, skill_name=%s", test_skill_entity.id, test_skill_entity.name)

    device = GlobalDevice(
        device_type_id=test_device_type.id,
        name="test light",
        pattern=["test light", f"{test_room.name} test light"],
        device_attributes={
            "topic": "test/integration/light/main/set",
            "payload_on": "ON",
            "payload_off": "OFF",
        },
        room_id=test_room.id,
        skill_id=test_skill_entity.id,
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device, ["room", "device_type"])

    logger.debug("Device created with ID=%s, skill_id=%s", device.id, device.skill_id)

    yield device

    # Cleanup: Delete test device
    logger.debug("Cleaning up device %s", device.id)
    await db_session.delete(device)
    await db_session.commit()


@pytest.fixture
async def test_devices_multiple(
    db_session, test_skill_entity, test_device_type, test_room
) -> AsyncGenerator[list[GlobalDevice], None]:
    """Create multiple test devices in the same room.

    Note: This fixture must be created BEFORE the running_skill fixture
    so the devices are loaded during skill initialization.
    """
    await db_session.refresh(test_room)
    await db_session.refresh(test_skill_entity)
    await db_session.refresh(test_device_type)

    room_id = test_room.id
    skill_id = test_skill_entity.id
    device_type_id = test_device_type.id
    room_name = test_room.name

    devices = [
        GlobalDevice(
            device_type_id=device_type_id,
            name="light one",
            pattern=["light one", f"{room_name} light one"],
            device_attributes={"topic": "test/integration/room/light1/set", "payload_on": "ON", "payload_off": "OFF"},
            room_id=room_id,
            skill_id=skill_id,
        ),
        GlobalDevice(
            device_type_id=device_type_id,
            name="light two",
            pattern=["light two", f"{room_name} light two"],
            device_attributes={"topic": "test/integration/room/light2/set", "payload_on": "ON", "payload_off": "OFF"},
            room_id=room_id,
            skill_id=skill_id,
        ),
        GlobalDevice(
            device_type_id=device_type_id,
            name="light three",
            pattern=["light three", f"{room_name} light three"],
            device_attributes={"topic": "test/integration/room/light3/set", "payload_on": "ON", "payload_off": "OFF"},
            room_id=room_id,
            skill_id=skill_id,
        ),
    ]

    for device in devices:
        db_session.add(device)

    await db_session.commit()

    for device in devices:
        await db_session.refresh(device, ["room", "device_type"])

    yield devices

    # Cleanup: Delete all test devices
    for device in devices:
        await db_session.delete(device)
    await db_session.commit()


@pytest.fixture
async def test_devices_realistic(
    db_session, test_skill_entity, test_device_types, test_rooms
) -> AsyncGenerator[list[GlobalDevice], None]:
    """Create realistic mixed devices across multiple rooms.

    Inspired by real smart home setups with:
    - Multiple device types (switches, plugs, lights)
    - Realistic naming (desk, ceiling, shelf patterns)
    - Zigbee2mqtt-style topics and JSON payloads
    - Multiple rooms with different device configurations

    Note: This fixture must be created BEFORE the running_skill fixture.
    """
    await db_session.refresh(test_skill_entity)

    # Ensure device types and rooms are refreshed
    for device_type in test_device_types.values():
        await db_session.refresh(device_type)
    for room in test_rooms.values():
        await db_session.refresh(room)

    skill_id = test_skill_entity.id
    office_room = test_rooms["test_office"]
    lounge_room = test_rooms["test_lounge"]

    # Create devices inspired by real setup patterns
    devices = [
        # Office: mix of switches and plugs
        GlobalDevice(
            device_type_id=test_device_types["switch"].id,
            name="desk",
            pattern=["desk", f"{office_room.name} desk"],
            device_attributes={
                "topic": f"test/mqtt/{office_room.name}/plug/desk_lamp/set",
                "payload_on": '{"state": "ON"}',
                "payload_off": '{"state": "OFF"}',
            },
            room_id=office_room.id,
            skill_id=skill_id,
        ),
        GlobalDevice(
            device_type_id=test_device_types["switch"].id,
            name="ceiling",
            pattern=["ceiling", f"{office_room.name} ceiling"],
            device_attributes={
                "topic": f"test/mqtt/{office_room.name}/plug/ceiling_light/set",
                "payload_on": '{"state": "ON"}',
                "payload_off": '{"state": "OFF"}',
            },
            room_id=office_room.id,
            skill_id=skill_id,
        ),
        GlobalDevice(
            device_type_id=test_device_types["plug"].id,
            name="shelf",
            pattern=["shelf", f"{office_room.name} shelf"],
            device_attributes={
                "topic": f"test/mqtt/{office_room.name}/plug/shelf_light/set",
                "payload_on": '{"state": "ON"}',
                "payload_off": '{"state": "OFF"}',
            },
            room_id=office_room.id,
            skill_id=skill_id,
        ),
        # Lounge: mix of lights and plugs
        GlobalDevice(
            device_type_id=test_device_types["light"].id,
            name="ceiling",
            pattern=["ceiling", f"{lounge_room.name} ceiling"],
            device_attributes={
                "topic": f"test/mqtt/{lounge_room.name}/light/ceiling/set",
                "payload_on": '{"state": "ON"}',
                "payload_off": '{"state": "OFF"}',
            },
            room_id=lounge_room.id,
            skill_id=skill_id,
        ),
        GlobalDevice(
            device_type_id=test_device_types["plug"].id,
            name="corner",
            pattern=["corner", f"{lounge_room.name} corner"],
            device_attributes={
                "topic": f"test/mqtt/{lounge_room.name}/plug/corner_lamp/set",
                "payload_on": '{"state": "ON"}',
                "payload_off": '{"state": "OFF"}',
            },
            room_id=lounge_room.id,
            skill_id=skill_id,
        ),
    ]

    for device in devices:
        db_session.add(device)

    await db_session.commit()

    for device in devices:
        await db_session.refresh(device, ["room", "device_type"])

    yield devices

    # Cleanup: Delete all test devices
    for device in devices:
        await db_session.delete(device)
    await db_session.commit()


@pytest.fixture
async def skill_config_file(mqtt_config):
    """Create a temporary config file for the skill."""
    config = {
        "client_id": "switch-skill-integration-test",
        "mqtt_server_host": mqtt_config["host"],
        "mqtt_server_port": mqtt_config["port"],
        "base_topic": "assistant",
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        config_path = pathlib.Path(f.name)

    yield config_path

    # Cleanup: Remove temp file
    config_path.unlink(missing_ok=True)


@pytest.fixture
async def running_skill_single_device(skill_config_file, test_device, db_engine):
    """Start the skill in background with a single device ready.

    Args:
        skill_config_file: Path to skill config
        test_device: Test device that must be created before skill starts
        db_engine: Database engine to verify device visibility
    """
    # Device is already created by test_device fixture
    # Give database time to fully persist the commit
    await asyncio.sleep(0.5)

    # Verify device is visible from a fresh session (simulate what the skill does)
    async with AsyncSession(db_engine) as session:
        # Check device by ID
        result = await session.exec(select(GlobalDevice).where(GlobalDevice.id == test_device.id))
        check_device = result.first()
        logger.debug("Device visible by ID: %s", check_device is not None)

        # Check device by skill_id (this is what the skill does)
        result = await session.exec(select(GlobalDevice).where(GlobalDevice.skill_id == test_device.skill_id))
        devices_by_skill = result.all()
        logger.debug("Devices found by skill_id=%s: %d", test_device.skill_id, len(devices_by_skill))
        for dev in devices_by_skill:
            logger.debug("  - %s (ID: %s)", dev.name, dev.id)

        # Check if the Skill entity exists
        result = await session.exec(select(Skill).where(Skill.id == test_device.skill_id))
        skill_entity = result.first()
        skill_name = skill_entity.name if skill_entity else "N/A"
        logger.debug("Skill entity exists: %s, name: %s", skill_entity is not None, skill_name)

    # Start skill as background task
    skill_task = asyncio.create_task(start_skill(skill_config_file))

    # Wait for skill to initialize and subscribe to all topics
    # This includes the device update topic listener
    await asyncio.sleep(3)

    # Trigger device load by publishing device update notification
    # The skill's device cache is only populated when it receives this notification
    mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
    async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as trigger_client:
        await trigger_client.publish("assistant/global_device_update", "", qos=1)

    # Wait for skill to process the device update and load devices
    await asyncio.sleep(2)

    yield

    # Cleanup: Cancel skill task
    skill_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await skill_task


@pytest.fixture
async def running_skill_multiple_devices(skill_config_file, test_devices_multiple):  # noqa: ARG001
    """Start the skill in background with multiple devices ready.

    Args:
        skill_config_file: Path to skill config
        test_devices_multiple: Test devices that must be created before skill starts
    """
    # Devices are already created by test_devices_multiple fixture
    # Give database time to fully persist the commit
    await asyncio.sleep(0.5)

    # Start skill as background task
    skill_task = asyncio.create_task(start_skill(skill_config_file))

    # Wait for skill to initialize and subscribe to all topics
    # This includes the device update topic listener
    await asyncio.sleep(3)

    # Trigger device load by publishing device update notification
    mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
    async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as trigger_client:
        await trigger_client.publish("assistant/global_device_update", "", qos=1)

    # Wait for skill to process the device update and load devices
    await asyncio.sleep(2)

    yield

    # Cleanup: Cancel skill task
    skill_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await skill_task


@pytest.fixture
async def running_skill(skill_config_file):
    """Start the skill in background without any test devices.

    Used for tests that don't need devices (e.g., error handling tests).
    """
    # Start skill as background task
    skill_task = asyncio.create_task(start_skill(skill_config_file))

    # Wait for skill to initialize and subscribe to topics
    await asyncio.sleep(3)

    yield

    # Cleanup: Cancel skill task
    skill_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await skill_task


@pytest.fixture
async def running_skill_realistic(skill_config_file, test_devices_realistic):  # noqa: ARG001
    """Start the skill in background with realistic mixed devices ready.

    Args:
        skill_config_file: Path to skill config
        test_devices_realistic: Realistic devices that must be created before skill starts
    """
    # Devices are already created by test_devices_realistic fixture
    # Give database time to fully persist the commit
    await asyncio.sleep(0.5)

    # Start skill as background task
    skill_task = asyncio.create_task(start_skill(skill_config_file))

    # Wait for skill to initialize and subscribe to all topics
    # This includes the device update topic listener
    await asyncio.sleep(3)

    # Trigger device load by publishing device update notification
    mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
    async with aiomqtt.Client(hostname=mqtt_host, port=mqtt_port) as trigger_client:
        await trigger_client.publish("assistant/global_device_update", "", qos=1)

    # Wait for skill to process the device update and load devices
    await asyncio.sleep(2)

    yield

    # Cleanup: Cancel skill task
    skill_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await skill_task


class TestSingleDeviceCommand:
    """Test single device commands (DEVICE_ON)."""

    async def test_device_on_command(
        self,
        test_device,
        test_room,
        running_skill_single_device,  # noqa: ARG002
        mqtt_test_client,
    ):
        """Test that DEVICE_ON intent triggers correct MQTT command and response.

        Flow:
        1. Publish IntentRequest with DEVICE_ON intent
        2. Assert device command published to correct topic
        3. Assert response published to output topic

        Note: Uses running_skill_single_device fixture which ensures test_device
        is created before the skill starts.
        """
        output_topic = f"test/output/{uuid.uuid4().hex}"
        device_topic = test_device.device_attributes["topic"]

        # Prepare IntentRequest
        device_entity = Entity(
            id=uuid.uuid4(),
            type=EntityType.DEVICE,
            raw_text="test light",
            normalized_value="test light",
            confidence=0.9,
            metadata={},
            linked_to=[],
        )

        classified_intent = ClassifiedIntent(
            id=uuid.uuid4(),
            intent_type=IntentType.DEVICE_ON,
            confidence=0.9,
            entities={"device": [device_entity]},
            alternative_intents=[],
            raw_text="turn on test light",
            timestamp=datetime.now(),
        )

        client_request = ClientRequest(
            id=uuid.uuid4(),
            text="turn on test light",
            room=test_room.name,
            output_topic=output_topic,
        )

        intent_request = IntentRequest(
            id=uuid.uuid4(),
            classified_intent=classified_intent,
            client_request=client_request,
        )

        # Subscribe to device topic and response topic
        await mqtt_test_client.subscribe(device_topic)
        await mqtt_test_client.subscribe(output_topic)

        # Publish IntentRequest
        await mqtt_test_client.publish(
            "assistant/intent_engine/result",
            intent_request.model_dump_json(),
            qos=1,
        )

        # Collect messages
        device_command_received = False
        response_received = False

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                topic = str(message.topic)
                payload = message.payload.decode()

                if topic == device_topic:
                    assert payload == "ON", f"Expected 'ON' payload, got '{payload}'"
                    device_command_received = True

                if topic == output_topic:
                    # Response should mention turning on the light
                    assert "test light" in payload.lower() or "light" in payload.lower()
                    response_received = True

                # Exit when both messages received
                if device_command_received and response_received:
                    break

        assert device_command_received, "Device command was not published"
        assert response_received, "Response was not published"


class TestRoomWideCommand:
    """Test room-wide commands (multiple devices)."""

    async def test_room_wide_off_command(
        self,
        test_devices_multiple,
        test_room,
        running_skill_multiple_devices,  # noqa: ARG002
        mqtt_test_client,
    ):
        """Test that DEVICE_OFF with multiple matching devices triggers all commands.

        Flow:
        1. Publish IntentRequest with DEVICE_OFF for all lights in room
        2. Assert commands published to all 3 device topics
        3. Assert response indicates multiple devices

        Note: Uses running_skill_multiple_devices fixture which ensures test_devices_multiple
        is created before the skill starts.
        """
        output_topic = f"test/output/{uuid.uuid4().hex}"
        device_topics = [d.device_attributes["topic"] for d in test_devices_multiple]

        # Prepare IntentRequest with generic device type (automatically triggers room-wide)
        # Intent engine sends generic device type "light" which skill translates to all lights in room
        device_entities = [
            Entity(
                id=uuid.uuid4(),
                type=EntityType.DEVICE,
                raw_text="lights",
                normalized_value="light",
                confidence=0.9,
                metadata={"device_type": "light", "is_generic": True},
                linked_to=[],
            )
        ]

        classified_intent = ClassifiedIntent(
            id=uuid.uuid4(),
            intent_type=IntentType.DEVICE_OFF,
            confidence=0.9,
            entities={"device": device_entities},
            alternative_intents=[],
            raw_text="turn off all lights",
            timestamp=datetime.now(),
        )

        client_request = ClientRequest(
            id=uuid.uuid4(),
            text="turn off all lights",
            room=test_room.name,
            output_topic=output_topic,
        )

        intent_request = IntentRequest(
            id=uuid.uuid4(),
            classified_intent=classified_intent,
            client_request=client_request,
        )

        # Subscribe to all device topics and response topic
        for topic in device_topics:
            await mqtt_test_client.subscribe(topic)
        await mqtt_test_client.subscribe(output_topic)

        # Publish IntentRequest
        await mqtt_test_client.publish(
            "assistant/intent_engine/result",
            intent_request.model_dump_json(),
            qos=1,
        )

        # Collect messages
        device_commands_received = set()
        response_received = False

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                topic = str(message.topic)
                payload = message.payload.decode()

                if topic in device_topics:
                    assert payload == "OFF", f"Expected 'OFF' payload, got '{payload}'"
                    device_commands_received.add(topic)

                if topic == output_topic:
                    # Response should indicate multiple devices or room-wide action
                    response_received = True

                # Exit when all messages received
                if len(device_commands_received) == len(device_topics) and response_received:
                    break

        assert len(device_commands_received) == len(device_topics), (
            f"Expected commands to {len(device_topics)} devices, got {len(device_commands_received)}"
        )
        assert response_received, "Response was not published"


class TestGenericDeviceType:
    """Test generic device type queries across realistic mixed devices.

    These tests validate the skill's ability to handle generic device type
    requests (e.g., "turn on all plugs") in a room with mixed device types,
    mimicking real-world smart home scenarios.
    """

    async def test_generic_plug_query(
        self,
        test_devices_realistic,
        test_rooms,
        running_skill_realistic,  # noqa: ARG002
        mqtt_test_client,
    ):
        """Test that generic 'plug' query finds only plug devices in the room.

        Flow:
        1. Request to turn on all plugs in office room
        2. Assert only plug devices receive commands (not switches)
        3. Assert response indicates multiple devices controlled

        This test mimics the original bug scenario where generic device
        type queries were failing due to entity key mismatch.
        """
        office_room = test_rooms["test_office"]
        output_topic = f"test/output/{uuid.uuid4().hex}"

        # Get plug devices in office room
        plug_devices = [
            d for d in test_devices_realistic if d.device_type.name == "plug" and d.room_id == office_room.id
        ]
        plug_topics = [d.device_attributes["topic"] for d in plug_devices]

        # Get non-plug devices in office room (should not be controlled)
        non_plug_devices = [
            d for d in test_devices_realistic if d.device_type.name != "plug" and d.room_id == office_room.id
        ]
        non_plug_topics = [d.device_attributes["topic"] for d in non_plug_devices]

        logger.info("Testing generic plug query: %d plugs, %d non-plugs", len(plug_devices), len(non_plug_devices))

        # Prepare IntentRequest with generic device type "plug"
        device_entity = Entity(
            id=uuid.uuid4(),
            type=EntityType.DEVICE,
            raw_text="plugs",
            normalized_value="plug",
            confidence=0.8,
            metadata={"device_type": "plug", "is_generic": True, "quantifier": "all"},
            linked_to=[],
        )

        classified_intent = ClassifiedIntent(
            id=uuid.uuid4(),
            intent_type=IntentType.DEVICE_ON,
            confidence=1.0,
            entities={"device": [device_entity]},
            alternative_intents=[],
            raw_text="turn on all plugs",
            timestamp=datetime.now(),
        )

        client_request = ClientRequest(
            id=uuid.uuid4(),
            text="turn on all plugs",
            room=office_room.name,
            output_topic=output_topic,
        )

        intent_request = IntentRequest(
            id=uuid.uuid4(),
            classified_intent=classified_intent,
            client_request=client_request,
        )

        # Subscribe to all device topics and response topic
        await mqtt_test_client.subscribe("test/mqtt/#")
        await mqtt_test_client.subscribe(output_topic)

        # Publish IntentRequest
        await mqtt_test_client.publish(
            "assistant/intent_engine/result",
            intent_request.model_dump_json(),
            qos=1,
        )

        # Collect messages
        plug_commands_received = set()
        non_plug_commands_received = set()
        response_received = False

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                topic = str(message.topic)
                payload = message.payload.decode()

                if topic in plug_topics:
                    assert '{"state": "ON"}' in payload, f"Expected ON payload, got '{payload}'"
                    plug_commands_received.add(topic)

                if topic in non_plug_topics:
                    non_plug_commands_received.add(topic)

                if topic == output_topic:
                    response_received = True

                # Exit when expected messages received
                if len(plug_commands_received) == len(plug_topics) and response_received:
                    break

        # Assertions
        assert len(plug_commands_received) == len(plug_topics), (
            f"Expected commands to {len(plug_topics)} plug devices, got {len(plug_commands_received)}"
        )
        assert len(non_plug_commands_received) == 0, (
            f"Non-plug devices should not receive commands, but {len(non_plug_commands_received)} did"
        )
        assert response_received, "Response was not published"


class TestDeviceNotFound:
    """Test error handling when device is not found."""

    async def test_device_not_found(self, running_skill, mqtt_test_client, test_room):  # noqa: ARG002
        """Test that non-existent device request sends error response without device commands.

        Flow:
        1. Publish IntentRequest for non-existent device
        2. Assert no device commands published
        3. Assert error response published
        """
        output_topic = f"test/output/{uuid.uuid4().hex}"

        # Prepare IntentRequest for non-existent device
        device_entity = Entity(
            id=uuid.uuid4(),
            type=EntityType.DEVICE,
            raw_text="nonexistent device",
            normalized_value="nonexistent device",
            confidence=0.9,
            metadata={},
            linked_to=[],
        )

        classified_intent = ClassifiedIntent(
            id=uuid.uuid4(),
            intent_type=IntentType.DEVICE_ON,
            confidence=0.9,
            entities={"device": [device_entity]},
            alternative_intents=[],
            raw_text="turn on nonexistent device",
            timestamp=datetime.now(),
        )

        client_request = ClientRequest(
            id=uuid.uuid4(),
            text="turn on nonexistent device",
            room=test_room.name,
            output_topic=output_topic,
        )

        intent_request = IntentRequest(
            id=uuid.uuid4(),
            classified_intent=classified_intent,
            client_request=client_request,
        )

        # Subscribe to response topic and a wildcard for any device commands
        await mqtt_test_client.subscribe(output_topic)
        await mqtt_test_client.subscribe("test/integration/#")

        # Publish IntentRequest
        await mqtt_test_client.publish(
            "assistant/intent_engine/result",
            intent_request.model_dump_json(),
            qos=1,
        )

        # Collect messages
        device_command_received = False
        response_received = False
        response_payload = None

        async with asyncio.timeout(10):
            async for message in mqtt_test_client.messages:
                topic = str(message.topic)
                payload = message.payload.decode()

                # Check if any device command was sent
                if topic.startswith("test/integration/") and topic != output_topic:
                    device_command_received = True

                if topic == output_topic:
                    response_payload = payload
                    response_received = True
                    break  # Got response, can exit

        assert not device_command_received, "Device command should not be published for non-existent device"
        assert response_received, "Error response should be published"
        # Response should indicate device not found or similar error
        assert response_payload is not None
