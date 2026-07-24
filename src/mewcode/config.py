"""YAML 配置加载和校验。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from mewcode.errors import ConfigError

_ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class ProviderProfile(BaseModel):
    """单个模型供应商配置。"""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    protocol: Literal["anthropic", "openai"]
    model: str = Field(min_length=1)
    base_url: AnyHttpUrl
    api_key: SecretStr
    thinking: bool = False

    @field_validator("api_key", mode="before")
    @classmethod
    def resolve_api_key(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("api_key 不能为空")
        raw_value = value.strip()
        match = _ENV_REFERENCE.fullmatch(raw_value)
        if not match:
            return raw_value
        variable = match.group(1)
        resolved = os.environ.get(variable)
        if not resolved:
            raise ValueError(f"环境变量 {variable} 未设置")
        return resolved

    @model_validator(mode="after")
    def validate_thinking_protocol(self) -> ProviderProfile:
        if self.protocol == "openai" and self.thinking:
            raise ValueError("OpenAI profile 不支持 thinking")
        return self


class AppConfig(BaseModel):
    """完整应用配置。"""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    default: str = Field(min_length=1)
    profiles: tuple[ProviderProfile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile_names(self) -> AppConfig:
        names = [profile.name for profile in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("profile name 不能重复")
        if self.default not in names:
            raise ValueError(f"默认 profile '{self.default}' 不存在")
        return self

    def select_profile(self, override: str | None = None) -> ProviderProfile:
        selected = override or self.default
        for profile in self.profiles:
            if profile.name == selected:
                return profile
        raise ConfigError(f"profile '{selected}' 不存在")


def _format_validation_error(error: ValidationError) -> str:
    details: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        message = item["msg"]
        details.append(f"{location}: {message}" if location else message)
    return "；".join(details)


def load_config(path: Path | None = None) -> AppConfig:
    """读取并验证 YAML 配置。"""

    config_path = path or Path.home() / ".config" / "mewcode" / "config.yaml"
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigError(f"配置文件不存在：{config_path}") from error
    except OSError as error:
        raise ConfigError(f"无法读取配置文件：{config_path}") from error

    try:
        document = yaml.safe_load(raw_text)
    except yaml.YAMLError as error:
        raise ConfigError(f"配置文件 YAML 格式无效：{config_path}") from error
    if document is None:
        raise ConfigError(f"配置文件为空：{config_path}")
    if not isinstance(document, dict):
        raise ConfigError("配置文件顶层必须是映射")
    try:
        return AppConfig.model_validate(document)
    except ValidationError as error:
        raise ConfigError(f"配置无效：{_format_validation_error(error)}") from error
