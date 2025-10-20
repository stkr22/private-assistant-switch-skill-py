import asyncio
import logging
from dataclasses import dataclass

import aiomqtt
import jinja2
import private_assistant_commons as commons
from private_assistant_commons import (
    ClassifiedIntent,
    IntentRequest,
    IntentType,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from private_assistant_switch_skill.models import SwitchSkillDevice  # Import the Device model from models.py


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
    """Command parameters extracted from classified intent.

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


class SwitchSkill(commons.BaseSkill):
    """Main skill class for controlling smart switches, plugs, and bulbs via zigbee2mqtt.

    Processes voice commands to control IoT devices through MQTT messaging.
    Provides room-aware device resolution, template-based responses, and global
    device registry integration for optimal performance.

    Attributes:
        db_engine: Database engine for device queries
        template_env: Jinja2 environment for response generation
        intent_to_template: Mapping of intent types to response templates
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
        super().__init__(
            config_obj=config_obj,
            mqtt_client=mqtt_client,
            task_group=task_group,
            engine=dependencies.db_engine,
            logger=logger,
        )
        self.db_engine = dependencies.db_engine
        self.template_env = dependencies.template_env
        self.intent_to_template: dict[IntentType, jinja2.Template] = {}

        # AIDEV-NOTE: Intent-based configuration replaces calculate_certainty method
        self.supported_intents = {
            IntentType.DEVICE_ON: 0.8,
            IntentType.DEVICE_OFF: 0.8,
            IntentType.SYSTEM_HELP: 0.7,
        }

        # AIDEV-NOTE: Device types this skill can control
        self.supported_device_types = ["light", "switch", "plug", "bulb"]

        # AIDEV-NOTE: Template preloading at init prevents runtime template lookup failures
        self._load_templates()

    def _load_templates(self) -> None:
        """Load and validate all required templates with fallback handling.

        Raises:
            RuntimeError: If critical templates cannot be loaded
        """
        template_mappings = {
            IntentType.SYSTEM_HELP: "help.j2",
            IntentType.DEVICE_ON: "state.j2",
            IntentType.DEVICE_OFF: "state.j2",
        }

        failed_templates = []
        for intent_type, template_name in template_mappings.items():
            try:
                self.intent_to_template[intent_type] = self.template_env.get_template(template_name)
            except jinja2.TemplateNotFound as e:
                self.logger.error("Failed to load template %s: %s", template_name, e)
                failed_templates.append(template_name)

        if failed_templates:
            raise RuntimeError(f"Critical templates failed to load: {', '.join(failed_templates)}")

        self.logger.debug("All templates successfully loaded during initialization.")

        self.logger.info("Skill preparations complete. %d devices loaded from registry.", len(self.global_devices))

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
        # AIDEV-NOTE: Room priority logic - current room first for context-aware resolution
        self.logger.debug("Searching for device '%s' in current room: %s", device_name, current_room)

        # Search current room first
        for global_device in self.global_devices:
            if (
                global_device.room
                and global_device.room.name == current_room
                and global_device.name.lower() == device_name.lower()
            ):
                switch_device = SwitchSkillDevice.from_global_device(global_device)
                return DeviceLocation(device=switch_device, found_room=current_room)

        # If not found, search other rooms
        self.logger.debug("Device not found in current room, searching other rooms")
        for global_device in self.global_devices:
            if (
                global_device.room
                and global_device.room.name != current_room
                and global_device.name.lower() == device_name.lower()
            ):
                switch_device = SwitchSkillDevice.from_global_device(global_device)
                return DeviceLocation(device=switch_device, found_room=global_device.room.name)

        return None

    async def _extract_devices_from_entities(
        self, classified_intent: ClassifiedIntent, current_room: str
    ) -> list[DeviceLocation]:
        """Extract device targets from classified intent entities.

        Handles both generic device types (e.g., "light" for all lights) and specific device names.
        When a generic device type is detected, all devices of that type in the target room(s) are selected.

        Args:
            classified_intent: The classified intent with extracted entities
            current_room: The current room context

        Returns:
            list[DeviceLocation]: List of device locations to control
        """
        targets = []
        device_entities = classified_intent.entities.get("devices", [])
        room_entities = classified_intent.entities.get("rooms", [])

        # Determine target rooms
        target_rooms = [room_entities[0].normalized_value] if room_entities else [current_room]

        if device_entities:
            for device_entity in device_entities:
                device_value = device_entity.normalized_value
                is_generic = device_entity.metadata.get("is_generic", False)

                # Check if this is a generic device type (e.g., "light" for all lights)
                # Generic if: explicit metadata flag OR matches a supported device type
                if is_generic and device_value in self.supported_device_types:
                    # Get all devices of this type in target rooms
                    for room in target_rooms:
                        for global_device in self.global_devices:
                            if (
                                global_device.room
                                and global_device.room.name == room
                                and global_device.device_type
                                and global_device.device_type.name == device_value
                            ):
                                switch_device = SwitchSkillDevice.from_global_device(global_device)
                                targets.append(DeviceLocation(device=switch_device, found_room=room))
                else:
                    # Specific device name - find by name
                    device_location = await self.find_device_in_all_rooms(device_value, current_room)
                    if device_location:
                        targets.append(device_location)

        return targets

    def _render_response(self, intent_type: IntentType, parameters: Parameters) -> str:
        """Render response using template for given intent type.

        Args:
            intent_type: The intent type to render response for
            parameters: Command parameters for template context

        Returns:
            str: Rendered response text
        """
        template = self.intent_to_template.get(intent_type)
        if template:
            answer = template.render(
                intent_type=intent_type,
                parameters=parameters,
            )
            self.logger.debug("Generated answer using template for intent %s.", intent_type)
            return answer
        self.logger.error("No template found for intent %s.", intent_type)
        return "Sorry, I couldn't process your request."

    async def _send_mqtt_commands(self, intent_type: IntentType, parameters: Parameters) -> None:
        """Send MQTT commands to control target devices concurrently.

        Publishes device-specific payloads to zigbee2mqtt topics for each target device.
        Uses concurrent operations to reduce latency for multi-device commands.
        Fire-and-forget approach with QoS 1 for delivery assurance but no state confirmation.

        Args:
            intent_type: The intent type being performed (DEVICE_ON/DEVICE_OFF)
            parameters: Command parameters containing target devices

        Raises:
            Exception: If MQTT publishing fails for any device
        """
        if not parameters.targets:
            return

        # AIDEV-NOTE: Concurrent MQTT publishing addresses issue #49 - faster room-wide commands
        async def publish_single_device(device_location: DeviceLocation) -> None:
            """Publish MQTT command for a single device with error handling."""
            try:
                is_on_action = intent_type == IntentType.DEVICE_ON
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
                raise

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
            self.logger.error("Failed to execute concurrent MQTT operations: %s", e)
            raise

    async def _handle_device_on(self, intent_request: IntentRequest) -> None:
        """Handle DEVICE_ON intent - turn devices on.

        Args:
            intent_request: The intent request with classified intent and client request
        """
        classified_intent = intent_request.classified_intent
        client_request = intent_request.client_request
        current_room = client_request.room

        # Extract device targets from entities
        targets = await self._extract_devices_from_entities(classified_intent, current_room)

        if not targets:
            await self.send_response("I couldn't find any devices to turn on.", client_request)
            return

        # Build parameters
        parameters = Parameters(
            targets=targets,
            current_room=current_room,
            rooms=[current_room],
            is_room_wide=len(targets) > 1,
        )

        # Send response and MQTT commands
        answer = self._render_response(IntentType.DEVICE_ON, parameters)
        self.add_task(self.send_response(answer, client_request=client_request))
        self.add_task(self._send_mqtt_commands(IntentType.DEVICE_ON, parameters))

    async def _handle_device_off(self, intent_request: IntentRequest) -> None:
        """Handle DEVICE_OFF intent - turn devices off.

        Args:
            intent_request: The intent request with classified intent and client request
        """
        classified_intent = intent_request.classified_intent
        client_request = intent_request.client_request
        current_room = client_request.room

        # Extract device targets from entities
        targets = await self._extract_devices_from_entities(classified_intent, current_room)

        if not targets:
            await self.send_response("I couldn't find any devices to turn off.", client_request)
            return

        # Build parameters
        parameters = Parameters(
            targets=targets,
            current_room=current_room,
            rooms=[current_room],
            is_room_wide=len(targets) > 1,
        )

        # Send response and MQTT commands
        answer = self._render_response(IntentType.DEVICE_OFF, parameters)
        self.add_task(self.send_response(answer, client_request=client_request))
        self.add_task(self._send_mqtt_commands(IntentType.DEVICE_OFF, parameters))

    async def _handle_system_help(self, intent_request: IntentRequest) -> None:
        """Handle SYSTEM_HELP intent - show help information.

        Args:
            intent_request: The intent request with classified intent and client request
        """
        client_request = intent_request.client_request
        current_room = client_request.room

        # Build empty parameters for help template
        parameters = Parameters(
            targets=[],
            current_room=current_room,
            rooms=[current_room],
            is_room_wide=False,
        )

        # Send response
        answer = self._render_response(IntentType.SYSTEM_HELP, parameters)
        self.add_task(self.send_response(answer, client_request=client_request))

    async def process_request(self, intent_request: IntentRequest) -> None:
        """Main request processing method - routes intent to appropriate handler.

        Orchestrates the full command processing pipeline:
        1. Extract intent type from classified intent
        2. Route to appropriate intent handler
        3. Handler extracts entities, controls devices, and sends response

        Args:
            intent_request: The intent request with classified intent and client request
        """
        classified_intent = intent_request.classified_intent
        intent_type = classified_intent.intent_type

        self.logger.debug(
            "Processing intent %s with confidence %.2f",
            intent_type,
            classified_intent.confidence,
        )

        # Route to appropriate handler
        if intent_type == IntentType.DEVICE_ON:
            await self._handle_device_on(intent_request)
        elif intent_type == IntentType.DEVICE_OFF:
            await self._handle_device_off(intent_request)
        elif intent_type == IntentType.SYSTEM_HELP:
            await self._handle_system_help(intent_request)
        else:
            self.logger.warning("Unsupported intent type: %s", intent_type)
            await self.send_response(
                "I'm not sure how to handle that request.",
                client_request=intent_request.client_request,
            )
