import jinja2
import pytest
from private_assistant_switch_skill.models import Device
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


# Test for help.j2
@pytest.mark.parametrize(
    "expected_output",
    [
        (
            "The light skill can assist you with various tasks including:\n"
            "- Turning lights on or off.\n"
            "- Providing a list of all available plugs or lights.\n"
            "Just say switch and on or off followed by the devices name."
        ),
    ],
)
def test_help_template(jinja_env, expected_output):
    result = render_template("help.j2", Parameters(), jinja_env)
    assert result == expected_output


@pytest.mark.parametrize(
    "targets, expected_output",
    [
        ([], "I couldn't find any devices.\n"),
        (
            [Device(alias="Living Room Light")],
            "Here are the lights available: Living Room Light\n",
        ),
        (
            [Device(alias="Living Room Light"), Device(alias="Bedroom Fan")],
            "Here are the lights available: Living Room Light and Bedroom Fan\n",
        ),
        (
            [Device(alias="Living Room Light"), Device(alias="Bedroom Fan"), Device(alias="Kitchen Light")],
            "Here are the lights available: Living Room Light, Bedroom Fan and Kitchen Light\n",
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
        (Action.ON, [Device(alias="Living Room Light")], "I have turned the Living Room Light on.\n"),
        (Action.OFF, [Device(alias="Bedroom Fan")], "I have turned the Bedroom Fan off.\n"),
        (Action.ON, [], "Sorry, couldn't find lights requested.\n"),
    ],
)
def test_state_template(jinja_env, action, targets, expected_output):
    parameters = Parameters(targets=targets)
    result = render_template("state.j2", parameters, jinja_env, action=action)
    assert result == expected_output
