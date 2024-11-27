import asyncio
import logging
import string
from enum import Enum

import aiomqtt
import jinja2
import private_assistant_commons as commons
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from private_assistant_switch_skill.models import SwitchSkillDevice  # Import the Device model from models.py


class Parameters(BaseModel):
    targets: list[SwitchSkillDevice] = []


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
        mqtt_client: aiomqtt.Client,
        db_engine: AsyncEngine,
        template_env: jinja2.Environment,
        task_group: asyncio.TaskGroup,
        logger: logging.Logger,
    ) -> None:
        super().__init__(config_obj=config_obj, mqtt_client=mqtt_client, task_group=task_group, logger=logger)
        self.db_engine = db_engine
        self.template_env = template_env
        self._device_cache: dict[str, list[SwitchSkillDevice]] = {}  # Cache devices by room
        self.action_to_answer: dict[Action, jinja2.Template] = {}

        # Preload templates
        try:
            self.action_to_answer[Action.HELP] = self.template_env.get_template("help.j2")
            self.action_to_answer[Action.ON] = self.template_env.get_template("state.j2")
            self.action_to_answer[Action.OFF] = self.template_env.get_template("state.j2")
            self.action_to_answer[Action.LIST] = self.template_env.get_template("list.j2")
            self.logger.debug("Templates successfully loaded during initialization.")
        except jinja2.TemplateNotFound as e:
            self.logger.error("Failed to load template: %s", e, exc_info=True)

    async def load_device_cache(self) -> None:
        """Asynchronously load devices into the cache."""
        if not self._device_cache:
            self.logger.debug("Loading devices into cache asynchronously.")
            async with AsyncSession(self.db_engine) as session:
                statement = select(SwitchSkillDevice)
                result = await session.exec(statement)
                devices = result.all()
                for device in devices:
                    try:
                        device.model_validate(device)
                        if device.room not in self._device_cache:
                            self._device_cache[device.room] = []
                        self._device_cache[device.room].append(device)
                    except ValidationError as e:
                        self.logger.error("Validation error loading device into cache: %s", e)

    async def get_devices(self, room: str) -> list[SwitchSkillDevice]:
        """Return devices for a specific room, using async cache."""
        if not self._device_cache:
            await self.load_device_cache()
        self.logger.info("Fetching devices for room: %s", room)
        return self._device_cache.get(room, [])

    async def calculate_certainty(self, intent_analysis_result: commons.IntentAnalysisResult) -> float:
        if "switch" in intent_analysis_result.verbs:
            self.logger.debug("Switch verb detected, certainty set to 1.0.")
            return 1.0
        self.logger.debug("No switch verb detected, certainty set to 0.")
        return 0

    async def find_parameters(self, action: Action, intent_analysis_result: commons.IntentAnalysisResult) -> Parameters:
        parameters = Parameters()
        room = intent_analysis_result.client_request.room
        devices = await self.get_devices(room)
        if action == Action.LIST:
            parameters.targets = devices
        elif action in [Action.ON, Action.OFF]:
            targets = [device for device in devices if device.alias in intent_analysis_result.nouns]
            parameters.targets = targets
        self.logger.debug("Parameters found for action %s: %s", action, parameters.targets)
        return parameters

    def get_answer(self, action: Action, parameters: Parameters) -> str:
        template = self.action_to_answer.get(action)
        if template:
            answer = template.render(
                action=action,
                parameters=parameters,
            )
            self.logger.debug("Generated answer using template for action %s.", action)
            return answer
        else:
            self.logger.error("No template found for action %s.", action)
            return "Sorry, I couldn't process your request."

    async def send_mqtt_command(self, action: Action, parameters: Parameters) -> None:
        """Send the MQTT command asynchronously."""
        for device in parameters.targets:
            payload = device.payload_on if action == Action.ON else device.payload_off
            self.logger.info("Sending payload %s to topic %s via MQTT.", payload, device.topic)
            try:
                await self.mqtt_client.publish(device.topic, payload, qos=1)
            except Exception as e:
                self.logger.error("Failed to send MQTT message to topic %s: %s", device.topic, e, exc_info=True)

    async def process_request(self, intent_analysis_result: commons.IntentAnalysisResult) -> None:
        action = Action.find_matching_action(intent_analysis_result.client_request.text)
        if action is None:
            self.logger.error("Unrecognized action in verbs: %s", intent_analysis_result.verbs)
            return

        parameters = await self.find_parameters(action, intent_analysis_result)
        if parameters.targets:
            answer = self.get_answer(action, parameters)
            self.add_task(self.send_response(answer, client_request=intent_analysis_result.client_request))
            if action not in [Action.HELP, Action.LIST]:
                self.add_task(self.send_mqtt_command(action, parameters))
        else:
            self.logger.error("No targets found for action %s.", action)
