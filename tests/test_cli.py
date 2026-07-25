"""CLI 入口测试。"""

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from mewcode import cli
from mewcode.config import ProviderProfile
from mewcode.tui import TranscriptEntry, TranscriptSnapshot


def write_config(path: Path) -> Path:
    path.write_text(
        """
default: first
profiles:
  - name: first
    protocol: openai
    model: first-model
    base_url: https://api.example.com/v1
    api_key: secret-one
  - name: second
    protocol: anthropic
    model: second-model
    base_url: https://api.anthropic.com
    api_key: secret-two
""",
        encoding="utf-8",
    )
    return path


def test_help_lists_supported_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    assert "--config" in output
    assert "--profile" in output


def test_config_error_returns_two_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = cli.main(["--config", str(tmp_path / "missing.yaml")])
    captured = capsys.readouterr()
    assert result == 2
    assert "配置错误" in captured.err
    assert "Traceback" not in captured.err


def test_cli_selects_profile_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_config(tmp_path / "config.yaml")
    selected: list[ProviderProfile] = []

    async def fake_run_app(profile: ProviderProfile, console: Console | None = None) -> None:
        selected.append(profile)

    monkeypatch.setattr(cli, "run_app", fake_run_app)
    result = cli.main(["--config", str(path), "--profile", "second"])
    assert result == 0
    assert selected[0].name == "second"
    assert selected[0].model == "second-model"


@pytest.mark.asyncio
async def test_run_app_uses_textual_and_always_closes_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ProviderProfile.model_validate(
        {
            "name": "main",
            "protocol": "openai",
            "model": "test-model",
            "base_url": "https://api.example.com/v1",
            "api_key": "super-secret-value",
        }
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False)
    created: list[object] = []

    class FakeApp:
        def __init__(self, session: object, *, profile_name: str, model: str) -> None:
            self.profile_name = profile_name
            self.model = model
            created.append(self)

        async def run_async(self, *, mouse: bool) -> TranscriptSnapshot:
            assert mouse
            return TranscriptSnapshot((TranscriptEntry("assistant", "完成"),))

    class FakeProvider:
        def __init__(self) -> None:
            self.close_count = 0

        async def close(self) -> None:
            self.close_count += 1

    provider = FakeProvider()
    monkeypatch.setattr(cli, "create_provider", lambda _profile: provider)
    monkeypatch.setattr(cli, "MewCodeApp", FakeApp)
    await cli.run_app(profile, console)
    assert created[0].profile_name == "main"
    assert created[0].model == "test-model"
    assert "完成" in output.getvalue()
    assert "super-secret-value" not in output.getvalue()
    assert provider.close_count == 1


@pytest.mark.asyncio
async def test_run_app_closes_provider_when_textual_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ProviderProfile.model_validate(
        {
            "name": "main",
            "protocol": "openai",
            "model": "test-model",
            "base_url": "https://api.example.com/v1",
            "api_key": "secret",
        }
    )

    class FailingApp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def run_async(self, *, mouse: bool) -> TranscriptSnapshot:
            raise RuntimeError("TUI failed")

    class FakeProvider:
        def __init__(self) -> None:
            self.close_count = 0

        async def close(self) -> None:
            self.close_count += 1

    provider = FakeProvider()
    monkeypatch.setattr(cli, "create_provider", lambda _profile: provider)
    monkeypatch.setattr(cli, "MewCodeApp", FailingApp)
    with pytest.raises(RuntimeError, match="TUI failed"):
        await cli.run_app(profile)
    assert provider.close_count == 1


@pytest.mark.asyncio
async def test_run_app_fixes_tool_root_to_starting_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = ProviderProfile.model_validate(
        {
            "name": "main",
            "protocol": "openai",
            "model": "test-model",
            "base_url": "https://api.example.com/v1",
            "api_key": "secret",
        }
    )
    captured_sessions = []

    class FakeApp:
        def __init__(self, session, **_kwargs):
            captured_sessions.append(session)

        async def run_async(self, *, mouse: bool) -> TranscriptSnapshot:
            return TranscriptSnapshot()

    class FakeProvider:
        async def close(self) -> None:
            pass

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "create_provider", lambda _profile: FakeProvider())
    monkeypatch.setattr(cli, "MewCodeApp", FakeApp)
    await cli.run_app(profile)
    assert captured_sessions[0].context.project_root == tmp_path
