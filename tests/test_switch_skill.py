import unittest
from unittest.mock import Mock, patch

import jinja2  # Import Jinja2
import sqlmodel
from private_assistant_commons import messages

from private_assistant_switch_skill import models
from private_assistant_switch_skill.switch_skill import Action, Parameters, SwitchSkill


class TestSwitchSkill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Set up an in-memory SQLite database
        cls.engine = sqlmodel.create_engine("sqlite:///:memory:", echo=False)
        sqlmodel.SQLModel.metadata.create_all(cls.engine)

    def setUp(self):
        # Create a new session for each test
        self.session = sqlmodel.Session(self.engine)

        # Mock the MQTT client and other dependencies
        self.mock_mqtt_client = Mock()
        self.mock_config = Mock()
        self.mock_template_env = Mock(spec=jinja2.Environment)  # Correct mock with spec

        # Create an instance of SwitchSkill using the in-memory DB and mocked dependencies
        self.skill = SwitchSkill(
            config_obj=self.mock_config,
            mqtt_client=self.mock_mqtt_client,
            db_engine=self.engine,
            template_env=self.mock_template_env,
        )

    def tearDown(self):
        # Clean up the session after each test
        self.session.close()

    def test_get_devices(self):
        # Insert a mock device into the in-memory SQLite database
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="main light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )
        mock_device_two = models.SwitchSkillDevice(
            id=2,
            topic="livingroom/light/shelf",
            alias="main shelf",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )
        with self.session as session:
            session.add(mock_device)
            session.add(mock_device_two)
            session.commit()

        # Fetch devices for the "livingroom"
        devices = self.skill.get_devices("livingroom")

        # Assert that the correct device is returned
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].alias, "main light")
        self.assertEqual(devices[0].topic, "livingroom/light/main")

    def test_find_parameters(self):
        # Insert a mock device into the in-memory SQLite database
        mock_device = models.SwitchSkillDevice(
            topic="livingroom/light/main", alias="main light", room="livingroom", payload_on="ON", payload_off="OFF"
        )
        mock_device_two = models.SwitchSkillDevice(
            topic="livingroom/light/shelf", alias="main shelf", room="livingroom", payload_on="ON", payload_off="OFF"
        )

        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)

        # Create a mock for the `client_request` attribute
        mock_client_request = Mock()
        mock_client_request.room = "livingroom"
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.nouns = ["main light"]
        with (
            patch.object(self.skill, "get_devices", return_value=[mock_device, mock_device_two]),
        ):
            # Find parameters for turning on the light
            parameters = self.skill.find_parameters(Action.ON, mock_intent_result)

        # Assert that the correct device is in the parameters
        self.assertEqual(len(parameters.targets), 1)
        self.assertEqual(parameters.targets[0].alias, "main light")

    def test_calculate_certainty_with_switch(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)  # Added spec here
        mock_intent_result.verbs = ["switch"]
        certainty = self.skill.calculate_certainty(mock_intent_result)
        self.assertEqual(certainty, 1.0)

    def test_calculate_certainty_without_switch(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)  # Added spec here
        mock_intent_result.verbs = ["toggle"]
        certainty = self.skill.calculate_certainty(mock_intent_result)
        self.assertEqual(certainty, 0)

    @patch("private_assistant_switch_skill.switch_skill.logger")
    def test_send_mqtt_command(self, mock_logger):
        # Create mock device
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="main light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )

        # Mock parameters
        parameters = Parameters(targets=[mock_device])

        # Call the method to send the MQTT command
        self.skill.send_mqtt_command(Action.ON, parameters)

        # Assert that the MQTT client sent the correct payload to the correct topic
        self.mock_mqtt_client.publish.assert_called_once_with("livingroom/light/main", "ON", qos=1)
        mock_logger.info.assert_called_with("Sending payload %s to topic %s via MQTT.", "ON", "livingroom/light/main")

    def test_process_request_with_valid_action(self):
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )
        # Mock the client request
        mock_client_request = Mock()
        mock_client_request.room = "livingroom"
        mock_client_request.text = "switch on the light"

        # Mock the IntentAnalysisResult with spec
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)  # Added spec here
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.verbs = ["switch", "on"]
        mock_intent_result.nouns = ["light"]

        # Set up mock parameters and method patches
        mock_parameters = Parameters(targets=[mock_device])

        with (
            patch.object(self.skill, "get_answer", return_value="Turning on the livingroom light") as mock_get_answer,
            patch.object(self.skill, "send_mqtt_command") as mock_send_mqtt_command,
            patch.object(self.skill, "find_parameters", return_value=mock_parameters),
            patch.object(self.skill, "add_text_to_output_topic") as mock_add_text_to_output_topic,
        ):
            # Execute the process_request method
            self.skill.process_request(mock_intent_result)

            # Assert that methods were called with expected arguments
            mock_get_answer.assert_called_once_with(Action.ON, mock_parameters)
            mock_send_mqtt_command.assert_called_once_with(Action.ON, mock_parameters)
            mock_add_text_to_output_topic.assert_called_once_with(
                "Turning on the livingroom light", client_request=mock_intent_result.client_request
            )

    def test_get_answer(self):
        mock_device = models.SwitchSkillDevice(
            id=1,
            topic="livingroom/light/main",
            alias="light",
            room="livingroom",
            payload_on="ON",
            payload_off="OFF",
        )
        # Mock a template for rendering
        mock_template = Mock()
        mock_template.render.return_value = "Turning on the living room light"
        self.skill.action_to_answer = {Action.ON: mock_template, Action.OFF: mock_template, Action.LIST: mock_template}

        # Mock parameters
        mock_parameters = Parameters(targets=[mock_device])

        # Call the method and assert the answer
        answer = self.skill.get_answer(Action.ON, mock_parameters)
        self.assertEqual(answer, "Turning on the living room light")
        mock_template.render.assert_called_once_with(action=Action.ON, parameters=mock_parameters)
