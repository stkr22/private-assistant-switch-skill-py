"""Typed exception hierarchy for the switch skill.

This module defines a comprehensive exception hierarchy to improve error handling
throughout the codebase, replacing generic exceptions with specific, meaningful
error types that provide better context and debugging information.
"""

from __future__ import annotations


class SwitchSkillError(Exception):
    """Base exception for all switch skill errors.
    
    All custom exceptions in the switch skill should inherit from this base class
    to provide a consistent error handling interface.
    """


class DatabaseError(SwitchSkillError):
    """Database-related errors including connection failures and query errors."""


class DeviceCacheError(SwitchSkillError):
    """Errors related to device cache operations."""


class DeviceValidationError(SwitchSkillError):
    """Errors during device model validation."""
    
    def __init__(self, message: str, device_data: dict | None = None) -> None:
        super().__init__(message)
        self.device_data = device_data


class TemplateError(SwitchSkillError):
    """Template loading and rendering errors."""
    
    def __init__(self, message: str, template_name: str | None = None) -> None:
        super().__init__(message)
        self.template_name = template_name


class MQTTError(SwitchSkillError):
    """MQTT communication errors."""
    
    def __init__(self, message: str, topic: str | None = None) -> None:
        super().__init__(message)
        self.topic = topic


class DeviceNotFoundError(SwitchSkillError):
    """Error when requested device cannot be found."""
    
    def __init__(self, message: str, device_name: str | None = None, room: str | None = None) -> None:
        super().__init__(message)
        self.device_name = device_name
        self.room = room


class ActionParsingError(SwitchSkillError):
    """Error during action detection and parsing."""
    
    def __init__(self, message: str, text: str | None = None) -> None:
        super().__init__(message)
        self.text = text


class ConcurrencyError(SwitchSkillError):
    """Errors related to concurrent operations."""