from sqlmodel import Field, SQLModel


class Device(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    topic: str
    alias: str
    room: str
    payload_on: str = "ON"
    payload_off: str = "OFF"
