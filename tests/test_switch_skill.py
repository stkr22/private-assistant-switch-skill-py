import logging
import unittest
from unittest.mock import AsyncMock, Mock, patch

import jinja2
from private_assistant_commons import messages
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from private_assistant_switch_skill import models
from private_assistant_switch_skill.switch_skill import Action, DeviceLocation, Parameters, SwitchSkill


class TestSwitchSkill(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_async = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async def asyncSetUp(self):
        self.mock_session = AsyncMock(spec=AsyncSession)
        self.mock_mqtt_client = AsyncMock()
        self.mock_config = Mock()
        self.mock_template_env = Mock(spec=jinja2.Environment)
        self.mock_task_group = AsyncMock()
        self.mock_logger = Mock(logging.Logger)

        self.skill = SwitchSkill(
            config_obj=self.mock_config,
            mqtt_client=self.mock_mqtt_client,
            db_engine=self.engine_async,
            template_env=self.mock_template_env,
            task_group=self.mock_task_group,
            logger=self.mock_logger,
        )
        async with self.engine_async.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    async def asyncTearDown(self):
        async with self.engine_async.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await self.mock_session.close()

    async def test_get_devices(self):
        mock_device = models.SwitchSkillDevice(
            topic="livingroom/light/main",
            alias="main light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )
        async with AsyncSession(self.engine_async) as session, session.begin():
            session.add(mock_device)

        devices = await self.skill.get_devices_from_room("livingroom")

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].alias, "main light")
        self.assertEqual(devices[0].topic, "livingroom/light/main")

    async def test_find_device_in_all_rooms(self):
        # Add devices in different rooms
        devices = [
            models.SwitchSkillDevice(
                topic="livingroom/light/main",
                alias="main light",
                room="livingroom",
                payload_on="ON",
                payload_off="OFF",
            ),
            models.SwitchSkillDevice(
                topic="bedroom/light/main",
                alias="bedroom light",
                room="bedroom",
                payload_on="ON",
                payload_off="OFF",
            ),
        ]
        async with AsyncSession(self.engine_async) as session, session.begin():
            for device in devices:
                session.add(device)

        # Test finding device in current room
        device_location = await self.skill.find_device_in_all_rooms("main light", "livingroom")
        self.assertIsNotNone(device_location)
        self.assertEqual(device_location.device.alias, "main light")
        self.assertEqual(device_location.found_room, "livingroom")

        # Test finding device in different room
        device_location = await self.skill.find_device_in_all_rooms("bedroom light", "livingroom")
        self.assertIsNotNone(device_location)
        self.assertEqual(device_location.device.alias, "bedroom light")
        self.assertEqual(device_location.found_room, "bedroom")

        # Test device not found
        device_location = await self.skill.find_device_in_all_rooms("nonexistent", "livingroom")
        self.assertIsNone(device_location)

    async def test_find_parameters(self):
        mock_device = models.SwitchSkillDevice(
            topic="livingroom/light/main", alias="main light", room="livingroom", payload_on="ON", payload_off="OFF"
        )
        async with AsyncSession(self.engine_async) as session, session.begin():
            session.add(mock_device)

        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_client_request = Mock()
        mock_client_request.room = "livingroom"
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.nouns = ["main light"]

        parameters = await self.skill.find_parameters(Action.ON, mock_intent_result)

        self.assertEqual(len(parameters.targets), 1)
        self.assertEqual(parameters.targets[0].device.alias, "main light")
        self.assertEqual(parameters.targets[0].found_room, "livingroom")

    async def test_send_mqtt_command(self):
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="main light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )

        device_location = DeviceLocation(device=mock_device, found_room="livingroom")
        parameters = Parameters(targets=[device_location], current_room="livingroom")

        await self.skill.send_mqtt_command(Action.ON, parameters)

        self.mock_mqtt_client.publish.assert_called_once_with("livingroom/light/main", "ON", qos=1)
        self.mock_logger.info.assert_called_with(
            "Sending payload %s to topic %s via MQTT for device in %s.", "ON", "livingroom/light/main", "livingroom"
        )

    async def test_process_request_with_valid_action(self):
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )

        device_location = DeviceLocation(device=mock_device, found_room="livingroom")
        mock_parameters = Parameters(targets=[device_location], current_room="livingroom")

        mock_client_request = Mock()
        mock_client_request.room = "livingroom"
        mock_client_request.text = "switch on the light"

        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.verbs = ["switch", "on"]
        mock_intent_result.nouns = [Mock(text="light")]

        with (
            patch.object(self.skill, "get_answer", return_value="Turning on the livingroom light") as mock_get_answer,
            patch.object(self.skill, "send_mqtt_command") as mock_send_mqtt_command,
            patch.object(self.skill, "find_parameters", return_value=mock_parameters),
            patch.object(self.skill, "send_response") as mock_send_response,
        ):
            await self.skill.process_request(mock_intent_result)

            mock_get_answer.assert_called_once_with(Action.ON, mock_parameters)
            mock_send_mqtt_command.assert_called_once_with(Action.ON, mock_parameters)
            mock_send_response.assert_called_once_with(
                "Turning on the livingroom light", client_request=mock_intent_result.client_request
            )
