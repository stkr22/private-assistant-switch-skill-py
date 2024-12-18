# Private Assistant switch Skill

[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)
[![python](https://img.shields.io/badge/Python-3.12-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v0.json)](https://github.com/charliermarsh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

Owner: stkr22

## Overview

This Home Automation Skill is a specialized module designed to integrate with a Modular Private Assistant system. It utilizes MQTT for communication to manage and control smart home devices like plugs and bulbs, enhancing home automation capabilities.

## Features

- **Device Control**: Directly control smart plugs and bulbs through intuitive voice commands.
- **MQTT Integration**: Seamlessly communicates with the private assistant's coordinator using MQTT, ensuring reliable and real-time operations.
- **Dynamic Response Generation**: Provides feedback on the actions performed, enhancing user interaction by confirming the status of devices or reporting any issues.

## Getting Started

### Prerequisites

- A functioning MQTT broker setup.
- The Modular Private Assistant's coordinator must be running and configured.

### Installation

1. Clone the repository to your local machine.
2. Ensure Python 3.12 is installed.
3. Install dependencies using:
    ```bash
    pip install -r requirements.txt
    ```
4. Configure the MQTT settings in `template.yaml` to match your environment:
    ```yaml
    mqtt_server_host: "localhost"
    mqtt_server_port: 1883
    client_id: "skill_name"
    certainty_topic: "assistant/coordinator/certainty"
    register_topic: "assistant/coordinator/register"
    registration_interval: 500.0
    ```

### Usage

To run the skill, execute:

```bash
python -m home_automation_skill
```

This will activate the skill, and it will start listening for commands via MQTT.

## Contributing

Contributions are welcome! If you'd like to improve the functionality or add support for more devices, please fork the repository and submit a pull request.
