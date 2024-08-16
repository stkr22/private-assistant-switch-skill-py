import unittest
from unittest.mock import Mock, patch

import jinja2
from homeassistant_api import Entity, Group, State
from private_assistant_commons import messages
from private_assistant_switch_skill.switch_skill import Action, Parameters, SwitchSkill


class TestSwitchSkill(unittest.TestCase):
    def setUp(self):
        self.mock_mqtt_client = Mock()
        self.mock_config = Mock()
        self.mock_ha_api_client = Mock()
        self.mock_template_env = Mock(spec=jinja2.Environment)

        self.skill = SwitchSkill(
            config_obj=self.mock_config,
            mqtt_client=self.mock_mqtt_client,
            ha_api_client=self.mock_ha_api_client,
            template_env=self.mock_template_env,
        )

    def test_calculate_certainty_with_switch(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.verbs = ["switch"]
        certainty = self.skill.calculate_certainty(mock_intent_result)
        self.assertEqual(certainty, 1.0)

    def test_calculate_certainty_without_switch(self):
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.verbs = ["toggle"]
        certainty = self.skill.calculate_certainty(mock_intent_result)
        self.assertEqual(certainty, 0)

    def test_get_targets(self):
        mock_state = Mock(spec=State)
        mock_state.state = "on"
        mock_state.attributes = {"friendly_name": "Living Room Light"}

        mock_entity = Mock(spec=Entity)
        mock_entity.state = mock_state

        mock_group = Mock(spec=Group)
        mock_group.entities = {"entity_id_1": mock_entity}

        self.skill.ha_api_client.get_entities.return_value = {"light": mock_group, "switch": mock_group}

        targets = self.skill.get_targets()

        self.assertIn("entity_id_1", targets)
        self.assertEqual(targets["entity_id_1"], mock_state)

    def test_find_parameter_targets(self):
        self.skill._target_alias_cache = {
            "livingroom/light/main": "main",
            "kitchen/plug/main": "kitchen plug",
            "bedroom/switch/main": "bedroom switch",
        }
        mock_intent_result = Mock()
        mock_intent_result.client_request.room = "livingroom"
        mock_intent_result.client_request.text = "switch on the main light"
        mock_intent_result.nouns = ["light", "main"]

        targets = self.skill.find_parameter_targets(mock_intent_result)
        self.assertEqual(targets, ["livingroom/light/main"])

    def test_get_answer(self):
        mock_template = Mock()
        mock_template.render.return_value = "Turning on the living room light"
        self.skill.action_to_answer = {Action.ON: mock_template, Action.OFF: mock_template, Action.LIST: mock_template}

        mock_state = Mock(spec=State)
        mock_state.entity_id = "livingroom/light/main"
        mock_state.state = "on"
        mock_state.attributes = {"friendly_name": "Living Room Light"}

        mock_entity = Mock(spec=Entity)
        mock_entity.state = mock_state

        mock_group = Mock(spec=Group)
        mock_group.entities = {"entity_id_1": mock_entity}

        self.skill.ha_api_client.get_entities.return_value = {"light": mock_group, "switch": mock_group}

        _ = self.skill.target_alias_cache

        mock_parameters = Parameters(targets=["livingroom/light/main"])
        answer = self.skill.get_answer(Action.ON, mock_parameters)
        self.assertEqual(answer, "Turning on the living room light")
        mock_template.render.assert_called_once_with(
            action=Action.ON, parameters=mock_parameters, target_alias_cache=self.skill.target_alias_cache
        )

    @patch("private_assistant_switch_skill.switch_skill.logger")
    def test_call_action_api(self, mock_logger):
        mock_service = Mock()
        self.skill.ha_api_client.get_domain.return_value = mock_service

        parameters = Parameters(targets=["livingroom/light/main"])
        self.skill.call_action_api(Action.ON, parameters)

        mock_service.turn_on.assert_called_once_with(entity_id="livingroom/light/main")
        mock_logger.error.assert_not_called()

    def test_process_request_with_valid_action(self):
        # Mock the client request
        mock_client_request = Mock()
        mock_client_request.room = "livingroom"
        mock_client_request.text = "turn on the light"

        # Mock the IntentAnalysisResult
        mock_intent_result = Mock(spec=messages.IntentAnalysisResult)
        mock_intent_result.client_request = mock_client_request
        mock_intent_result.verbs = ["on"]
        mock_intent_result.nouns = ["light"]

        # Set up mock parameters and method patches
        mock_parameters = Parameters(targets=["livingroom/light/main"])

        with (
            patch.object(self.skill, "get_answer", return_value="Turning on the living room light") as mock_get_answer,
            patch.object(self.skill, "call_action_api") as mock_call_action_api,
            patch.object(self.skill, "find_parameter_targets", return_value=["livingroom/light/main"]),
            patch.object(self.skill, "add_text_to_output_topic") as mock_add_text_to_output_topic,
        ):
            # Execute the process_request method
            self.skill.process_request(mock_intent_result)

            # Assert that methods were called with expected arguments
            mock_get_answer.assert_called_once_with(Action.ON, mock_parameters)
            mock_call_action_api.assert_called_once_with(Action.ON, mock_parameters)
            mock_add_text_to_output_topic.assert_called_once_with(
                "Turning on the living room light", client_request=mock_intent_result.client_request
            )
