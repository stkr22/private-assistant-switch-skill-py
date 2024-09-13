from sqlmodel import Field, SQLModel


class BaseSwitchSkillModel(SQLModel):
    __table_args__ = {"schema": "switch_skill"}


class Device(BaseSwitchSkillModel, table=True):  # type: ignore
    id: int | None = Field(default=None, primary_key=True)
    topic: str
    alias: str
    room: str
    payload_on: str = "ON"
    payload_off: str = "OFF"
