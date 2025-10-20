import uuid

import pytest
from pydantic import ValidationError

from private_assistant_switch_skill.models import SwitchSkillDevice  # Assuming the Device model is in models.py

# Define test cases with valid and invalid topics
valid_topics = [
    "zigbee2mqtt/livingroom/plug/desk_lamp/set",
    "home/automation/sensor/temperature",
    "devices/kitchen/fridge",
]

invalid_topics = [
    ("zigbee2mqtt/livingroom/plug/desk_lamp/set\n"),
    ("home/automation/#"),
    (" devices/kitchen/light "),
    ("invalid\0topic"),
    (
        "home_home/automation/sensor_sensor/temperature_sensor/very_long_topic_exceeding_maximum_length_beyond_128_characters_to_trigger_error"
    ),
]


# Test that valid topics are accepted
@pytest.mark.parametrize("topic", valid_topics)
def test_valid_topics(topic):
    try:
        device = SwitchSkillDevice(id=uuid.uuid4(), topic=topic, alias="Valid Device", room="Room")
        assert device.topic == topic.strip()  # Ensure the topic is properly accepted and trimmed
    except ValidationError:
        pytest.fail(f"Valid topic '{topic}' was unexpectedly rejected.")


# Test that invalid topics are rejected
@pytest.mark.parametrize("topic", invalid_topics)
def test_invalid_topics(topic):
    with pytest.raises(ValidationError):
        SwitchSkillDevice(id=uuid.uuid4(), topic=topic, alias="Invalid Device", room="Room")
