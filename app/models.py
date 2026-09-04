"""Validated data contracts shared by the Gemini boundary and the API."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CastCall(BaseModel):
    """A performer and the time they need to report to set."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=120)
    call_time: str = Field(default="TBD", max_length=40)
    notes: str = Field(default="", max_length=300)

    @field_validator("name", "notes", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("call_time", mode="before")
    @classmethod
    def clean_call_time(cls, value: Any) -> str:
        return normalize_call_time(value)


class PropItem(BaseModel):
    """A prop required by a scene."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=300)

    @field_validator("name", "notes", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return str(value or "").strip()


class Scene(BaseModel):
    """One normalized screenplay scene."""

    model_config = ConfigDict(extra="ignore")

    scene_number: str = Field(min_length=1, max_length=30)
    heading: str = Field(min_length=1, max_length=240)
    location: str = Field(default="Unspecified", max_length=160)
    time_of_day: str = Field(default="Unspecified", max_length=80)
    summary: str = Field(default="", max_length=600)
    cast: list[CastCall] = Field(default_factory=list, max_length=80)
    props: list[PropItem] = Field(default_factory=list, max_length=80)

    @field_validator("scene_number", "heading", "location", "time_of_day", "summary", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("location", mode="after")
    @classmethod
    def default_location(cls, value: str) -> str:
        return value or "Unspecified"

    @field_validator("time_of_day", mode="after")
    @classmethod
    def normalize_time_of_day(cls, value: str) -> str:
        value = value or "Unspecified"
        return value.title() if value.upper() not in {"DAY", "NIGHT", "DAWN", "DUSK"} else value.upper()


class ProductionSummary(BaseModel):
    """Counts shown above the call sheet."""

    model_config = ConfigDict(extra="ignore")

    scene_count: int = Field(ge=0)
    cast_count: int = Field(ge=0)
    prop_count: int = Field(ge=0)


class CallSheet(BaseModel):
    """The stable payload returned to the browser."""

    model_config = ConfigDict(extra="ignore")

    summary: ProductionSummary
    scenes: list[Scene] = Field(min_length=1, max_length=100)


class ParseRequest(BaseModel):
    """Bounded API input."""

    model_config = ConfigDict(extra="forbid")

    screenplay: str = Field(min_length=1, max_length=100_000)

    @field_validator("screenplay")
    @classmethod
    def screenplay_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Screenplay text cannot be empty.")
        return value


class ApiError(BaseModel):
    detail: str


def normalize_call_time(value: Any) -> str:
    """Make common 12/24-hour model outputs predictable for the UI."""

    raw = str(value or "").strip()
    if not raw or raw.upper() in {"TBD", "UNKNOWN", "N/A", "NA", "NONE"}:
        return "TBD"

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])?", raw)
    if not match:
        return raw

    hour = int(match.group(1))
    minute = int(match.group(2) or "00")
    meridiem = match.group(3)
    if minute > 59:
        return raw
    if meridiem:
        if hour < 1 or hour > 12:
            return raw
        return f"{hour:02d}:{minute:02d} {meridiem.upper()}"
    if hour > 23:
        return raw
    return f"{hour:02d}:{minute:02d}"


def _dedupe(items: list[BaseModel], key: str) -> list[BaseModel]:
    unique: OrderedDict[str, BaseModel] = OrderedDict()
    for item in items:
        item_key = str(getattr(item, key)).casefold()
        if item_key not in unique:
            unique[item_key] = item
        else:
            current = unique[item_key]
            if hasattr(current, "notes") and not current.notes and item.notes:
                unique[item_key] = current.model_copy(update={"notes": item.notes})
    return list(unique.values())


def normalize_call_sheet(payload: Any) -> CallSheet:
    """Validate Gemini JSON, remove duplicates, and compute trusted counts."""

    if not isinstance(payload, dict):
        raise ValueError("Gemini returned a JSON value instead of an object.")
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Gemini response did not include at least one scene.")

    scenes: list[Scene] = []
    for raw_scene in raw_scenes:
        if not isinstance(raw_scene, dict):
            raise ValueError("Gemini returned a scene with an invalid shape.")
        # These aliases make the boundary tolerant of harmless key naming drift,
        # while required scene_number and heading still fail loudly when absent.
        scene_data = dict(raw_scene)
        if "scene_number" not in scene_data and "number" in scene_data:
            scene_data["scene_number"] = scene_data["number"]
        if "time_of_day" not in scene_data and "time" in scene_data:
            scene_data["time_of_day"] = scene_data["time"]
        if "cast" not in scene_data:
            scene_data["cast"] = []
        if "props" not in scene_data:
            scene_data["props"] = []
        scene = Scene.model_validate(scene_data)
        scene = scene.model_copy(
            update={
                "cast": _dedupe(scene.cast, "name"),
                "props": _dedupe(scene.props, "name"),
            }
        )
        scenes.append(scene)

    cast_count = len({person.name.casefold() for scene in scenes for person in scene.cast})
    prop_count = len({prop.name.casefold() for scene in scenes for prop in scene.props})
    return CallSheet(
        scenes=scenes,
        summary=ProductionSummary(
            scene_count=len(scenes),
            cast_count=cast_count,
            prop_count=prop_count,
        ),
    )