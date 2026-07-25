"""供 tmux 验收使用的确定性 OpenAI/Anthropic SSE 服务。"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def select_calls(prompt: str) -> list[tuple[str, dict[str, object]]]:
    if "多个工具" in prompt:
        return [
            ("read_file", {"path": "sample.txt"}),
            ("find_files", {"pattern": "**/*.txt"}),
        ]
    if "连续工具" in prompt:
        return [("read_file", {"path": "sample.txt"})]
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


def has_tool_result(messages: list[dict[str, Any]]) -> bool:
    if not messages:
        return False
    message = messages[-1]
    if message.get("role") == "tool":
        return True
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def openai_sse(calls: list[tuple[str, dict[str, object]]], final: bool) -> str:
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
                            "delta": {"content": "工具结果已收到，"},
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
                        {"index": 0, "delta": {"content": "已完成请求。"}, "finish_reason": "stop"}
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
                    "id": f"call-{index + 1}",
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
    return (
        "".join(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks)
        + "data: [DONE]\n\n"
    )


def anthropic_sse(calls: list[tuple[str, dict[str, object]]], final: bool) -> str:
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
                    "usage": {"input_tokens": 1, "output_tokens": 0},
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
                        "delta": {"type": "text_delta", "text": "工具结果已收到，已完成请求。"},
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
                                "id": f"tool-{index + 1}",
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
        final = has_tool_result(messages)
        calls = select_calls(prompt)
        if final and "连续工具" not in prompt:
            calls = []
        protocol = "openai" if self.path.endswith("/chat/completions") else "anthropic"
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"protocol": protocol, "prompt": prompt, "final": final, "calls": len(calls)},
                    ensure_ascii=False,
                )
                + "\n"
            )
        payload = openai_sse(calls, final) if protocol == "openai" else anthropic_sse(calls, final)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    arguments = parser.parse_args()
    Handler.log_path = arguments.log
    ThreadingHTTPServer(("127.0.0.1", arguments.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
