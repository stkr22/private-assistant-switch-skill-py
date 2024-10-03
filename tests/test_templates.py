import jinja2
import pytest

from private_assistant_switch_skill.models import SwitchSkillDevice
from private_assistant_switch_skill.switch_skill import Action, Parameters  # Assuming Parameters is defined here


# Fixture to set up the Jinja environment
@pytest.fixture(scope="module")
def jinja_env():
    return jinja2.Environment(
        loader=jinja2.PackageLoader(
            "private_assistant_switch_skill",
            "templates",
        ),
    )


def render_template(template_name, parameters, env, action=None):
    template = env.get_template(template_name)
    return template.render(parameters=parameters, action=action)


@pytest.mark.parametrize(
    "targets, expected_output",
    [
        ([], "No devices were found.\n"),
        (
            [SwitchSkillDevice(alias="Living Room Light")],
            "The following devices are available: Living Room Light\n",
        ),
        (
            [SwitchSkillDevice(alias="Living Room Light"), SwitchSkillDevice(alias="Bedroom Fan")],
            "The following devices are available: Living Room Light and Bedroom Fan\n",
        ),
        (
            [
                SwitchSkillDevice(alias="Living Room Light"),
                SwitchSkillDevice(alias="Bedroom Fan"),
                SwitchSkillDevice(alias="Kitchen Light"),
            ],
            "The following devices are available: Living Room Light, Bedroom Fan and Kitchen Light\n",
        ),
    ],
)
def test_list_template(jinja_env, targets, expected_output):
    parameters = Parameters(targets=targets)  # Using Device objects in targets
    result = render_template("list.j2", parameters, jinja_env)
    assert result == expected_output


# Test for state.j2
@pytest.mark.parametrize(
    "action, targets, expected_output",
    [
        # Test with a single device
        (
            Action.ON,
            [SwitchSkillDevice(alias="Living Room Light")],
            "The device Living Room Light has been turned on.\n",
        ),
        (
            Action.OFF,
            [SwitchSkillDevice(alias="Bedroom Fan")],
            "The device Bedroom Fan has been turned off.\n",
        ),
        # Test with no devices
        (Action.ON, [], "No devices matching the request were found.\n"),
        # Test with multiple devices
        (
            Action.ON,
            [SwitchSkillDevice(alias="Living Room Light"), SwitchSkillDevice(alias="Bedroom Fan")],
            "The devices Living Room Light and Bedroom Fan have been turned on.\n",
        ),
    ],
)
def test_state_template(jinja_env, action, targets, expected_output):
    parameters = Parameters(targets=targets)
    result = render_template("state.j2", parameters, jinja_env, action=action)
    assert result == expected_output
