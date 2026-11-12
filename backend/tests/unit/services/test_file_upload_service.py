"""FileUploadService called directly, outside a route."""

from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.services.file_upload_service import FileUploadConfig, FileUploadService


def _config(base_dir: Path) -> FileUploadConfig:
    return FileUploadConfig(
        base_dir=base_dir,
        allowed_extensions={".pdf"},
        allowed_mimes={"application/pdf"},
        max_size_bytes=1024,
        verify_magic_bytes=False,
    )


def _pdf(filename: str | None) -> UploadFile:
    return UploadFile(
        file=BytesIO(b"%PDF-1.4 not much of a pdf"),
        filename=filename,
        headers=Headers({"content-type": "application/pdf"}),
    )


class TestNoFilename:
    async def test_a_named_file_saves(self, tmp_path: Path) -> None:
        result = await FileUploadService.upload_file(_pdf("manual.pdf"), _config(tmp_path))

        assert result.file_path.parent == tmp_path.resolve()
        assert result.file_path.suffix == ".pdf"
        assert result.content_type == "application/pdf"

    async def test_a_file_with_no_name_is_a_400_and_nothing_is_saved(self, tmp_path: Path) -> None:
        # FastAPI never builds an UploadFile without a name, but a direct caller
        # can, and Path(None) used to come back as a 500.
        with pytest.raises(HTTPException) as exc:
            await FileUploadService.upload_file(_pdf(None), _config(tmp_path))

        assert exc.value.status_code == 400
        assert list(tmp_path.iterdir()) == []
