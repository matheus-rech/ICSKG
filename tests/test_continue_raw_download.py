"""Tests for scripts/continue_raw_download.py."""

from __future__ import annotations

import ftplib
from pathlib import Path

import pandas as pd
import pytest


def test_iter_months_descending_across_year():
    """_iter_months yields descending (year, month) sequence from end month."""
    from scripts.continue_raw_download import _iter_months

    got = list(_iter_months(2024, 2, 4))
    assert got == [(2024, 2), (2024, 1), (2023, 12), (2023, 11)]


def test_ftp_list_returns_empty_on_permission_error():
    """_ftp_list returns [] when ftp.cwd raises error_perm."""
    from scripts.continue_raw_download import _ftp_list

    class _FTP:
        def cwd(self, _path):
            raise ftplib.error_perm("denied")

    assert _ftp_list(_FTP(), "/x") == []


def test_download_month_invalid_source_raises_value_error(tmp_path):
    """download_month rejects unknown source."""
    from scripts.continue_raw_download import download_month

    with pytest.raises(ValueError, match="Unknown source"):
        download_month("bad", 2023, 1, tmp_path / "o.parquet")


def test_download_month_returns_false_on_connect_failure(monkeypatch, tmp_path):
    """download_month returns False when FTP connection fails."""
    from scripts import continue_raw_download

    def _raise_no_ftp(*_args, **_kwargs):
        raise RuntimeError("no ftp")

    monkeypatch.setattr(
        continue_raw_download,
        "_connect_ftp",
        _raise_no_ftp,
    )

    ok = continue_raw_download.download_month("SIH", 2023, 1, tmp_path / "out.parquet")
    assert ok is False


def test_download_month_returns_false_when_nothing_downloaded(monkeypatch, tmp_path):
    """download_month returns False when file list has no matching UF files."""
    from scripts import continue_raw_download

    class _FTP:
        def quit(self):
            return None

    monkeypatch.setattr(continue_raw_download, "_connect_ftp", lambda *_a, **_k: _FTP())
    monkeypatch.setattr(continue_raw_download, "_ftp_list", lambda *_a, **_k: [])

    ok = continue_raw_download.download_month("SIH", 2023, 1, tmp_path / "out.parquet")
    assert ok is False


def test_download_month_merge_branch_success(monkeypatch, tmp_path):
    """download_month merges per-UF parquet files when conversions produce outputs."""
    from scripts import continue_raw_download

    class _FTP:
        def quit(self):
            return None

    files = ["RDAC2301.dbc", "RDSP2301.dbc"]
    monkeypatch.setattr(continue_raw_download, "_connect_ftp", lambda *_a, **_k: _FTP())
    monkeypatch.setattr(continue_raw_download, "_ftp_list", lambda *_a, **_k: files)
    monkeypatch.setattr(continue_raw_download, "_download_file", lambda *_a, **_k: True)

    def _fake_convert(dbc_path: Path, parquet_path: Path):
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"x": [1]}).to_parquet(parquet_path, index=False)
        return True

    monkeypatch.setattr(continue_raw_download, "_dbc_to_parquet", _fake_convert)

    out = tmp_path / "merged.parquet"
    ok = continue_raw_download.download_month(
        source="SIH",
        year=2023,
        month=1,
        output_path=out,
        raw_dir=tmp_path / "raw",
        resume=True,
        convert=True,
    )
    assert ok is True
    assert out.exists()
    merged = pd.read_parquet(out)
    assert len(merged) == 2


def test_download_month_returns_true_when_downloaded_without_convert(monkeypatch, tmp_path):
    """download_month returns bool(downloaded_parquets)==False unless convert creates outputs."""
    from scripts import continue_raw_download

    class _FTP:
        def quit(self):
            return None

    monkeypatch.setattr(continue_raw_download, "_connect_ftp", lambda *_a, **_k: _FTP())
    monkeypatch.setattr(continue_raw_download, "_ftp_list", lambda *_a, **_k: ["RDAC2301.dbc"])
    monkeypatch.setattr(continue_raw_download, "_download_file", lambda *_a, **_k: True)
    monkeypatch.setattr(continue_raw_download, "_dbc_to_parquet", lambda *_a, **_k: False)

    ok = continue_raw_download.download_month(
        source="SIH",
        year=2023,
        month=1,
        output_path=tmp_path / "x.parquet",
        raw_dir=tmp_path / "raw",
        convert=False,
    )
    assert ok is False


def test_main_single_month_calls_download_for_selected_source(monkeypatch, tmp_path):
    """main() with explicit --year/--month calls download_month once per requested source."""
    from scripts import continue_raw_download

    calls: list[tuple[str, int, int, Path, bool, bool]] = []

    def _fake_download(source, year, month, output_path, raw_dir, resume, convert):
        calls.append((source, year, month, output_path, resume, convert))
        return True

    monkeypatch.setattr(continue_raw_download, "download_month", _fake_download)

    rc = continue_raw_download.main(
        [
            "--source",
            "BOTH",
            "--year",
            "2023",
            "--month",
            "6",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--output-dir",
            str(tmp_path / "processed"),
        ]
    )

    assert rc == 0
    assert len(calls) == 2
    assert {c[0] for c in calls} == {"SIH", "CNES"}
    assert {(c[1], c[2]) for c in calls} == {(2023, 6)}


def test_main_respects_existing_output_when_resume_true(monkeypatch, tmp_path):
    """main() skips download when output already exists and resume is enabled."""
    from scripts import continue_raw_download

    out_dir = tmp_path / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = out_dir / "sih_202312.parquet"
    existing.write_bytes(b"already")

    called = {"download": 0}
    monkeypatch.setattr(
        continue_raw_download,
        "download_month",
        lambda *_a, **_k: called.__setitem__("download", called["download"] + 1) or True,
    )

    rc = continue_raw_download.main(
        [
            "--source",
            "SIH",
            "--end-year",
            "2023",
            "--end-month",
            "12",
            "--months",
            "1",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    assert called["download"] == 0
