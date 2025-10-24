import asyncio
import logging
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import jinja2
from private_assistant_commons import (
    ClassifiedIntent,
    ClientRequest,
    Entity,
    EntityType,
    IntentRequest,
    IntentType,
)
from private_assistant_commons.database.models import GlobalDevice, Room
from sqlalchemy.ext.asyncio import create_async_engine

from private_assistant_switch_skill.switch_skill import (
    SwitchSkill,
    SwitchSkillDependencies,
)


class TestSwitchSkill(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_async = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    def create_mock_global_device(  # noqa: PLR0913
        self,
        device_id: uuid.UUID,
        name: str,
        room_name: str,
        topic: str,
        payload_on: str = "ON",
        payload_off: str = "OFF",
    ) -> Mock:
        """Create a mock GlobalDevice with a mocked Room relationship."""
        # Create mock Room
        mock_room = Mock(spec=Room)
        mock_room.id = uuid.uuid4()
        mock_room.name = room_name

        # Create mock GlobalDevice (avoid SQLAlchemy configuration issues)
        mock_global_device = Mock(spec=GlobalDevice)
        mock_global_device.id = device_id
        mock_global_device.device_type_id = uuid.uuid4()
        mock_global_device.name = name
        mock_global_device.pattern = [name.lower()]
        mock_global_device.device_attributes = {
            "topic": topic,
            "payload_on": payload_on,
            "payload_off": payload_off,
        }
        mock_global_device.room_id = mock_room.id
        mock_global_device.skill_id = uuid.uuid4()

        # Mock the room relationship (eagerly loaded by BaseSkill)
        mock_global_device.room = mock_room

        return mock_global_device

    async def asyncSetUp(self):
        self.mock_mqtt_client = AsyncMock()
        self.mock_config = Mock()
        self.mock_config.client_id = "test_switch_skill"
        self.mock_template_env = Mock(spec=jinja2.Environment)
        self.mock_task_group = AsyncMock()
        self.mock_logger = Mock(logging.Logger)

        dependencies = SwitchSkillDependencies(
            db_engine=self.engine_async,
            template_env=self.mock_template_env,
        )
        self.skill = SwitchSkill(
            config_obj=self.mock_config,
            mqtt_client=self.mock_mqtt_client,
            dependencies=dependencies,
            task_group=self.mock_task_group,
            logger=self.mock_logger,
        )

        # Mock add_task to return actual asyncio.Task objects for proper concurrent testing
        self.skill.add_task = lambda coro, name=None, **_: asyncio.create_task(coro, name=name)

        # Mock device registry methods (BaseSkill methods)
        self.skill.register_device = AsyncMock()
        self.skill.ensure_device_types_registered = AsyncMock()
        self.skill.ensure_skill_registered = AsyncMock()
        self.skill.publish_device_update = AsyncMock()

        # Initialize global_devices as empty list (tests will populate)
        self.skill.global_devices = []

    async def asyncTearDown(self):
        pass  # No database cleanup needed

    async def test_find_device_in_all_rooms(self):
        # Create mock GlobalDevices in different rooms
        living_room_device = self.create_mock_global_device(
            device_id=uuid.uuid4(),
            name="main light",
            room_name="living room",
            topic="livingroom/light/main",
        )
        bedroom_device = self.create_mock_global_device(
            device_id=uuid.uuid4(),
            name="bedroom light",
            room_name="bedroom",
            topic="bedroom/light/main",
        )

        # Set global_devices on skill
        self.skill.global_devices = [living_room_device, bedroom_device]

        # Test finding device in current room
        device_location = await self.skill.find_device_in_all_rooms("main light", "living room")
        self.assertIsNotNone(device_location)
        self.assertEqual(device_location.device.alias, "main light")
        self.assertEqual(device_location.found_room, "living room")

        # Test finding device in different room
        device_location = await self.skill.find_device_in_all_rooms("bedroom light", "living room")
        self.assertIsNotNone(device_location)
        self.assertEqual(device_location.device.alias, "bedroom light")
        self.assertEqual(device_location.found_room, "bedroom")

        # Test device not found
        device_location = await self.skill.find_device_in_all_rooms("nonexistent", "living room")
        self.assertIsNone(device_location)

    async def test_extract_devices_from_entities(self):
        # Create mock GlobalDevice
        mock_global_device = self.create_mock_global_device(
            device_id=uuid.uuid4(),
            name="main light",
            room_name="living room",
            topic="livingroom/light/main",
        )

        # Set global_devices on skill
        self.skill.global_devices = [mock_global_device]

        # Create mock classified intent with device entities
        device_entity = Entity(
            id=uuid.uuid4(),
            type=EntityType.DEVICE,
            raw_text="main light",
            normalized_value="main light",
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
            raw_text="turn on the main light",
            timestamp=datetime.now(),
        )

        targets = await self.skill._extract_devices_from_entities(classified_intent, "living room")

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].device.alias, "main light")
        self.assertEqual(targets[0].found_room, "living room")

    async def test_process_request_with_device_on(self):
        # Create mock GlobalDevice
        mock_global_device = self.create_mock_global_device(
            device_id=uuid.uuid4(),
            name="main light",
            room_name="living room",
            topic="livingroom/light/main",
        )

        # Set global_devices on skill
        self.skill.global_devices = [mock_global_device]

        # Create IntentRequest with DEVICE_ON intent
        device_entity = Entity(
            id=uuid.uuid4(),
            type=EntityType.DEVICE,
            raw_text="main light",
            normalized_value="main light",
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
            raw_text="turn on the main light",
            timestamp=datetime.now(),
        )
        client_request = ClientRequest(
            id=uuid.uuid4(),
            text="turn on the main light",
            room="living room",
            output_topic="test/output/topic",
        )
        intent_request = IntentRequest(
            id=uuid.uuid4(),
            classified_intent=classified_intent,
            client_request=client_request,
        )

        with (
            patch.object(self.skill, "_render_response", return_value="Turning on the main light") as mock_render,
            patch.object(self.skill, "add_task") as mock_add_task,
        ):
            await self.skill.process_request(intent_request)

            mock_render.assert_called_once()
            # Verify add_task was called twice: once for send_response, once for _send_mqtt_commands
            check_value = 2
            assert mock_add_task.call_count == check_value
