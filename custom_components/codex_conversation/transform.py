"""Helpers to transform Home Assistant chat objects into Codex API payloads."""

from __future__ import annotations

import base64
from datetime import date, datetime
import json
from mimetypes import guess_file_type
from pathlib import Path
from typing import Any

from homeassistant.components.conversation import (
    AssistantContent,
    ChatLog,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from voluptuous_openapi import convert

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def json_default(obj: object) -> str:
    """Fallback serializer for types json.dumps cannot handle natively."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return str(obj)


def format_tool(tool: llm.Tool) -> dict[str, Any]:
    """Format an HA LLM tool as a Responses API function definition."""
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description or "",
        "parameters": convert(tool.parameters),
        "strict": False,
    }


def extract_instructions(chat_log: ChatLog) -> str:
    """Return the system instructions from the chat log."""
    for content in chat_log.content:
        if isinstance(content, SystemContent):
            return content.content
    return ""


def build_input_items(chat_log: ChatLog) -> list[dict[str, Any]]:
    """Build input items in Responses API format from a chat log."""
    items: list[dict[str, Any]] = []

    for content in chat_log.content:
        if isinstance(content, SystemContent):
            continue
        if isinstance(content, UserContent):
            items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": content.content}],
                }
            )
            continue
        if isinstance(content, AssistantContent):
            if content.tool_calls:
                for tool_call in content.tool_calls:
                    items.append(
                        {
                            "type": "function_call",
                            "name": tool_call.tool_name,
                            "arguments": json.dumps(tool_call.tool_args),
                            "call_id": tool_call.id,
                        }
                    )
            elif content.content:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content.content}],
                    }
                )
            continue
        if isinstance(content, ToolResultContent):
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": content.tool_call_id,
                    "output": json.dumps(content.tool_result, default=json_default),
                }
            )

    return items


async def async_prepare_files_for_prompt(
    hass: HomeAssistant, files: list[tuple[Path, str | None]]
) -> list[dict[str, Any]]:
    """Convert user attachments into Responses API input items."""

    def append_files_to_content() -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []

        for file_path, mime_type in files:
            file_path = _resolve_attachment_path(file_path)
            display_name = file_path.name or "attachment"

            if not _is_allowed_attachment_path(hass, file_path):
                raise HomeAssistantError(
                    f"Attachment `{display_name}` is not in an allowed path"
                )

            if not file_path.is_file():
                raise HomeAssistantError(f"Attachment `{display_name}` is not a file")

            size = file_path.stat().st_size
            if size > MAX_ATTACHMENT_BYTES:
                raise HomeAssistantError(
                    f"Attachment `{display_name}` is too large "
                    f"({MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit)"
                )

            detected_mime = _detect_supported_mime_type(file_path)
            if detected_mime is None:
                raise HomeAssistantError(
                    "Only images and PDF are supported by the Codex API, "
                    f"`{display_name}` is not a supported image file or PDF"
                )

            requested_mime = _normalize_mime_type(
                mime_type or guess_file_type(file_path)[0]
            )
            if requested_mime is not None and not _mime_types_match(
                requested_mime, detected_mime
            ):
                raise HomeAssistantError(
                    f"Attachment `{display_name}` does not match its declared file type"
                )

            base64_file = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            if detected_mime.startswith("image/"):
                content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{detected_mime};base64,{base64_file}",
                        "detail": "auto",
                    }
                )
            elif detected_mime == "application/pdf":
                content.append(
                    {
                        "type": "input_file",
                        "filename": display_name,
                        "file_data": f"data:{detected_mime};base64,{base64_file}",
                    }
                )

        return content

    return await hass.async_add_executor_job(append_files_to_content)


def _resolve_attachment_path(file_path: Path) -> Path:
    """Resolve an attachment path without leaking absolute paths in errors."""
    display_name = file_path.name or "attachment"
    try:
        return file_path.expanduser().resolve(strict=True)
    except FileNotFoundError as err:
        raise HomeAssistantError(f"Attachment `{display_name}` does not exist") from err
    except OSError as err:
        raise HomeAssistantError(f"Attachment `{display_name}` cannot be read") from err


def _is_allowed_attachment_path(hass: HomeAssistant, file_path: Path) -> bool:
    """Return whether Home Assistant considers *file_path* safe to read."""
    config = getattr(hass, "config", None)
    is_allowed_path = getattr(config, "is_allowed_path", None)
    if callable(is_allowed_path):
        return bool(is_allowed_path(str(file_path)))

    config_path = getattr(config, "path", None)
    if callable(config_path):
        try:
            base_path = Path(config_path()).resolve()
        except OSError:
            return False
        try:
            file_path.relative_to(base_path)
        except ValueError:
            return False
        return True

    return True


def _normalize_mime_type(mime_type: str | None) -> str | None:
    """Normalize a MIME type, ignoring parameters such as charsets."""
    if mime_type is None:
        return None
    return mime_type.split(";", 1)[0].strip().lower() or None


def _mime_types_match(requested_mime: str, detected_mime: str) -> bool:
    """Return whether a declared MIME type is compatible with detected content."""
    if requested_mime == detected_mime:
        return True
    return requested_mime.startswith("image/") and detected_mime.startswith("image/")


def _detect_supported_mime_type(file_path: Path) -> str | None:
    """Detect supported image/PDF types from file signatures."""
    with file_path.open("rb") as file:
        header = file.read(16)

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    return None
