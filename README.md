# Private Assistant Switch Skill

[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=fff)](#)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v0.json)](https://github.com/charliermarsh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

A voice-controlled home automation skill for the Modular Private Assistant that manages smart switches, plugs, and bulbs through zigbee2mqtt.

## What it does

This skill enables voice control of your smart home devices by:
- Turning individual devices on/off by name
- Controlling all lights in a room simultaneously
- Listing available devices
- Providing room-aware device resolution (finds devices in current room first)

## Voice Commands

### Individual Device Control
- "Switch on the bedroom light"
- "Turn off the kitchen plug"
- "Switch off desk light"

### Room-wide Control
- "Turn off all lights"
- "Switch on all lights in bedroom"
- "Turn off all lights"

### Information Commands
- "List" - Shows all available devices
- "Help" - Displays usage instructions

## Setup

### Prerequisites
- zigbee2mqtt running and accessible via MQTT
- PostgreSQL database
- MQTT broker
- Private Assistant Commons framework

### Installation

1. Install dependencies:
```bash
uv sync --group dev
```

2. Configure MQTT and database connections via environment variables or config file

3. Set up your devices in the database (see Developer Documentation)

4. Run the skill:
```bash
private-assistant-switch-skill /path/to/config.yaml
```

## How it Works

The skill listens to MQTT messages from the Private Assistant's intent analysis system. When it detects the "switch" verb with high certainty, it:

1. Parses the command to identify the action (on/off/room/list/help)
2. Finds matching devices in the database, prioritizing the current room
3. Sends MQTT commands to zigbee2mqtt to control the devices
4. Responds with natural language confirmation

## Documentation

- [Developer Documentation](docs/) - Setup, architecture, and development guide
- [AGENTS.md](AGENTS.md) - AI agent working instructions (for developers)

**For developers**: READ THE AGENTS.md
