"""CLI 入口测试。"""

import importlib.util
import sys
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from mewcode import cli
from mewcode.config import ProviderProfile
from mewcode.models import ProviderEvent, ProviderEventKind, TokenUsage
from mewcode.prompting import PromptEnvelope, PromptPipeline
from mewcode.tui import TranscriptEntry, TranscriptSnapshot

_CACHE_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "verify_prompt_cache.py"
_CACHE_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "mewcode_test_verify_prompt_cache", _CACHE_SCRIPT_PATH
)
assert _CACHE_SCRIPT_SPEC is not None and _CACHE_SCRIPT_SPEC.loader is not None
_CACHE_SCRIPT = importlib.util.module_from_spec(_CACHE_SCRIPT_SPEC)
sys.modules[_CACHE_SCRIPT_SPEC.name] = _CACHE_SCRIPT
_CACHE_SCRIPT_SPEC.loader.exec_module(_CACHE_SCRIPT)
build_cache_parser = _CACHE_SCRIPT.build_parser
render_records = _CACHE_SCRIPT.render_records
verify_profile = _CACHE_SCRIPT.verify_profile


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
    assert isinstance(captured_sessions[0].runner.prompt_pipeline, PromptPipeline)


@pytest.mark.asyncio
async def test_prompt_cache_verifier_is_bounded_and_preserves_unknown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile = ProviderProfile.model_validate(
        {
            "name": "cache-test",
            "protocol": "openai",
            "model": "cache-model",
            "base_url": "https://api.example.com/v1",
            "api_key": "never-print-this-secret",
        }
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.requests: list[PromptEnvelope] = []

        async def stream(self, request: PromptEnvelope):
            self.requests.append(request)
            yield ProviderEvent(
                ProviderEventKind.TEXT_DELTA,
                "完成",
            )
            yield ProviderEvent(
                ProviderEventKind.TOKEN_USAGE,
                usage=TokenUsage(20, 2, None, None),
            )
            yield ProviderEvent(ProviderEventKind.DONE)

    provider = FakeProvider()
    records = await verify_profile(profile, 2, provider=provider)  # type: ignore[arg-type]
    assert len(provider.requests) == 2
    assert len(records) == 2
    assert provider.requests[0].prompt.stable_system == provider.requests[1].prompt.stable_system
    render_records(profile, records)
    output = capsys.readouterr().out
    assert "cache_read=unknown" in output
    assert "never-print-this-secret" not in output
    with pytest.raises(SystemExit):
        build_cache_parser().parse_args(["--requests", "5"])
