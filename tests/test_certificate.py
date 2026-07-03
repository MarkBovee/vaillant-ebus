from __future__ import annotations

from pathlib import Path

from vaillant.certificate import get_or_create_certificate


def test_get_or_create_certificate_reuses_existing_files(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    first = get_or_create_certificate()
    second = get_or_create_certificate()

    assert first == second
    assert len(first) == 40
    assert Path("cert.pem").exists()
    assert Path("key.pem").exists()
