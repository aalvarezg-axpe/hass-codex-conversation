"""Unit tests for HA <-> Codex payload transformations."""

from __future__ import annotations

from pathlib import Path

from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.codex_conversation import transform as transform_module
from custom_components.codex_conversation.transform import (
    async_prepare_files_for_prompt,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-data"
PDF_BYTES = b"%PDF-1.7\nfake-pdf-data"


class _FakeHass:
    """Minimal HomeAssistant-like object for executor job calls."""

    def __init__(self, *, allowed_path: bool = True) -> None:
        self.config = _FakeConfig(allowed_path=allowed_path)

    async def async_add_executor_job(self, target, *args):
        return target(*args)


class _FakeConfig:
    """Minimal HomeAssistant config object for path allow-list checks."""

    def __init__(self, *, allowed_path: bool) -> None:
        self._allowed_path = allowed_path

    def is_allowed_path(self, path: str) -> bool:
        return self._allowed_path


@pytest.mark.parametrize(
    ("filename", "file_bytes", "mime_type", "expected_type"),
    [
        ("image.png", PNG_BYTES, None, "input_image"),
        ("document.pdf", PDF_BYTES, None, "input_file"),
    ],
)
async def test_async_prepare_files_for_prompt_supported_types(
    tmp_path: Path,
    filename: str,
    file_bytes: bytes,
    mime_type: str | None,
    expected_type: str,
) -> None:
    file_path = tmp_path / filename
    file_path.write_bytes(file_bytes)

    result = await async_prepare_files_for_prompt(
        _FakeHass(),
        [(file_path, mime_type)],
    )

    assert len(result) == 1
    assert result[0]["type"] == expected_type
    if expected_type == "input_file":
        assert result[0]["filename"] == filename
        assert str(tmp_path) not in result[0]["filename"]


async def test_async_prepare_files_for_prompt_rejects_unsupported_file_type(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello")

    with pytest.raises(HomeAssistantError, match="Only images and PDF"):
        await async_prepare_files_for_prompt(
            _FakeHass(),
            [(file_path, None)],
        )


async def test_async_prepare_files_for_prompt_rejects_declared_type_mismatch(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "document.pdf"
    file_path.write_bytes(PDF_BYTES)

    with pytest.raises(HomeAssistantError, match="does not match"):
        await async_prepare_files_for_prompt(
            _FakeHass(),
            [(file_path, "image/png")],
        )


async def test_async_prepare_files_for_prompt_rejects_disallowed_path(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "image.png"
    file_path.write_bytes(PNG_BYTES)

    with pytest.raises(HomeAssistantError, match="not in an allowed path"):
        await async_prepare_files_for_prompt(
            _FakeHass(allowed_path=False),
            [(file_path, None)],
        )


async def test_async_prepare_files_for_prompt_rejects_large_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "image.png"
    file_path.write_bytes(PNG_BYTES)
    monkeypatch.setattr(transform_module, "MAX_ATTACHMENT_BYTES", 4)

    with pytest.raises(HomeAssistantError, match="too large"):
        await async_prepare_files_for_prompt(
            _FakeHass(),
            [(file_path, None)],
        )


async def test_async_prepare_files_for_prompt_missing_file() -> None:
    with pytest.raises(HomeAssistantError, match="does not exist"):
        await async_prepare_files_for_prompt(
            _FakeHass(),
            [(Path("/tmp/definitely-missing-file.png"), "image/png")],
        )
