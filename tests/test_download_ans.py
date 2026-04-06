"""Tests for scripts/download_ans.py."""

from __future__ import annotations

from pathlib import Path
import sys
import types

import pandas as pd
import pytest


def test_build_filename_and_url():
    """Filename and URL helpers produce expected format."""
    from scripts.download_ans import _build_filename, _build_url

    assert _build_filename(2023, 12) == "202312_Beneficiarios_por_municipio.csv"
    assert _build_url(2023, 12).endswith("/202312_Beneficiarios_por_municipio.csv")


def test_get_with_retry_succeeds_after_retries(monkeypatch):
    """_get_with_retry retries and eventually returns content."""
    from scripts import download_ans

    calls: list[str] = []

    class _Resp:
        content = b"ok"

        def raise_for_status(self):
            return None

    class _Session:
        def get(self, *_args, **_kwargs):
            calls.append("get")
            if len(calls) < 3:
                raise RuntimeError("temporary failure")
            return _Resp()

    monkeypatch.setattr(download_ans.time, "sleep", lambda *_args, **_kwargs: None)
    fake_requests = types.SimpleNamespace(Session=lambda: _Session())
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    data = download_ans._get_with_retry("https://example.test/file.csv")
    assert data == b"ok"
    assert len(calls) == 3


def test_download_competence_skip_existing(tmp_path):
    """download_competence returns existing file without download."""
    from scripts.download_ans import download_competence

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    existing = raw_dir / "202312_Beneficiarios_por_municipio.csv"
    existing.write_bytes(b"cached")

    got = download_competence(2023, 12, raw_dir=raw_dir, skip_existing=True)
    assert got == existing


def test_download_competence_returns_none_on_runtimeerror(monkeypatch, tmp_path):
    """download_competence returns None when HTTP helper fails."""
    from scripts import download_ans

    monkeypatch.setattr(
        download_ans,
        "_get_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    got = download_ans.download_competence(2023, 12, raw_dir=tmp_path)
    assert got is None


def test_parse_csv_normalizes_columns_and_numeric(tmp_path):
    """parse_csv normalizes municipality/beneficiary columns and parses numbers."""
    from scripts.download_ans import parse_csv

    csv_path = tmp_path / "ans.csv"
    csv_path.write_text(
        "CD_MUN;QT_BENEF\n355030;1.234\n120020;56\n",
        encoding="latin-1",
    )
    df = parse_csv(csv_path)
    assert "CD_MUNICIPIO" in df.columns
    assert "BENEFICIARIOS" in df.columns
    assert df["BENEFICIARIOS"].tolist() == [1234, 56]


def test_merge_downloads_writes_parquet_and_adds_competence_columns(tmp_path):
    """merge_downloads concatenates parsed files and writes parquet with comp columns."""
    from scripts.download_ans import merge_downloads

    p1 = tmp_path / "202303_Beneficiarios_por_municipio.csv"
    p2 = tmp_path / "202306_Beneficiarios_por_municipio.csv"
    p1.write_text("CD_MUNICIPIO;BENEFICIARIOS\n355030;100\n", encoding="latin-1")
    p2.write_text("CD_MUNICIPIO;BENEFICIARIOS\n355030;200\n", encoding="latin-1")
    out = tmp_path / "merged.parquet"

    n = merge_downloads([p1, p2], out)
    assert n == 2
    assert out.exists()
    merged = pd.read_parquet(out)
    assert {"comp_year", "comp_month"}.issubset(set(merged.columns))
    assert set(merged["comp_month"].tolist()) == {3, 6}


def test_merge_downloads_returns_zero_when_all_parses_fail(monkeypatch, tmp_path):
    """merge_downloads returns 0 when no frame is parseable."""
    from scripts import download_ans

    p1 = tmp_path / "202303_Beneficiarios_por_municipio.csv"
    p1.write_text("x", encoding="latin-1")
    monkeypatch.setattr(
        download_ans,
        "parse_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad")),
    )
    n = download_ans.merge_downloads([p1], tmp_path / "out.parquet")
    assert n == 0


def test_download_latest_fallback_then_success(monkeypatch, tmp_path):
    """download_latest searches backwards by quarter and writes parquet on success."""
    from scripts import download_ans

    class _Date:
        @classmethod
        def today(cls):
            return type("_D", (), {"year": 2026})()

    monkeypatch.setattr(
        download_ans,
        "datetime",
        type("_DT", (), {"date": _Date}),
        raising=False,
    )

    attempts: list[tuple[int, int]] = []
    csv_path = tmp_path / "202509_Beneficiarios_por_municipio.csv"
    csv_path.write_text("CD_MUNICIPIO;BENEFICIARIOS\n355030;10\n", encoding="latin-1")

    def _fake_download(year, month, *_args, **_kwargs):
        attempts.append((year, month))
        if (year, month) == (2025, 12):
            return None
        if (year, month) == (2025, 9):
            return csv_path
        return None

    monkeypatch.setattr(download_ans, "download_competence", _fake_download)
    monkeypatch.setattr(
        download_ans,
        "parse_csv",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"CD_MUNICIPIO": ["355030"], "BENEFICIARIOS": [10]}
        ),
    )

    out = tmp_path / "latest.parquet"
    ok = download_ans.download_latest(out, raw_dir=tmp_path / "raw")
    assert ok is True
    assert out.exists()
    assert attempts[:2] == [(2025, 12), (2025, 9)]


def test_download_latest_returns_false_on_conversion_error(monkeypatch, tmp_path):
    """download_latest returns False when parse/convert fails."""
    from scripts import download_ans

    csv_path = tmp_path / "202512_Beneficiarios_por_municipio.csv"
    csv_path.write_text("CD_MUNICIPIO;BENEFICIARIOS\n355030;10\n", encoding="latin-1")

    monkeypatch.setattr(download_ans, "download_competence", lambda *_args, **_kwargs: csv_path)
    monkeypatch.setattr(
        download_ans,
        "parse_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("parse failed")),
    )

    ok = download_ans.download_latest(tmp_path / "latest.parquet", raw_dir=tmp_path / "raw")
    assert ok is False


def test_iter_months_inclusive():
    """_iter_months yields an inclusive month sequence across year boundaries."""
    from scripts.download_ans import _iter_months

    got = list(_iter_months("2023-11", "2024-02"))
    assert got == [(2023, 11), (2023, 12), (2024, 1), (2024, 2)]


def test_main_with_start_end_and_merge(monkeypatch, tmp_path):
    """main() processes requested range and calls merge on downloaded files."""
    from scripts import download_ans

    downloaded: list[Path] = []
    merged: list[tuple[list[Path], Path]] = []

    def _fake_download(year, month, raw_dir, skip_existing=True):
        p = raw_dir / f"{year:04d}{month:02d}_Beneficiarios_por_municipio.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("CD_MUNICIPIO;BENEFICIARIOS\n355030;1\n", encoding="latin-1")
        downloaded.append(p)
        return p

    def _fake_merge(paths, output):
        merged.append((paths, output))
        return len(paths)

    monkeypatch.setattr(download_ans, "download_competence", _fake_download)
    monkeypatch.setattr(download_ans, "merge_downloads", _fake_merge)

    rc = download_ans.main(
        [
            "--start",
            "2023-01",
            "--end",
            "2023-03",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--merge",
            "--merge-output",
            str(tmp_path / "out.parquet"),
        ]
    )
    assert rc == 0
    assert len(downloaded) == 3
    assert len(merged) == 1
    assert len(merged[0][0]) == 3


def test_main_year_quarterly_only(monkeypatch, tmp_path):
    """main() with --year and --quarterly-only processes only 4 quarter months."""
    from scripts import download_ans

    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        download_ans,
        "download_competence",
        lambda y, m, *_args, **_kwargs: calls.append((y, m)) or (tmp_path / f"{y}{m}.csv"),
    )

    rc = download_ans.main(
        [
            "--year",
            "2020",
            "--quarterly-only",
            "--raw-dir",
            str(tmp_path / "raw"),
        ]
    )
    assert rc == 0
    assert calls == [(2020, 3), (2020, 6), (2020, 9), (2020, 12)]
