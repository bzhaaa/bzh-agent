"""MewCode 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console

from mewcode.agent.runner import AgentRunner
from mewcode.agent.scheduler import ToolScheduler
from mewcode.config import ProviderProfile, load_config
from mewcode.errors import ConfigError
from mewcode.prompting import PromptPipeline
from mewcode.providers import create_provider
from mewcode.session import READ_ONLY_TOOLS, ChatSession
from mewcode.tools import CommandApprovalRequest, ToolContext, ToolExecutor, create_default_registry
from mewcode.tui import MewCodeApp, render_static_transcript


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mewcode", description="MewCode 终端 AI 助手")
    parser.add_argument("--config", type=Path, help="YAML 配置文件路径")
    parser.add_argument("--profile", help="覆盖配置中的默认 profile")
    return parser


async def run_app(profile: ProviderProfile, console: Console | None = None) -> None:
    """组装并运行应用。"""

    output = console or Console()
    provider = create_provider(profile)
    try:
        project_root = Path.cwd().resolve()
        registry = create_default_registry()
        executor = ToolExecutor(registry)
        readonly_registry = registry.subset(READ_ONLY_TOOLS)
        approval_target: list[object] = []

        async def request_approval(request: CommandApprovalRequest) -> bool:
            if not approval_target:
                return False
            handler = getattr(approval_target[0], "request_command_approval", None)
            if handler is None:
                return False
            return bool(await handler(request))

        context = ToolContext(project_root, request_approval)
        runner = AgentRunner(
            provider,
            ToolScheduler(registry, executor),
            ToolScheduler(readonly_registry, ToolExecutor(readonly_registry)),
            context,
            PromptPipeline(),
        )
        session = ChatSession(runner)
        app = MewCodeApp(session, profile_name=profile.name, model=profile.model)
        approval_target.append(app)
        snapshot = await app.run_async(mouse=True)
        render_static_transcript(snapshot, output)
    finally:
        close = getattr(provider, "close", None)
        if close is not None:
            await close()


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数并返回稳定进程退出码。"""

    arguments = build_parser().parse_args(argv)
    try:
        config = load_config(arguments.config)
        profile = config.select_profile(arguments.profile)
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2
    try:
        asyncio.run(run_app(profile))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
