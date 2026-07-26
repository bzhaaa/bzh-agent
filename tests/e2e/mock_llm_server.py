"""供 tmux 验收使用的确定性 OpenAI/Anthropic SSE 服务。"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def select_calls(prompt: str, step: int, mode: str) -> list[tuple[str, dict[str, object]]]:
    if mode == "plan":
        sequence = [
            [
                ("read_file", {"path": "sample.txt"}),
                ("find_files", {"pattern": "**/*.txt"}),
            ],
            [("search_code", {"query": "needle", "file_pattern": "**/*.txt"})],
        ]
        return sequence[step] if step < len(sequence) else []
    if prompt.strip() == "/do":
        return (
            [("write_file", {"path": "plan-result.txt", "content": "planned\n"})]
            if step == 0
            else []
        )
    if "先读后改" in prompt:
        sequence = [
            [("read_file", {"path": "generated.txt"})],
            [
                (
                    "edit_file",
                    {"path": "generated.txt", "old_text": "alpha", "new_text": "beta"},
                )
            ],
            [("read_file", {"path": "generated.txt"})],
        ]
        return sequence[step] if step < len(sequence) else []
    if "三步任务" in prompt:
        sequence = [
            [
                ("read_file", {"path": "sample.txt"}),
                ("find_files", {"pattern": "**/*.txt"}),
            ],
            [("search_code", {"query": "needle", "file_pattern": "**/*.txt"})],
            [("write_file", {"path": "agent-loop.txt", "content": "agent-loop\n"})],
        ]
        return sequence[step] if step < len(sequence) else []
    if "并发调度" in prompt:
        sequence = [
            [
                ("read_file", {"path": "sample.txt"}),
                ("find_files", {"pattern": "**/*.txt"}),
            ],
            [("write_file", {"path": "generated.txt", "content": "alpha\n"})],
            [
                ("read_file", {"path": "generated.txt"}),
                ("search_code", {"query": "alpha", "file_pattern": "**/*.txt"}),
            ],
            [
                (
                    "edit_file",
                    {"path": "generated.txt", "old_text": "alpha", "new_text": "beta"},
                )
            ],
        ]
        return sequence[step] if step < len(sequence) else []
    if "未知工具" in prompt:
        return [("missing_tool", {})]
    if "取消并发读" in prompt:
        return [
            ("find_files", {"pattern": "**/*", "max_results": 1000}),
            ("search_code", {"query": "never-a", "file_pattern": "**/*"}),
            ("search_code", {"query": "never-b", "file_pattern": "**/*"}),
        ]
    if "迭代上限" in prompt or "连续工具" in prompt:
        return [("read_file", {"path": "sample.txt"})]
    if step > 0:
        return []
    if "多个工具" in prompt:
        return [
            ("read_file", {"path": "sample.txt"}),
            ("find_files", {"pattern": "**/*.txt"}),
        ]
    if "新建" in prompt:
        return [("write_file", {"path": "generated.txt", "content": "alpha\n"})]
    if "修改零匹配" in prompt:
        return [
            (
                "edit_file",
                {"path": "generated.txt", "old_text": "missing", "new_text": "changed"},
            )
        ]
    if "修改多匹配" in prompt:
        return [
            (
                "edit_file",
                {"path": "duplicates.txt", "old_text": "same", "new_text": "changed"},
            )
        ]
    if "修改" in prompt:
        return [
            (
                "edit_file",
                {"path": "generated.txt", "old_text": "alpha", "new_text": "beta"},
            )
        ]
    if "查找" in prompt:
        return [("find_files", {"pattern": "**/*.txt"})]
    if "搜索" in prompt:
        return [("search_code", {"query": "needle", "file_pattern": "**/*.txt"})]
    if "命令批准" in prompt:
        return [("execute_command", {"command": "touch approved-marker", "timeout_seconds": 5})]
    if "命令拒绝" in prompt:
        return [("execute_command", {"command": "touch rejected-marker", "timeout_seconds": 5})]
    if "取消确认" in prompt:
        return [
            (
                "execute_command",
                {"command": "touch confirmation-cancelled-marker", "timeout_seconds": 5},
            )
        ]
    if "长命令" in prompt:
        command = "echo $$ > command.pid; sleep 120 & echo $! > child.pid; wait"
        return [("execute_command", {"command": command, "timeout_seconds": 30})]
    if "符号链接" in prompt:
        return [("read_file", {"path": "outside-link.txt"})]
    if "越界" in prompt:
        return [("read_file", {"path": "../outside.txt"})]
    if "读取" in prompt:
        return [("read_file", {"path": "sample.txt"})]
    return []


def prompt_from_messages(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def current_tool_step(messages: list[dict[str, Any]]) -> int:
    """统计最近一条字符串用户消息之后的完整工具请求次数。"""

    start = 0
    for index, message in enumerate(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            start = index + 1
    count = 0
    for message in messages[start:]:
        if message.get("role") != "assistant":
            continue
        if isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
            count += 1
            continue
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_use" for block in content
        ):
            count += 1
    return count


def final_text(prompt: str, mode: str) -> str:
    if mode == "plan":
        return "调查完成。计划：根据搜索结果更新目标文件，然后运行验证。"
    if prompt.strip() == "/do":
        return "计划已经执行完成。"
    return "工具结果已收到，已完成请求。"


def openai_sse(
    calls: list[tuple[str, dict[str, object]]],
    final: bool,
    *,
    prompt: str,
    step: int,
    mode: str,
) -> str:
    chunks: list[dict[str, object]] = []
    if final and not calls:
        chunks.extend(
            [
                {
                    "id": "chat-final",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": final_text(prompt, mode)[:8]},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chat-final",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": final_text(prompt, mode)[8:]},
                            "finish_reason": "stop",
                        }
                    ],
                },
            ]
        )
    elif calls:
        first_fragments = []
        second_fragments = []
        for index, (name, arguments) in enumerate(calls):
            encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
            split = max(1, len(encoded) // 2)
            first_fragments.append(
                {
                    "index": index,
                    "id": f"call-{step + 1}-{index + 1}",
                    "type": "function",
                    "function": {"name": name, "arguments": encoded[:split]},
                }
            )
            second_fragments.append(
                {
                    "index": index,
                    "function": {"arguments": encoded[split:]},
                }
            )
        chunks.extend(
            [
                {
                    "id": "chat-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"tool_calls": first_fragments},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chat-tool",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"tool_calls": second_fragments},
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
            ]
        )
    else:
        chunks.append(
            {
                "id": "chat-text",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "mock",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "你好，MewCode 已就绪。"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
    usage = {
        "id": "chat-usage",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "mock",
        "choices": [],
        "usage": {
            "prompt_tokens": 10 + step,
            "completion_tokens": 3,
            "prompt_tokens_details": {"cached_tokens": 0 if step == 0 else 8},
        },
    }
    chunks.append(usage)
    return (
        "".join(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks)
        + "data: [DONE]\n\n"
    )


def anthropic_sse(
    calls: list[tuple[str, dict[str, object]]],
    final: bool,
    *,
    prompt: str,
    step: int,
    mode: str,
) -> str:
    events: list[tuple[str, dict[str, object]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg-1",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": "mock",
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 12 if step == 0 else 0,
                        "cache_read_input_tokens": 0 if step == 0 else 10,
                    },
                },
            },
        )
    ]
    if final and not calls:
        events.extend(
            [
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": "", "citations": None},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": final_text(prompt, mode)},
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ]
        )
        stop_reason = "end_turn"
    elif calls:
        for index, (name, arguments) in enumerate(calls):
            encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
            split = max(1, len(encoded) // 2)
            events.extend(
                [
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": {
                                "type": "tool_use",
                                "id": f"tool-{step + 1}-{index + 1}",
                                "name": name,
                                "input": {},
                            },
                        },
                    ),
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {"type": "input_json_delta", "partial_json": encoded[:split]},
                        },
                    ),
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {"type": "input_json_delta", "partial_json": encoded[split:]},
                        },
                    ),
                    ("content_block_stop", {"type": "content_block_stop", "index": index}),
                ]
            )
        stop_reason = "tool_use"
    else:
        events.extend(
            [
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": "", "citations": None},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "你好，MewCode 已就绪。"},
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ]
        )
        stop_reason = "end_turn"
    events.extend(
        [
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
    )
    return "".join(
        f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        for event, payload in events
    )


class Handler(BaseHTTPRequestHandler):
    log_path: Path

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length))
        messages = body.get("messages", [])
        prompt = prompt_from_messages(messages)
        step = current_tool_step(messages)
        protocol = "openai" if self.path.endswith("/chat/completions") else "anthropic"
        if protocol == "openai":
            system_blocks = [
                message.get("content", "")
                for message in messages
                if message.get("role") == "system"
            ]
        else:
            system_blocks = [
                block.get("text", "") for block in body.get("system", []) if isinstance(block, dict)
            ]
        reminder = next((text for text in system_blocks if "<system-reminder>" in text), "")
        mode = "plan" if "Agent 模式：plan" in reminder else "normal"
        calls = select_calls(prompt, step, mode)
        final = step > 0 and not calls
        stable_system = system_blocks[0] if system_blocks else ""
        tools = body.get("tools", [])
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "timestamp": time.time(),
                        "protocol": protocol,
                        "prompt": prompt,
                        "step": step,
                        "final": final,
                        "calls": [name for name, _arguments in calls],
                        "tools": [
                            tool.get("function", {}).get("name", "")
                            if protocol == "openai"
                            else tool.get("name", "")
                            for tool in tools
                        ],
                        "stable_system_sha256": hashlib.sha256(
                            stable_system.encode("utf-8")
                        ).hexdigest(),
                        "system_block_count": len(system_blocks),
                        "reminder_present": bool(reminder),
                        "mode": mode,
                        "system_cache_control": (
                            body.get("system", [{}])[0].get("cache_control")
                            if protocol == "anthropic" and body.get("system")
                            else None
                        ),
                        "last_tool_cache_control": (
                            tools[-1].get("cache_control")
                            if protocol == "anthropic" and tools
                            else None
                        ),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        if "流错误" in prompt:
            payload = (
                'data: {"id":"broken","object":"chat.completion.chunk","created":1,'
                '"model":"mock","choices":[{"index":0,"delta":{"content":"部分"},'
                '"finish_reason":null}]}\n\ndata: [DONE]\n\n'
                if protocol == "openai"
                else (
                    "event: message_start\n"
                    'data: {"type":"message_start","message":'
                    '{"usage":{"input_tokens":1}}}\n\n'
                )
            )
        else:
            payload = (
                openai_sse(calls, final, prompt=prompt, step=step, mode=mode)
                if protocol == "openai"
                else anthropic_sse(calls, final, prompt=prompt, step=step, mode=mode)
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        encoded = payload.encode("utf-8")
        if "长模型" in prompt and len(encoded) > 1:
            split = len(encoded) // 2
            try:
                self.wfile.write(encoded[:split])
                self.wfile.flush()
                time.sleep(30)
                self.wfile.write(encoded[split:])
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self.wfile.write(encoded)
            self.wfile.flush()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    arguments = parser.parse_args()
    Handler.log_path = arguments.log
    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
