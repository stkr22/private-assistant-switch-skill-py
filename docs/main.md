# Private Assistant Switch Skill - Developer Documentation

## Architecture Overview

The Switch Skill is part of the Modular Private Assistant ecosystem - a distributed home automation system where independent skills communicate via MQTT.

### System Flow
```
Voice Input  Speech-to-Text  Intent Analysis  MQTT Broadcast  Skills  zigbee2mqtt  Devices
```

### Core Components

#### SwitchSkill Class
- **Purpose**: Main skill implementation extending `private_assistant_commons.BaseSkill`
- **Key Methods**:
  - `calculate_certainty()`: Returns 1.0 if "switch" verb detected
  - `process_request()`: Main request handler
  - `find_device_in_all_rooms()`: Room-aware device lookup
  - `send_mqtt_command()`: Device control via MQTT

#### SwitchSkillDevice Model
```python
class SwitchSkillDevice(SQLModelValidation, table=True):
    id: int | None = Field(default=None, primary_key=True)
    topic: str        # zigbee2mqtt MQTT topic
    alias: str        # Human-readable device name
    room: str         # Room location
    payload_on: str   # MQTT payload for "on" (default: "ON")
    payload_off: str  # MQTT payload for "off" (default: "OFF")
```

#### Action Enum
- **ON/OFF**: Individual device control
- **ROOM_ON/ROOM_OFF**: Room-wide light control ("all lights")
- **LIST**: Show available devices
- **HELP**: Usage instructions

## Database Setup

### Prerequisites
- PostgreSQL database running
- Environment variables or config file with connection details

### Device Configuration
Devices must be manually added to the database:

```sql
INSERT INTO switchskilldevice (topic, alias, room, payload_on, payload_off) 
VALUES 
  ('livingroom/light/main', 'main light', 'living room', 'ON', 'OFF'),
  ('bedroom/switch/bedside', 'bedside lamp', 'bedroom', 'ON', 'OFF'),
  ('kitchen/plug/coffee', 'coffee maker', 'kitchen', 'ON', 'OFF');
```

### MQTT Topic Validation
Topics are validated against regex: `[\$#\+\s\0-\31]+`
- No wildcards (+, #)
- No whitespace or control characters
- Max 128 characters

## Configuration

### Environment Variables
- `PRIVATE_ASSISTANT_CONFIG_PATH`: Path to YAML config file
- PostgreSQL connection via `PostgresConfig.from_env()`

### Config File Example
```yaml
mqtt_server_host: 192.168.1.100
mqtt_server_port: 1883
client_id: switch_skill_prod
intent_analysis_result_topic: "assistant/intent_engine/result"
```

## Development Setup

### Install Dependencies
```bash
uv sync --group dev
```

### Run Tests
```bash
uv run pytest
uv run pytest --cov=private_assistant_switch_skill
```

### Code Quality
```bash
uv run ruff check .      # Lint
uv run ruff format .     # Format
uv run mypy src/         # Type checking
```

### Run Locally
```bash
private-assistant-switch-skill local_config.yaml
```

## Device Management

### Adding New Devices

1. **Add to zigbee2mqtt**: Pair device through zigbee2mqtt interface
2. **Note MQTT topic**: Check zigbee2mqtt logs for device topic
3. **Insert to database**:
   ```sql
   INSERT INTO switchskilldevice (topic, alias, room) 
   VALUES ('bedroom/light/ceiling', 'ceiling light', 'bedroom');
   ```
4. **Test**: Use voice command "switch on ceiling light"

### Device Cache
- Loads all devices on first access
- Cached in memory for performance
- No automatic refresh (manual restart required for new devices)
- Future improvement: voice command "refresh devices"

## MQTT Integration

### zigbee2mqtt Topics
- **Command topics**: `device/topic/set` (usually)
- **Payloads**: Configurable per device (ON/OFF, true/false, etc.)
- **Fire-and-forget**: No state confirmation

### Message Flow
1. Intent analysis publishes to `intent_analysis_result_topic`
2. SwitchSkill calculates certainty and processes if high
3. Device commands sent to zigbee2mqtt topics
4. Response sent back via MQTT to user interface

## Templates

Jinja2 templates in `src/private_assistant_switch_skill/templates/`:

- **help.j2**: Usage instructions
- **state.j2**: Device on/off confirmation
- **list.j2**: Available devices listing  
- **room_state.j2**: Room-wide control confirmation

## Troubleshooting

### Common Issues

1. **Device not found**: Check database entry and spelling
2. **No response**: Verify MQTT broker connection
3. **Device doesn't respond**: Check zigbee2mqtt topic and payload
4. **Room confusion**: Device search prioritizes current room

### Debugging
- Enable debug logging in `private_assistant_commons`
- Check MQTT broker logs
- Verify zigbee2mqtt device topics

## Future Improvements

- **Device auto-discovery**: Use zigbee2mqtt MQTT discovery
- **State feedback**: Subscribe to device state topics
- **Device refresh command**: Voice-activated cache refresh
- **Enhanced device model**: Support dimming, color, power monitoring
- **Migration system**: Waiting for SQLModel roadmap