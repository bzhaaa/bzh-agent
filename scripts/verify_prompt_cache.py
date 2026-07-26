"""使用生产提示重复请求并输出脱敏缓存指标。"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mewcode.config import ProviderProfile, load_config
from mewcode.errors import ConfigError, ProviderError
from mewcode.models import AgentMode, ProviderEventKind, TokenUsage, UserMessage
from mewcode.prompting import PromptOptions, PromptPipeline
from mewcode.providers import LLMProvider, create_provider
from mewcode.tools import create_default_registry

MIN_REQUESTS = 2
MAX_REQUESTS = 4


def bounded_request_count(value: str) -> int:
    count = int(value)
    if not MIN_REQUESTS <= count <= MAX_REQUESTS:
        raise argparse.ArgumentTypeError(f"请求次数必须在 {MIN_REQUESTS} 到 {MAX_REQUESTS} 之间。")
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证 MewCode Prompt Cache 指标")
    parser.add_argument("--config", type=Path, help="YAML 配置文件路径")
    parser.add_argument("--profile", help="要验证的 profile 名称")
    parser.add_argument(
        "--requests",
        type=bounded_request_count,
        default=MIN_REQUESTS,
        help=f"重复请求次数，范围 {MIN_REQUESTS}-{MAX_REQUESTS}",
    )
    return parser


@dataclass(frozen=True, slots=True)
class CacheVerificationRecord:
    request_number: int
    usage: TokenUsage


def format_value(value: int | None) -> str:
    return "unknown" if value is None else str(value)


async def verify_profile(
    profile: ProviderProfile,
    request_count: int,
    *,
    provider: LLMProvider | None = None,
    pipeline: PromptPipeline | None = None,
) -> tuple[CacheVerificationRecord, ...]:
    """执行严格有界的重复请求，不打印提示正文。"""

    active_provider = provider or create_provider(profile)
    owns_provider = provider is None
    active_pipeline = pipeline or PromptPipeline()
    tools = create_default_registry().definitions()
    records: list[CacheVerificationRecord] = []
    try:
        for request_number in range(1, request_count + 1):
            envelope = await active_pipeline.build(
                messages=(UserMessage("请只回复：缓存验证完成。"),),
                tools=tools,
                project_root=Path.cwd(),
                mode=AgentMode.NORMAL,
                iteration=1,
                options=PromptOptions(),
            )
            usage: TokenUsage | None = None
            async for event in active_provider.stream(envelope):
                if event.kind == ProviderEventKind.TOKEN_USAGE:
                    usage = event.usage
            records.append(
                CacheVerificationRecord(
                    request_number,
                    usage or TokenUsage(None, None, None, None),
                )
            )
    finally:
        if owns_provider:
            close = getattr(active_provider, "close", None)
            if close is not None:
                await close()
    return tuple(records)


def render_records(profile: ProviderProfile, records: Sequence[CacheVerificationRecord]) -> None:
    for record in records:
        usage = record.usage
        print(
            " ".join(
                (
                    f"protocol={profile.protocol}",
                    f"model={profile.model}",
                    f"request={record.request_number}",
                    f"input={format_value(usage.input_tokens)}",
                    f"output={format_value(usage.output_tokens)}",
                    f"cache_create={format_value(usage.cache_creation_input_tokens)}",
                    f"cache_read={format_value(usage.cache_read_input_tokens)}",
                )
            )
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        profile = load_config(arguments.config).select_profile(arguments.profile)
        records = asyncio.run(verify_profile(profile, arguments.requests))
    except (ConfigError, ProviderError) as error:
        print(f"缓存验证失败：{error}")
        return 1
    render_records(profile, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
