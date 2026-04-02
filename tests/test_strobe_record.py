"""Tests for STROBE/RECORD checklists and submission statements."""

import json
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# STROBE checklist tests
# ---------------------------------------------------------------------------


def test_strobe_has_22_items(tmp_path: Path) -> None:
    """STROBE checklist CSV must have exactly 22 rows."""
    from analysis.strobe_record import generate_strobe_checklist

    csv_path = generate_strobe_checklist(tmp_path)
    df = pd.read_csv(csv_path)
    assert len(df) == 22, "STROBE checklist must have 22 items, got %d" % len(df)


def test_record_has_13_items(tmp_path: Path) -> None:
    """RECORD extension CSV must have exactly 13 rows."""
    from analysis.strobe_record import generate_record_checklist

    csv_path = generate_record_checklist(tmp_path)
    df = pd.read_csv(csv_path)
    assert len(df) == 13, "RECORD checklist must have 13 items, got %d" % len(df)


def test_no_blank_manuscript_sections_strobe(tmp_path: Path) -> None:
    """Every STROBE item must have a non-empty manuscript_section."""
    from analysis.strobe_record import generate_strobe_checklist

    csv_path = generate_strobe_checklist(tmp_path)
    df = pd.read_csv(csv_path)
    blanks = df["manuscript_section"].isna() | (
        df["manuscript_section"].str.strip() == ""
    )
    assert not blanks.any(), (
        "STROBE checklist has blank manuscript_section in rows: %s"
        % df[blanks]["item_number"].tolist()
    )


def test_no_blank_manuscript_sections_record(tmp_path: Path) -> None:
    """Every RECORD item must have a non-empty manuscript_section."""
    from analysis.strobe_record import generate_record_checklist

    csv_path = generate_record_checklist(tmp_path)
    df = pd.read_csv(csv_path)
    blanks = df["manuscript_section"].isna() | (
        df["manuscript_section"].str.strip() == ""
    )
    assert not blanks.any(), (
        "RECORD checklist has blank manuscript_section in rows: %s"
        % df[blanks]["item_number"].tolist()
    )


# ---------------------------------------------------------------------------
# Ethics statement tests
# ---------------------------------------------------------------------------


def test_ethics_statement_cites_resolution_510(tmp_path: Path) -> None:
    """Ethics statement must cite Brazilian Resolution 510/2016."""
    from analysis.strobe_record import generate_ethics_statement

    txt_path = generate_ethics_statement(tmp_path)
    text = txt_path.read_text(encoding="utf-8")
    assert "510/2016" in text, "Ethics statement must cite Resolution 510/2016"


def test_ethics_statement_cites_law_12527(tmp_path: Path) -> None:
    """Ethics statement must cite Lei de Acesso a Informacao."""
    from analysis.strobe_record import generate_ethics_statement

    txt_path = generate_ethics_statement(tmp_path)
    text = txt_path.read_text(encoding="utf-8")
    assert "12.527/2011" in text, (
        "Ethics statement must cite Law 12.527/2011"
    )


# ---------------------------------------------------------------------------
# Data availability statement tests
# ---------------------------------------------------------------------------


def test_data_availability_has_all_portals(tmp_path: Path) -> None:
    """Data availability statement must list at least 8 source portal URLs."""
    from analysis.strobe_record import generate_data_availability_statement

    txt_path = generate_data_availability_statement(tmp_path)
    text = txt_path.read_text(encoding="utf-8")

    required_urls = [
        "ftp://ftp.datasus.gov.br",
        "dados.ans.gov.br",
        "firjan.com.br",
        "sidra.ibge.gov.br",
        "ipeadata.gov.br",
        "censo2022.ibge.gov.br",
        "dados.transportes.gov.br",
        "portalfns.saude.gov.br",
    ]

    found = [url for url in required_urls if url in text]
    assert len(found) >= 8, (
        "Data availability must list 8+ portal URLs; found %d: %s"
        % (len(found), found)
    )


# ---------------------------------------------------------------------------
# Zenodo metadata tests
# ---------------------------------------------------------------------------


def test_zenodo_metadata_valid_json(tmp_path: Path) -> None:
    """Zenodo metadata must be valid JSON with required fields."""
    from analysis.zenodo_prep import generate_zenodo_metadata

    json_path = generate_zenodo_metadata(tmp_path)
    with open(json_path) as f:
        data = json.load(f)

    assert "title" in data, "Zenodo metadata must have 'title'"
    assert "upload_type" in data, "Zenodo metadata must have 'upload_type'"
    assert "creators" in data, "Zenodo metadata must have 'creators'"
    assert "keywords" in data, "Zenodo metadata must have 'keywords'"
    assert "license" in data, "Zenodo metadata must have 'license'"
    assert data["license"] == "CC-BY-4.0"


def test_zenodo_metadata_has_keywords(tmp_path: Path) -> None:
    """Zenodo metadata must include relevant keywords."""
    from analysis.zenodo_prep import generate_zenodo_metadata

    json_path = generate_zenodo_metadata(tmp_path)
    with open(json_path) as f:
        data = json.load(f)

    keywords = data.get("keywords", [])
    assert "global surgery" in keywords
    assert "Brazil" in keywords
    assert "CUDS" in keywords


def test_release_checklist_has_steps(tmp_path: Path) -> None:
    """Release checklist must have actionable steps."""
    from analysis.zenodo_prep import generate_release_checklist

    md_path = generate_release_checklist(tmp_path)
    text = md_path.read_text(encoding="utf-8")

    assert "zenodo.org" in text.lower(), "Checklist must mention Zenodo"
    assert "git tag" in text, "Checklist must include git tag step"
    assert "v1.0.0" in text, "Checklist must reference version tag"
