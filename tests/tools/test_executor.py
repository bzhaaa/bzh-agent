"""注册中心和统一执行器测试。"""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from mewcode.tools import (
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolErrorCode,
    ToolExecutionPolicy,
    ToolExecutor,
    ToolRegistry,
    create_default_registry,
)


def test_default_registry_and_duplicate_rejection() -> None:
    registry = create_default_registry()
    assert [definition.name for definition in registry.definitions()] == [
        "read_file",
        "write_file",
        "edit_file",
        "execute_command",
        "find_files",
        "search_code",
    ]
    assert all(
        definition.input_schema["additionalProperties"] is False
        for definition in registry.definitions()
    )
    with pytest.raises(ValueError, match="重复"):
        registry.register(registry.get("read_file"))  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,arguments,code",
    [
        ("missing_tool", "{}", ToolErrorCode.UNKNOWN_TOOL),
        ("read_file", "{", ToolErrorCode.INVALID_JSON),
        ("read_file", "[]", ToolErrorCode.INVALID_JSON),
        ("read_file", "{}", ToolErrorCode.INVALID_ARGUMENTS),
        ("read_file", '{"path":"x","extra":1}', ToolErrorCode.INVALID_ARGUMENTS),
    ],
)
async def test_executor_maps_lookup_and_argument_errors(
    tmp_path: Path, name: str, arguments: str, code: ToolErrorCode
) -> None:
    registry = create_default_registry()
    result = await ToolExecutor(registry).execute(
        ToolCall("id", name, arguments), ToolContext(tmp_path)
    )
    assert not result.success
    assert result.error_code == code
    assert "Traceback" not in result.to_model_json()


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplodingTool:
    argument_model = EmptyArguments
    requires_approval = False
    policy = ToolExecutionPolicy.PARALLEL_READ
    definition = ToolDefinition("explode", "测试异常隔离。", EmptyArguments.model_json_schema())

    async def execute(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        raise RuntimeError("unsafe-secret")


class BlockingTool(ExplodingTool):
    definition = ToolDefinition("block", "测试取消传播。", EmptyArguments.model_json_schema())

    async def execute(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        await asyncio.Event().wait()
        return {}


@pytest.mark.asyncio
async def test_executor_hides_internal_error_and_preserves_cancellation(tmp_path: Path) -> None:
    registry = ToolRegistry((ExplodingTool(), BlockingTool()))
    executor = ToolExecutor(registry)
    failed = await executor.execute(ToolCall("x", "explode", "{}"), ToolContext(tmp_path))
    assert failed.error_code == ToolErrorCode.INTERNAL_ERROR
    assert "unsafe-secret" not in failed.to_model_json()
    task = asyncio.create_task(
        executor.execute(ToolCall("x", "block", json.dumps({})), ToolContext(tmp_path))
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_registry_rejects_missing_policy_and_subset_unknown() -> None:
    class MissingPolicy:
        argument_model = EmptyArguments
        requires_approval = False
        definition = ToolDefinition(
            "missing_policy",
            "缺少策略。",
            EmptyArguments.model_json_schema(),
        )

    with pytest.raises(ValueError, match="执行策略"):
        ToolRegistry((MissingPolicy(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="不存在"):
        create_default_registry().subset(("read_file", "missing"))


def test_tool_descriptions_reinforce_specialized_tool_rules() -> None:
    descriptions = {
        definition.name: definition.description
        for definition in create_default_registry().definitions()
    }
    assert "编辑或覆盖已有文件前必须先" in descriptions["read_file"]
    assert "小范围变化优先" in descriptions["write_file"]
    assert "先用 read_file" in descriptions["edit_file"]
    assert "find 或 ls" in descriptions["find_files"]
    assert "grep 或 rg" in descriptions["search_code"]
    assert "不得替代专用工具" in descriptions["execute_command"]
