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


class DeviceLocation(BaseModel):
    device: SwitchSkillDevice
    found_room: str


class Parameters(BaseModel):
    targets: list[DeviceLocation] = []
    current_room: str
    rooms: list[str] = []
    is_room_wide: bool = False


class Action(Enum):
    HELP = ["help"]
    ON = ["on"]
    OFF = ["off"]
    LIST = ["list"]
    ROOM_ON = ["room", "on"]
    ROOM_OFF = ["room", "off"]

    @classmethod
    def find_matching_action(cls, text: str) -> "Action | None":
        text = text.translate(str.maketrans("", "", string.punctuation))
        text_words = set(text.lower().split())

        # Check for room-wide light control phrases
        text_lower = text.lower()
        if "all lights" in text_lower:
            if "on" in text_words:
                return cls.ROOM_ON
            if "off" in text_words:
                return cls.ROOM_OFF

        # Check other actions
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
        self._device_cache: dict[str, list[SwitchSkillDevice]] = {}
        self.action_to_answer: dict[Action, jinja2.Template] = {}

        # Preload templates
        try:
            self.action_to_answer[Action.HELP] = self.template_env.get_template("help.j2")
            self.action_to_answer[Action.ON] = self.template_env.get_template("state.j2")
            self.action_to_answer[Action.OFF] = self.template_env.get_template("state.j2")
            self.action_to_answer[Action.LIST] = self.template_env.get_template("list.j2")
            self.action_to_answer[Action.ROOM_ON] = self.template_env.get_template("room_state.j2")
            self.action_to_answer[Action.ROOM_OFF] = self.template_env.get_template("room_state.j2")
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

    async def get_devices(self, rooms: list[str]) -> list[SwitchSkillDevice]:
        """Return devices for a list of rooms, using async cache loading."""
        if not self._device_cache:
            await self.load_device_cache()
        self.logger.info("Fetching devices for rooms: %s", rooms)

        devices = []
        for room in rooms:
            devices.extend(self._device_cache.get(room, []))
        return devices

    async def get_all_room_devices(self, rooms: list[str]) -> list[DeviceLocation]:
        """Get all devices from specified rooms."""
        if not self._device_cache:
            await self.load_device_cache()

        devices = []
        for room in rooms:
            room_devices = self._device_cache.get(room, [])
            devices.extend([DeviceLocation(device=device, found_room=room) for device in room_devices])
        return devices

    async def skill_preparations(self):
        return await super().skill_preparations()

    async def calculate_certainty(self, intent_analysis_result: commons.IntentAnalysisResult) -> float:
        if "switch" in intent_analysis_result.verbs:
            self.logger.debug("Switch verb detected, certainty set to 1.0.")
            return 1.0
        self.logger.debug("No switch verb detected, certainty set to 0.")
        return 0

    async def find_device_in_all_rooms(self, device_name: str, current_room: str) -> DeviceLocation | None:
        """
        Search for a device across all rooms, prioritizing the current room.
        """
        if not self._device_cache:
            await self.load_device_cache()

        # First check current room
        self.logger.debug("Searching for device '%s' in current room: %s", device_name, current_room)
        current_room_devices = self._device_cache.get(current_room, [])
        for device in current_room_devices:
            if device.alias.lower() == device_name.lower():
                return DeviceLocation(device=device, found_room=current_room)

        # If not found, search other rooms
        self.logger.debug("Device not found in current room, searching other rooms")
        for room, devices in self._device_cache.items():
            if room == current_room:
                continue
            for device in devices:
                if device.alias.lower() == device_name.lower():
                    return DeviceLocation(device=device, found_room=room)

        return None

    async def find_parameters(self, action: Action, intent_analysis_result: commons.IntentAnalysisResult) -> Parameters:
        room = intent_analysis_result.client_request.room
        parameters = Parameters(current_room=room, is_room_wide=False)
        parameters.rooms = intent_analysis_result.rooms or [intent_analysis_result.client_request.room]

        if action in [Action.ROOM_ON, Action.ROOM_OFF]:
            parameters.is_room_wide = True
            parameters.targets = await self.get_all_room_devices(parameters.rooms)
        elif action == Action.LIST:
            devices = await self.get_devices(parameters.rooms)
            parameters.targets = [DeviceLocation(device=device, found_room=room) for device in devices]
        elif action in [Action.ON, Action.OFF]:
            device_names = [n.lower() for n in intent_analysis_result.nouns]
            for device_name in device_names:
                device_location = await self.find_device_in_all_rooms(device_name, room)
                if device_location:
                    parameters.targets.append(device_location)

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
        self.logger.error("No template found for action %s.", action)
        return "Sorry, I couldn't process your request."

    async def send_mqtt_command(self, action: Action, parameters: Parameters) -> None:
        """Send the MQTT command asynchronously."""
        for device_location in parameters.targets:
            is_on_action = action in [Action.ON, Action.ROOM_ON]
            payload = device_location.device.payload_on if is_on_action else device_location.device.payload_off
            self.logger.info(
                "Sending payload %s to topic %s via MQTT for device in %s.",
                payload,
                device_location.device.topic,
                device_location.found_room,
            )
            await self.mqtt_client.publish(device_location.device.topic, payload, qos=1)

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
