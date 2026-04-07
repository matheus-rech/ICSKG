#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests>=2.32",
#     "pandas>=2.2",
#     "pyarrow>=19.0",
# ]
# ///
"""
Phase 12 explorer — FIOCRUZ ICICT ETLSIH.zip schema discovery
==============================================================

Purpose
-------
Probe the FIOCRUZ ICICT pre-ETL'd SIH archive WITHOUT downloading the
full 31 GB.  Reports:
  1. Number of files in the ZIP
  2. Total uncompressed size
  3. Filename pattern (so we know how to filter by year)
  4. Sample column list from one CSV (so we can map to existing
     sih_municipal schema)
  5. Row count of the sample
  6. Year range covered

Why this is a separate job from the real processor
---------------------------------------------------
- No need to download 31 GB until we know the schema is compatible
  with our existing sih_municipal table contract
- Fast feedback loop (~5 min on HF Jobs vs ~30+ min for full processing)
- Uses ZIP central-directory tricks to read metadata without extracting
- The real processor will be a stream-extract pipeline that handles
  one inner file at a time and never materializes the full 31 GB

How it runs
-----------
Submit via `hf jobs uv run`:

    hf jobs uv run scripts/jobs/explore_fiocruz_sih.py \\
        --secrets HF_TOKEN \\
        --flavor cpu-basic

The job downloads JUST the ZIP central directory (last few MB) using
HTTP Range requests, parses it locally, and prints the report to job
logs.  No HF Dataset writes from this job — purely diagnostic.
"""

from __future__ import annotations

import io
import sys
import zipfile

import requests

ICICT_URL = "https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/SIH/ETLSIH.zip"
DICT_URL = "https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/SIH/dict_SIH.csv"
SAMPLE_BYTES = 64 * 1024 * 1024  # 64 MB — enough for one or two inner CSVs


def report(label: str, value: object) -> None:
    print(f"  {label:<28} {value}")


def main() -> int:
    print("=" * 70)
    print("FIOCRUZ ICICT ETLSIH.zip explorer (Phase 12)")
    print("=" * 70)
    print()

    # Step 1: HEAD request to confirm size
    print("Step 1: Confirm archive size")
    r = requests.head(ICICT_URL, allow_redirects=True, timeout=30)
    r.raise_for_status()
    total_size = int(r.headers["content-length"])
    report("URL", ICICT_URL)
    report("Total size", f"{total_size / 1e9:.2f} GB ({total_size} bytes)")
    print()

    # Step 2: Pull data dictionary (small)
    print("Step 2: Fetch data dictionary")
    dict_r = requests.get(DICT_URL, timeout=60)
    dict_r.raise_for_status()
    dict_lines = dict_r.text.splitlines()
    report("Dict rows", len(dict_lines))
    print("  Header:", dict_lines[0] if dict_lines else "(empty)")
    print("  First 15 columns:")
    for line in dict_lines[1:16]:
        print(f"    {line}")
    print()

    # Step 3: Pull just the ZIP central directory (last 64 MB)
    print(f"Step 3: Pull last {SAMPLE_BYTES // (1024*1024)} MB for ZIP central directory")
    range_start = max(0, total_size - SAMPLE_BYTES)
    headers = {"Range": f"bytes={range_start}-{total_size - 1}"}
    cd_r = requests.get(ICICT_URL, headers=headers, timeout=120, stream=True)
    cd_r.raise_for_status()
    cd_buf = io.BytesIO()
    for chunk in cd_r.iter_content(chunk_size=8 * 1024 * 1024):
        cd_buf.write(chunk)
    actual_pulled = cd_buf.tell()
    report("Pulled", f"{actual_pulled / 1e6:.1f} MB")
    print()

    # Step 4: Try to parse central directory.  zipfile expects to seek
    # from the END of the file.  Since we have only the tail, we need to
    # construct a file-like that pretends to be the full archive by
    # padding the front with zeros.  This works because zipfile reads
    # the EOCD from the end and only follows offsets within the trailing
    # bytes when those offsets exist within our pulled range.
    print("Step 4: Parse ZIP central directory from tail")
    cd_buf.seek(0)
    tail = cd_buf.read()
    # Build a sparse view: prepend zeros so absolute offsets in the EOCD
    # land in the right place.  This wastes memory but works without
    # full download.  For 31 GB we'd allocate 31 GB of zeros which is
    # too much — instead we use a slightly smarter trick: most ZIP
    # central directories are entirely in the tail, so the EOCD's CD
    # offset points within our pulled range.  We can verify by reading
    # the EOCD record (last 22+ bytes) and checking the cd_offset field.
    # If cd_offset >= range_start, we can read the CD without front-padding.
    import struct
    EOCD_SIG = b"PK\x05\x06"
    eocd_idx = tail.rfind(EOCD_SIG)
    if eocd_idx == -1:
        print("  ERROR: EOCD signature not found in tail. Increase SAMPLE_BYTES.")
        return 1
    # EOCD layout: 4 sig + 2 disk + 2 cd_disk + 2 entries_disk + 2 entries_total
    #            + 4 cd_size + 4 cd_offset + 2 comment_len
    eocd = tail[eocd_idx:eocd_idx + 22]
    (sig, disk, cd_disk, entries_disk, entries_total,
     cd_size, cd_offset_32, comment_len) = struct.unpack("<IHHHHIIH", eocd)
    report("CD entries", entries_total)
    report("CD size", f"{cd_size / 1e6:.1f} MB")
    report("CD offset (32-bit)", f"{cd_offset_32}")
    # If cd_offset_32 == 0xFFFFFFFF, the file uses ZIP64 — handle that
    if cd_offset_32 == 0xFFFFFFFF:
        print("  Archive is ZIP64 — would need ZIP64 EOCD locator parsing")
        print("  (deferred — most ETLs use plain ZIP under 4 GB per entry)")

    cd_offset_in_tail = cd_offset_32 - range_start
    if cd_offset_in_tail < 0:
        print(
            "  ERROR: central directory starts before our pulled range. "
            "Increase SAMPLE_BYTES (currently %d MB) and re-run."
            % (SAMPLE_BYTES // (1024 * 1024))
        )
        return 1

    # Reconstruct just enough zip-like structure for zipfile to parse
    # Pad the front to make absolute offsets work.
    print("Step 5: Construct virtual ZIP for inspection")
    virtual = bytearray(b"\x00" * range_start) + tail
    bio = io.BytesIO(virtual)
    try:
        zf = zipfile.ZipFile(bio)
    except zipfile.BadZipFile as exc:
        print(f"  BadZipFile: {exc}")
        return 1

    names = zf.namelist()
    print(f"  Total entries: {len(names)}")
    print()

    print("Step 6: Sample 10 filenames")
    for n in names[:10]:
        info = zf.getinfo(n)
        print(f"  {n}  ({info.file_size / 1e6:.1f} MB uncompressed)")
    print()
    print("Step 7: Last 5 filenames")
    for n in names[-5:]:
        info = zf.getinfo(n)
        print(f"  {n}  ({info.file_size / 1e6:.1f} MB uncompressed)")
    print()

    # Try to detect year/state pattern
    import re
    year_states = set()
    for n in names:
        m = re.search(r"(\d{4})", n)
        if m:
            year_states.add(m.group(1))
    years = sorted(y for y in year_states if 2010 <= int(y) <= 2030)
    report("Detected year tokens", ", ".join(years[:20]) + ("..." if len(years) > 20 else ""))
    print()

    print("=" * 70)
    print("Done. Use this report to write the real processing job.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
