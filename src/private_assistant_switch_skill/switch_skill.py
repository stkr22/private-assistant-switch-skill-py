import logging
import string
from enum import Enum

import homeassistant_api as ha_api
import jinja2
import paho.mqtt.client as mqtt
import private_assistant_commons as commons
from private_assistant_commons import messages
from pydantic import BaseModel

from private_assistant_switch_skill.config import SkillConfig

logger = logging.getLogger(__name__)


class Parameters(BaseModel):
    targets: list[str] = []


class Action(Enum):
    HELP = ["help"]
    ON = ["on"]
    OFF = ["off"]
    LIST = ["list"]

    @classmethod
    def find_matching_action(cls, text: str):
        text = text.translate(str.maketrans("", "", string.punctuation))
        text_words = set(text.lower().split())
        for action in cls:
            if all(word in text_words for word in action.value):
                return action
        return None


class SwitchSkill(commons.BaseSkill):
    def __init__(
        self,
        config_obj: SkillConfig,
        mqtt_client: mqtt.Client,
        ha_api_client: ha_api.Client,
        template_env: jinja2.Environment,
    ) -> None:
        super().__init__(config_obj, mqtt_client)
        self.ha_api_client: ha_api.Client = ha_api_client
        self.template_env: jinja2.Environment = template_env
        self.action_to_answer: dict[Action, jinja2.Template] = {
            Action.HELP: template_env.get_template("help.j2"),
            Action.ON: template_env.get_template("state.j2"),
            Action.OFF: template_env.get_template("state.j2"),
            Action.LIST: template_env.get_template("list.j2"),
        }
        self._target_cache: dict[str, ha_api.State] = {}
        self._target_alias_cache: dict[str, str] = {}

    @property
    def target_cache(self) -> dict[str, ha_api.State]:
        if len(self._target_cache) < 1:
            self._target_cache = self.get_targets()
        return self._target_cache

    @property
    def target_alias_cache(self) -> dict[str, str]:
        if len(self._target_alias_cache) < 1:
            for target in self.target_cache.values():
                alias = target.attributes.get("friendly_name", "no name").lower()
                self._target_alias_cache[target.entity_id] = alias
        return self._target_alias_cache

    def calculate_certainty(self, intent_analysis_result: messages.IntentAnalysisResult) -> float:
        if ["switch"] in intent_analysis_result.verbs:
            return 1.0
        return 0

    def get_targets(self) -> dict[str, ha_api.State]:
        entity_groups = self.ha_api_client.get_entities()
        room_entities = {entity_name: entity.state for entity_name, entity in entity_groups["light"].entities.items()}
        room_entities |= {
            entity_name: entity.state
            for entity_name, entity in entity_groups["switch"].entities.items()
            if "plug" in entity_name.lower()
        }
        return room_entities

    def find_parameter_targets(self, intent_analysis_result: messages.IntentAnalysisResult) -> list[str]:
        targets = []
        room = intent_analysis_result.client_request.room
        if "completely" in intent_analysis_result.client_request.text.lower():
            return [target for target in self.target_alias_cache.keys() if room in target]
        for target, alias in self.target_alias_cache.items():
            if alias in intent_analysis_result.nouns and room in target:
                targets.append(target)
        if len(targets) < 1:
            for target, alias in self.target_alias_cache.items():
                if alias in intent_analysis_result.nouns:
                    targets.append(target)
        return targets

    def find_parameters(self, action: Action, intent_analysis_result: messages.IntentAnalysisResult) -> Parameters:
        parameters = Parameters()
        if action == Action.LIST:
            parameters.targets = [
                target
                for target in self.target_alias_cache.keys()
                if intent_analysis_result.client_request.room in target
            ]
        if action in [Action.ON, Action.OFF]:
            found_targets = self.find_parameter_targets(intent_analysis_result=intent_analysis_result)
            if len(found_targets) > 0:
                parameters.targets = found_targets
        return parameters

    def get_answer(self, action: Action, parameters: Parameters) -> str:
        template = self.action_to_answer[action]
        answer = template.render(
            action=action,
            parameters=parameters,
            target_alias_cache=self.target_alias_cache,
        )
        return answer

    def call_action_api(self, action: Action, parameters: Parameters) -> None:
        for target in parameters.targets:
            if "switch" in target:
                service = self.ha_api_client.get_domain("switch")
            else:
                service = self.ha_api_client.get_domain("light")
            if service is None:
                logger.error("Service is None.")
                continue
            if action == Action.ON:
                service.turn_on(entity_id=target)
            elif action == Action.OFF:
                service.turn_off(entity_id=target)
            else:
                continue

    def process_request(self, intent_analysis_result: messages.IntentAnalysisResult) -> None:
        action = Action.find_matching_action(intent_analysis_result.client_request.text)
        parameters = None
        if action is not None:
            parameters = self.find_parameters(action, intent_analysis_result=intent_analysis_result)
        if parameters is not None and action is not None:
            answer = self.get_answer(action, parameters)
            self.add_text_to_output_topic(answer, client_request=intent_analysis_result.client_request)
            if action not in [Action.HELP, Action.LIST]:
                self.call_action_api(action, parameters)
