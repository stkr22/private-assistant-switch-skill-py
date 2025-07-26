import asyncio
import pathlib
from typing import Annotated

import jinja2
import typer
from private_assistant_commons import mqtt_connection_handler, skill_config, skill_logger
from rich.console import Console
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from private_assistant_switch_skill import switch_skill
from private_assistant_switch_skill.switch_skill import SwitchSkillDependencies

# AIDEV-NOTE: Rich console integration provides consistent styling with private-commons logging
console = Console()
app = typer.Typer(
    rich_markup_mode="rich",
    help="[bold blue]Private Assistant Switch Skill[/bold blue] - Control smart switches, plugs, and bulbs",
)


@app.command()
def main(config_path: Annotated[pathlib.Path, typer.Argument(envvar="PRIVATE_ASSISTANT_CONFIG_PATH")]) -> None:
    asyncio.run(start_skill(config_path))


async def start_skill(
    config_path: pathlib.Path,
) -> None:
    """Initialize and start the switch skill with all dependencies.

    Sets up database, templates, logging, and MQTT connection, then starts
    the skill's main event loop to process incoming requests.

    Args:
        config_path: Path to YAML configuration file
    """
    logger = skill_logger.SkillLogger.get_logger("Private Assistant SwitchSkill")
    config_obj = skill_config.load_config(config_path, skill_config.SkillConfig)
    # AIDEV-NOTE: Database schema creation on startup - no migration system yet
    db_engine_async = create_async_engine(skill_config.PostgresConfig.from_env().connection_string_async)
    async with db_engine_async.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    template_env = jinja2.Environment(
        loader=jinja2.PackageLoader(
            "private_assistant_switch_skill",
            "templates",
        )
    )
    # Create dependencies container for dependency injection
    dependencies = SwitchSkillDependencies(
        db_engine=db_engine_async,
        template_env=template_env
    )
    
    await mqtt_connection_handler.mqtt_connection_handler(
        switch_skill.SwitchSkill, config_obj, 5, logger=logger, dependencies=dependencies
    )


if __name__ == "__main__":
    app()
