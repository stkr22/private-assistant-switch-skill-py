import logging
import unittest
from unittest.mock import AsyncMock, Mock, patch

import jinja2
from private_assistant_commons import messages
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from private_assistant_switch_skill import models
from private_assistant_switch_skill.switch_skill import Action, Parameters, SwitchSkill


class TestSwitchSkill(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Set up an in-memory SQLite database for async usage
        cls.engine_async = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async def asyncSetUp(self):
        # Create a new mock session for each test
        self.mock_session = AsyncMock(spec=AsyncSession)
        self.mock_mqtt_client = AsyncMock()
        self.mock_config = Mock()
        self.mock_template_env = Mock(spec=jinja2.Environment)
        self.mock_task_group = AsyncMock()
        self.mock_logger = Mock(logging.Logger)

        # Create an instance of SwitchSkill using the in-memory DB and mocked dependencies
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
        # Clean up operations after each test
        async with self.engine_async.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await self.mock_session.close()

    async def test_get_devices(self):
        # Insert a mock device into the in-memory SQLite database
        mock_device = models.SwitchSkillDevice(
            topic="livingroom/light/main",
            alias="main light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )
        async with AsyncSession(self.engine_async) as session:
            async with session.begin():
                session.add(mock_device)

        # Fetch devices for the "livingroom"
        devices = await self.skill.get_devices("livingroom")

        # Assert that the correct device is returned
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].alias, "main light")
        self.assertEqual(devices[0].topic, "livingroom/light/main")

    async def test_find_parameters(self):
        # Insert a mock device into the in-memory SQLite database
        mock_device = models.SwitchSkillDevice(
            topic="livingroom/light/main", alias="main light", room="livingroom", payload_on="ON", payload_off="OFF"
        )
        async with AsyncSession(self.engine_async) as session:
            async with session.begin():
                session.add(mock_device)

        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_client_request = Mock()
        mock_client_request.room = "livingroom"
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.nouns = ["main light"]

        parameters = await self.skill.find_parameters(Action.ON, mock_intent_result)

        # Assert that the correct device is in the parameters
        self.assertEqual(len(parameters.targets), 1)
        self.assertEqual(parameters.targets[0].alias, "main light")

    async def test_calculate_certainty_with_switch(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.verbs = ["switch"]
        certainty = await self.skill.calculate_certainty(mock_intent_result)
        self.assertEqual(certainty, 1.0)

    async def test_calculate_certainty_without_switch(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.verbs = ["toggle"]
        certainty = await self.skill.calculate_certainty(mock_intent_result)
        self.assertEqual(certainty, 0)

    async def test_send_mqtt_command(self):
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="main light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )

        parameters = Parameters(targets=[mock_device])

        # Call the method to send the MQTT command
        await self.skill.send_mqtt_command(Action.ON, parameters)

        # Assert that the MQTT client sent the correct payload to the correct topic
        self.mock_mqtt_client.publish.assert_called_once_with("livingroom/light/main", "ON", qos=1)
        self.mock_logger.info.assert_called_with(
            "Sending payload %s to topic %s via MQTT.", "ON", "livingroom/light/main"
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

        mock_client_request = Mock()
        mock_client_request.room = "livingroom"
        mock_client_request.text = "switch on the light"

        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.verbs = ["switch", "on"]
        mock_intent_result.nouns = ["light"]

        mock_parameters = Parameters(targets=[mock_device])

        with (
            patch.object(self.skill, "get_answer", return_value="Turning on the livingroom light") as mock_get_answer,
            patch.object(self.skill, "send_mqtt_command") as mock_send_mqtt_command,
            patch.object(self.skill, "find_parameters", return_value=mock_parameters),
            patch.object(self.skill, "send_response") as mock_send_response,
        ):
            await self.skill.process_request(mock_intent_result)

            # Assert that methods were called with expected arguments
            mock_get_answer.assert_called_once_with(Action.ON, mock_parameters)
            mock_send_mqtt_command.assert_called_once_with(Action.ON, mock_parameters)
            mock_send_response.assert_called_once_with(
                "Turning on the livingroom light", client_request=mock_intent_result.client_request
            )

    async def test_get_answer(self):
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )
        mock_template = Mock()
        mock_template.render.return_value = "Turning on the living room light"
        self.skill.action_to_answer = {Action.ON: mock_template, Action.OFF: mock_template, Action.LIST: mock_template}

        mock_parameters = Parameters(targets=[mock_device])

        answer = self.skill.get_answer(Action.ON, mock_parameters)
        self.assertEqual(answer, "Turning on the living room light")
        mock_template.render.assert_called_once_with(action=Action.ON, parameters=mock_parameters)
