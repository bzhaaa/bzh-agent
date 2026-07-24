"""配置加载与选择测试。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from mewcode.config import AppConfig, ProviderProfile, load_config
from mewcode.errors import ConfigError


def profile_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "main",
        "protocol": "openai",
        "model": "test-model",
        "base_url": "https://api.example.com/v1",
        "api_key": "secret-example",
    }
    data.update(overrides)
    return data


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_profile_resolves_environment_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEW_TEST_KEY", "resolved-secret")
    profile = ProviderProfile.model_validate(profile_data(api_key="${MEW_TEST_KEY}"))
    assert profile.api_key.get_secret_value() == "resolved-secret"
    assert "resolved-secret" not in repr(profile)


def test_missing_environment_secret_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_MEW_KEY", raising=False)
    with pytest.raises(ValidationError) as caught:
        ProviderProfile.model_validate(profile_data(api_key="${MISSING_MEW_KEY}"))
    assert "MISSING_MEW_KEY" in str(caught.value)
    assert "secret-example" not in str(caught.value)


def test_openai_rejects_thinking() -> None:
    with pytest.raises(ValidationError, match="不支持 thinking"):
        ProviderProfile.model_validate(profile_data(thinking=True))


def test_app_config_selects_default_and_override() -> None:
    first = ProviderProfile.model_validate(profile_data())
    second = ProviderProfile.model_validate(
        profile_data(name="claude", protocol="anthropic", base_url="https://api.anthropic.com")
    )
    config = AppConfig(default="main", profiles=(first, second))
    assert config.select_profile().name == "main"
    assert config.select_profile("claude").name == "claude"
    with pytest.raises(ConfigError, match="missing"):
        config.select_profile("missing")


@pytest.mark.parametrize(
    "default,profiles,match",
    [
        ("missing", [profile_data()], "默认 profile"),
        ("main", [profile_data(), profile_data()], "不能重复"),
    ],
)
def test_app_config_rejects_invalid_profile_sets(
    default: str, profiles: list[dict[str, object]], match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        AppConfig.model_validate({"default": default, "profiles": profiles})


def test_load_config_reads_yaml(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "config.yaml",
        """
default: main
profiles:
  - name: main
    protocol: openai
    model: test-model
    base_url: https://api.example.com/v1
    api_key: direct-secret
""",
    )
    config = load_config(path)
    assert config.default == "main"
    assert config.select_profile().api_key.get_secret_value() == "direct-secret"


def test_load_config_uses_current_home_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / ".config" / "mewcode"
    config_dir.mkdir(parents=True)
    write_config(
        config_dir / "config.yaml",
        """
default: main
profiles:
  - name: main
    protocol: openai
    model: test-model
    base_url: https://api.example.com/v1
    api_key: direct-secret
""",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert load_config().default == "main"


@pytest.mark.parametrize(
    "content,match",
    [
        ("", "配置文件为空"),
        ("- item", "顶层必须是映射"),
        ("default: [", "YAML 格式无效"),
        ("default: main\nprofiles: []", "配置无效"),
    ],
)
def test_load_config_reports_invalid_documents(tmp_path: Path, content: str, match: str) -> None:
    path = write_config(tmp_path / "bad.yaml", content)
    with pytest.raises(ConfigError, match=match):
        load_config(path)


def test_load_config_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_config(tmp_path / "missing.yaml")
