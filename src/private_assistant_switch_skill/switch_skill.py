import string
from enum import Enum

import jinja2
import paho.mqtt.client as mqtt
import private_assistant_commons as commons
import sqlalchemy
from private_assistant_commons import messages
from private_assistant_commons.skill_logger import SkillLogger
from pydantic import BaseModel
from sqlmodel import Session, select

from private_assistant_switch_skill.models import Device  # Import the Device model from models.py

logger = SkillLogger.get_logger(__name__)


class Parameters(BaseModel):
    targets: list[Device] = []


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
        config_obj: commons.SkillConfig,
        mqtt_client: mqtt.Client,
        db_engine: sqlalchemy.Engine,
        template_env: jinja2.Environment,
    ) -> None:
        super().__init__(config_obj, mqtt_client)
        self.db_engine = db_engine
        self.template_env = template_env
        self._device_cache: dict[str, list[Device]] = {}  # Cache devices by room
        self.action_to_answer: dict[Action, jinja2.Template] = {}

        # Preload templates
        try:
            self.action_to_answer[Action.HELP] = self.template_env.get_template("help.j2")
            self.action_to_answer[Action.ON] = self.template_env.get_template("state.j2")
            self.action_to_answer[Action.OFF] = self.template_env.get_template("state.j2")
            self.action_to_answer[Action.LIST] = self.template_env.get_template("list.j2")
            logger.debug("Templates successfully loaded during initialization.")
        except jinja2.TemplateNotFound as e:
            logger.error("Failed to load template: %s", e, exc_info=True)

    @property
    def device_cache(self) -> dict[str, list[Device]]:
        """Lazy-loaded cache for devices."""
        if not self._device_cache:
            logger.debug("Loading devices into cache.")
            try:
                with Session(self.db_engine) as session:
                    statement = select(Device)
                    devices = session.exec(statement).all()
                    for device in devices:
                        if device.room not in self._device_cache:
                            self._device_cache[device.room] = []
                        self._device_cache[device.room].append(device)
            except Exception as e:
                logger.error("Error loading devices into cache: %s", e, exc_info=True)
        return self._device_cache

    def get_devices(self, room: str) -> list[Device]:
        """Return devices for a specific room, using cache."""
        logger.info("Fetching devices for room: %s", room)
        return self.device_cache.get(room, [])

    def calculate_certainty(self, intent_analysis_result: messages.IntentAnalysisResult) -> float:
        if "switch" in intent_analysis_result.verbs:
            logger.debug("Switch verb detected, certainty set to 1.0.")
            return 1.0
        logger.debug("No switch verb detected, certainty set to 0.")
        return 0

    def find_parameters(self, action: Action, intent_analysis_result: messages.IntentAnalysisResult) -> Parameters:
        parameters = Parameters()
        room = intent_analysis_result.client_request.room
        devices = self.get_devices(room)
        if action == Action.LIST:
            parameters.targets = devices
        elif action in [Action.ON, Action.OFF]:
            targets = [device for device in devices if device.alias in intent_analysis_result.nouns]
            parameters.targets = targets
        logger.debug("Parameters found for action %s: %s", action, parameters.targets)
        return parameters

    def get_answer(self, action: Action, parameters: Parameters) -> str:
        template = self.action_to_answer.get(action)
        if template:
            answer = template.render(
                action=action,
                parameters=parameters,
            )
            logger.debug("Generated answer using template for action %s.", action)
            return answer
        else:
            logger.error("No template found for action %s.", action)
            return "Sorry, I couldn't process your request."

    def send_mqtt_command(self, action: Action, parameters: Parameters) -> None:
        for device in parameters.targets:
            payload = device.payload_on if action == Action.ON else device.payload_off
            logger.info("Sending payload %s to topic %s via MQTT.", payload, device.topic)
            try:
                self.mqtt_client.publish(device.topic, payload)
            except Exception as e:
                logger.error("Failed to send MQTT message to topic %s: %s", device.topic, e, exc_info=True)

    def process_request(self, intent_analysis_result: messages.IntentAnalysisResult) -> None:
        action = Action.find_matching_action(intent_analysis_result.client_request.text)
        if action is None:
            logger.error("Unrecognized action in verbs: %s", intent_analysis_result.verbs)
            return

        parameters = self.find_parameters(action, intent_analysis_result)
        if parameters.targets:
            answer = self.get_answer(action, parameters)
            self.add_text_to_output_topic(answer, client_request=intent_analysis_result.client_request)
            if action not in [Action.HELP, Action.LIST]:
                self.send_mqtt_command(action, parameters)
        else:
            logger.error("No targets found for action %s.", action)
