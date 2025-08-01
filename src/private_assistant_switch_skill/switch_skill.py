import asyncio
import logging
import re
import string
from dataclasses import dataclass
from enum import Enum
from re import Pattern

import aiomqtt
import jinja2
import private_assistant_commons as commons
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from private_assistant_switch_skill.exceptions import (
    ConcurrencyError,
    DatabaseError,
    DeviceCacheError,
    MQTTError,
    TemplateError,
)
from private_assistant_switch_skill.models import SwitchSkillDevice  # Import the Device model from models.py


@dataclass
class ActionPattern:
    """Defines a pattern for matching user input to actions.

    Supports both keyword-based matching and regex patterns for complex cases.

    Attributes:
        keywords: List of required keywords (all must be present)
        regex_pattern: Optional regex pattern for complex matching
        priority: Higher priority patterns are checked first
    """

    keywords: list[str]
    regex_pattern: Pattern[str] | None = None
    priority: int = 0


@dataclass
class SwitchSkillDependencies:
    """Container for SwitchSkill dependencies to reduce constructor parameter count.

    Groups related dependencies into a single object to simplify dependency injection
    and reduce the number of constructor parameters in SwitchSkill.

    Attributes:
        db_engine: Async SQLAlchemy engine for database operations
        template_env: Jinja2 environment for response template rendering
    """

    db_engine: AsyncEngine
    template_env: jinja2.Environment


class DeviceLocation(BaseModel):
    """Represents a device and the room where it was found during device resolution.

    Used to track context when devices are found in rooms different from the current room,
    enabling informative responses like "bedroom light (found in bedroom)".

    Attributes:
        device: The SwitchSkillDevice that was found
        found_room: The room where the device was located
    """

    device: SwitchSkillDevice
    found_room: str


class Parameters(BaseModel):
    """Command parameters extracted from intent analysis results.

    Contains all information needed to execute a switch command, including
    target devices, room context, and command scope.

    Attributes:
        targets: List of devices to control with their locations
        current_room: Room where the user made the request
        rooms: List of rooms to search for devices
        is_room_wide: Whether command affects all devices in room(s)
    """

    targets: list[DeviceLocation] = []
    current_room: str
    rooms: list[str] = []
    is_room_wide: bool = False


class Action(Enum):
    """Enum representing different switch actions that can be performed.

    Each action is defined by an ActionPattern that specifies matching criteria.
    This enables flexible, data-driven action detection without hard-coded special cases.

    Attributes:
        HELP: Show usage instructions
        ON: Turn individual device(s) on
        OFF: Turn individual device(s) off
        LIST: List available devices
        ROOM_ON: Turn all devices in room(s) on
        ROOM_OFF: Turn all devices in room(s) off
        REFRESH: Refresh device cache from database
    """

    # AIDEV-NOTE: Data-driven action patterns replace hard-coded special cases
    HELP = ActionPattern(keywords=["help"], priority=10)
    LIST = ActionPattern(keywords=["list"], priority=10)
    REFRESH = ActionPattern(keywords=["refresh"], priority=10)
    # High priority patterns for "all lights" scenarios
    ROOM_ON = ActionPattern(keywords=["on"], regex_pattern=re.compile(r"all\s+lights?"), priority=20)
    ROOM_OFF = ActionPattern(keywords=["off"], regex_pattern=re.compile(r"all\s+lights?"), priority=20)
    # Lower priority basic on/off patterns
    ON = ActionPattern(keywords=["on"], priority=5)
    OFF = ActionPattern(keywords=["off"], priority=5)

    def get_action_name(self) -> str:
        """Get human-readable action name for templates.
        
        Returns:
            str: Human-readable action name (e.g., "on", "off")
        """
        if self == Action.ROOM_ON:
            return "on"
        if self == Action.ROOM_OFF:
            return "off"
        return str(self.value.keywords[0])

    @classmethod
    def find_matching_action(cls, text: str) -> "Action | None":
        """Parse user text to identify the intended action using pattern matching.

        Uses configurable ActionPatterns to determine which action the user wants to perform.
        Patterns are checked by priority (highest first) to handle overlapping cases correctly.

        Args:
            text: Raw user input text to parse

        Returns:
            Action: The detected action, or None if no match found
        """
        # Normalize text for consistent matching
        normalized_text = text.translate(str.maketrans("", "", string.punctuation)).lower()
        text_words = set(normalized_text.split())

        # Sort actions by priority (highest first) for correct precedence
        actions_by_priority = sorted(cls, key=lambda a: a.value.priority, reverse=True)

        for action in actions_by_priority:
            pattern = action.value

            # Check if all required keywords are present
            keywords_match = all(keyword in text_words for keyword in pattern.keywords)

            # Check regex pattern if specified
            regex_match = True
            if pattern.regex_pattern:
                regex_match = bool(pattern.regex_pattern.search(normalized_text))

            if keywords_match and regex_match:
                return action

        return None


class SwitchSkill(commons.BaseSkill):
    """Main skill class for controlling smart switches, plugs, and bulbs via zigbee2mqtt.

    Processes voice commands to control IoT devices through MQTT messaging.
    Provides room-aware device resolution, template-based responses, and device caching
    for optimal performance.

    Attributes:
        db_engine: Database engine for device queries
        template_env: Jinja2 environment for response generation
        _device_cache: In-memory cache of devices by room
        action_to_answer: Mapping of actions to response templates
    """

    def __init__(
        self,
        config_obj: commons.SkillConfig,
        mqtt_client: aiomqtt.Client,
        dependencies: SwitchSkillDependencies,
        task_group: asyncio.TaskGroup,
        logger: logging.Logger,
    ) -> None:
        """Initialize the switch skill with dependencies and load templates.

        Args:
            config_obj: Skill configuration from commons
            mqtt_client: MQTT client for device communication
            dependencies: Injected dependencies (database, templates)
            task_group: Async task group for concurrent operations
            logger: Logger instance for debugging and monitoring
        """
        super().__init__(config_obj=config_obj, mqtt_client=mqtt_client, task_group=task_group, logger=logger)
        self.db_engine = dependencies.db_engine
        self.template_env = dependencies.template_env
        # AIDEV-NOTE: Device cache is lazy-loaded and never refreshed - restart required for new devices
        self._device_cache: dict[str, list[SwitchSkillDevice]] = {}
        self.action_to_answer: dict[Action, jinja2.Template] = {}

        # AIDEV-NOTE: Template preloading at init prevents runtime template lookup failures
        self._load_templates()

    def _load_templates(self) -> None:
        """Load and validate all required templates with fallback handling.

        Raises:
            TemplateError: If critical templates cannot be loaded
        """
        template_mappings = {
            Action.HELP: "help.j2",
            Action.ON: "state.j2",
            Action.OFF: "state.j2",
            Action.LIST: "list.j2",
            Action.ROOM_ON: "room_state.j2",
            Action.ROOM_OFF: "room_state.j2",
            Action.REFRESH: "refresh.j2",
        }

        failed_templates = []
        for action, template_name in template_mappings.items():
            try:
                self.action_to_answer[action] = self.template_env.get_template(template_name)
            except jinja2.TemplateNotFound as e:
                self.logger.error("Failed to load template %s: %s", template_name, e)
                failed_templates.append(template_name)

        if failed_templates:
            raise TemplateError(
                f"Critical templates failed to load: {', '.join(failed_templates)}", template_name=failed_templates[0]
            )

        self.logger.debug("All templates successfully loaded during initialization.")

    async def load_device_cache(self) -> None:
        """Load all devices from database into memory cache organized by room.

        Performs lazy loading - only loads when cache is empty. Validates each device
        and organizes them by room for efficient lookup. Invalid devices are logged
        but do not prevent other devices from loading.

        Raises:
            DatabaseError: If database query fails
            DeviceCacheError: If cache loading fails due to validation issues
        """
        if not self._device_cache:
            self.logger.debug("Loading devices into cache asynchronously.")

            # AIDEV-NOTE: Improved resource management with explicit error handling and cleanup
            session = None
            try:
                session = AsyncSession(self.db_engine)
                statement = select(SwitchSkillDevice)
                result = await session.exec(statement)
                devices = result.all()

                validation_errors = []
                for device in devices:
                    try:
                        device.model_validate(device)
                        if device.room not in self._device_cache:
                            self._device_cache[device.room] = []
                        self._device_cache[device.room].append(device)
                    except ValidationError as e:
                        error_msg = f"Device {device.alias} (topic: {device.topic}): {e}"
                        self.logger.error("Validation error loading device into cache: %s", error_msg)
                        validation_errors.append(error_msg)

                self.logger.info(
                    "Device cache loaded successfully: %d devices across %d rooms. %d validation errors.",
                    sum(len(devices) for devices in self._device_cache.values()),
                    len(self._device_cache),
                    len(validation_errors),
                )

                if validation_errors and len(validation_errors) == len(devices):
                    raise DeviceCacheError("All devices failed validation - no devices available")

            except Exception as e:
                if isinstance(e, ValidationError | DeviceCacheError):
                    raise
                self.logger.error("Database error loading device cache: %s", e, exc_info=True)
                raise DatabaseError(f"Failed to load device cache from database: {e}") from e
            finally:
                if session:
                    await session.close()

    async def refresh_device_cache(self) -> None:
        """Force refresh of device cache from database.

        Clears existing cache and reloads all devices from the database.
        Useful for picking up newly added devices without restart.

        Raises:
            DatabaseError: If database query fails
            DeviceCacheError: If cache loading fails due to validation issues
        """
        # AIDEV-NOTE: Manual cache refresh addresses issue #43 - no more restart required for new devices
        self.logger.info("Refreshing device cache from database...")
        self._device_cache.clear()
        await self.load_device_cache()
        self.logger.info("Device cache refresh completed successfully.")

    async def get_devices(self, rooms: list[str]) -> list[SwitchSkillDevice]:
        """Get all devices from the specified rooms.

        Loads device cache if needed, then returns all devices found in the
        specified rooms. Non-existent rooms are silently ignored.

        Args:
            rooms: List of room names to search for devices

        Returns:
            list[SwitchSkillDevice]: All devices found in the specified rooms
        """
        if not self._device_cache:
            await self.load_device_cache()
        self.logger.info("Fetching devices for rooms: %s", rooms)

        devices = []
        for room in rooms:
            devices.extend(self._device_cache.get(room, []))
        return devices

    async def get_all_room_devices(self, rooms: list[str]) -> list[DeviceLocation]:
        """Get all devices from specified rooms with location context.

        Similar to get_devices() but wraps each device in a DeviceLocation
        to track which room it was found in.

        Args:
            rooms: List of room names to search for devices

        Returns:
            list[DeviceLocation]: All devices with their room locations
        """
        if not self._device_cache:
            await self.load_device_cache()

        devices = []
        for room in rooms:
            room_devices = self._device_cache.get(room, [])
            devices.extend([DeviceLocation(device=device, found_room=room) for device in room_devices])
        return devices

    async def skill_preparations(self) -> None:
        # AIDEV-NOTE: Override base method for skill-specific preparation logic
        pass

    async def calculate_certainty(self, intent_analysis_result: commons.IntentAnalysisResult) -> float:
        """Calculate how confident this skill is about handling the user's request.

        Simple binary certainty calculation: returns 1.0 if "switch" verb is detected,
        0.0 otherwise. This ensures the skill only processes switch-related commands.

        Args:
            intent_analysis_result: Analyzed user intent from the intent engine

        Returns:
            float: Certainty score (0.0 or 1.0)
        """
        if "switch" in intent_analysis_result.verbs:
            self.logger.debug("Switch verb detected, certainty set to 1.0.")
            return 1.0
        self.logger.debug("No switch verb detected, certainty set to 0.")
        return 0

    async def find_device_in_all_rooms(self, device_name: str, current_room: str) -> DeviceLocation | None:
        """Search for a device across all rooms, prioritizing the current room.

        Implements room-aware device resolution by first checking the current room,
        then expanding the search to all other rooms. This allows users to control
        devices in other rooms by name when not ambiguous.

        Args:
            device_name: Name/alias of the device to find
            current_room: Room where the user made the request

        Returns:
            DeviceLocation: Device and its location if found, None otherwise
        """
        if not self._device_cache:
            await self.load_device_cache()

        # AIDEV-NOTE: Room priority logic - current room first for context-aware resolution
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
        """Extract command parameters based on action type and intent analysis.

        Args:
            action: The detected action to perform
            intent_analysis_result: Analyzed user intent from the intent engine

        Returns:
            Parameters: Command parameters with target devices and context
        """
        room = intent_analysis_result.client_request.room
        parameters = Parameters(current_room=room, is_room_wide=False)
        parameters.rooms = intent_analysis_result.rooms or [intent_analysis_result.client_request.room]

        # AIDEV-NOTE: Parameter extraction logic varies by action type
        if action in [Action.ROOM_ON, Action.ROOM_OFF]:
            parameters.is_room_wide = True
            parameters.targets = await self.get_all_room_devices(parameters.rooms)
        elif action == Action.LIST:
            devices = await self.get_devices(parameters.rooms)
            parameters.targets = [DeviceLocation(device=device, found_room=room) for device in devices]
        elif action == Action.REFRESH:
            # No targets needed for refresh action
            pass
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
        """Send MQTT commands to control target devices concurrently.

        Publishes device-specific payloads to zigbee2mqtt topics for each target device.
        Uses concurrent operations to reduce latency for multi-device commands.
        Fire-and-forget approach with QoS 1 for delivery assurance but no state confirmation.

        Args:
            action: The action being performed (ON/OFF/ROOM_ON/ROOM_OFF)
            parameters: Command parameters containing target devices

        Raises:
            MQTTError: If MQTT publishing fails for any device
            ConcurrencyError: If concurrent operations fail
        """
        if not parameters.targets:
            return

        # AIDEV-NOTE: Concurrent MQTT publishing addresses issue #49 - faster room-wide commands
        async def publish_single_device(device_location: DeviceLocation) -> None:
            """Publish MQTT command for a single device with error handling."""
            try:
                is_on_action = action in [Action.ON, Action.ROOM_ON]
                payload = device_location.device.payload_on if is_on_action else device_location.device.payload_off

                self.logger.info(
                    "Sending payload %s to topic %s via MQTT for device in %s.",
                    payload,
                    device_location.device.topic,
                    device_location.found_room,
                )

                await self.mqtt_client.publish(device_location.device.topic, payload, qos=1)

            except Exception as e:
                self.logger.error(
                    "Failed to publish MQTT command for device %s (topic: %s): %s",
                    device_location.device.alias,
                    device_location.device.topic,
                    e,
                )
                raise MQTTError(
                    f"Failed to publish to {device_location.device.alias}", topic=device_location.device.topic
                ) from e

        try:
            # Execute all MQTT publishes concurrently using BaseSkill task management
            tasks = []
            for device_location in parameters.targets:
                task = self.add_task(
                    publish_single_device(device_location), name=f"mqtt-publish-{device_location.device.alias}"
                )
                tasks.append(task)

            # Wait for all tasks to complete
            await asyncio.gather(*tasks)

            self.logger.debug("Successfully sent MQTT commands to %d devices concurrently", len(parameters.targets))

        except Exception as e:
            if isinstance(e, MQTTError):
                raise
            self.logger.error("Concurrent MQTT operations failed: %s", e)
            raise ConcurrencyError(f"Failed to execute concurrent MQTT operations: {e}") from e

    async def process_request(self, intent_analysis_result: commons.IntentAnalysisResult) -> None:
        """Main request processing method - handles complete switch command workflow.

        Orchestrates the full command processing pipeline:
        1. Parse action from user text
        2. Find target devices based on action type
        3. Generate response using templates
        4. Send MQTT commands (for control actions)
        5. Send response back to user

        Args:
            intent_analysis_result: Analyzed user intent from the intent engine
        """
        action = Action.find_matching_action(intent_analysis_result.client_request.text)
        if action is None:
            self.logger.error("Unrecognized action in verbs: %s", intent_analysis_result.verbs)
            return

        parameters = await self.find_parameters(action, intent_analysis_result)

        # Handle refresh action specially
        if action == Action.REFRESH:
            try:
                await self.refresh_device_cache()
                answer = self.get_answer(action, parameters) or "Device cache refreshed successfully."
                self.add_task(self.send_response(answer, client_request=intent_analysis_result.client_request))
            except (DatabaseError, DeviceCacheError) as e:
                self.logger.error("Failed to refresh device cache: %s", e)
                error_answer = "Sorry, I couldn't refresh the device cache. Please try again later."
                self.add_task(self.send_response(error_answer, client_request=intent_analysis_result.client_request))
            return

        if parameters.targets:
            answer = self.get_answer(action, parameters)
            self.add_task(self.send_response(answer, client_request=intent_analysis_result.client_request))
            # AIDEV-NOTE: Only send MQTT commands for control actions, not info actions
            if action not in [Action.HELP, Action.LIST]:
                self.add_task(self.send_mqtt_command(action, parameters))
        else:
            self.logger.error("No targets found for action %s.", action)
