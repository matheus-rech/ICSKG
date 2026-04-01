# Phase 1: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-01
**Phase:** 01-foundation
**Areas discussed:** Municipality codes, Project structure, Validation strictness, NAS integration, CNES source, PolisPCDaS dataset

---

## Municipality Codes

| Option | Description | Selected |
|--------|-------------|----------|
| 7-digit (Recommended) | Full IBGE code with check digit. Most sources use this natively. | ✓ |
| 6-digit | Truncated code without check digit. Some SIH fields use this. | |
| You decide | Claude picks based on source analysis | |

**User's choice:** 7-digit (Recommended)
**Notes:** Current codebase mixes both formats — extract_lcogs1.py uses 6-digit, analysis pipeline uses 7-digit.

---

## Project Structure

| Option | Description | Selected |
|--------|-------------|----------|
| database/utils.py | Keeps utilities close to pipeline. Minimal restructuring. | |
| icskg/utils.py | New top-level package. Cleaner separation but more restructuring. | |
| You decide | Claude picks based on existing patterns | ✓ |

**User's choice:** You decide
**Notes:** Claude has discretion on where shared utilities live.

---

## Validation Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Quarantine + continue | Move bad rows to quarantine/, log warnings, pipeline always completes. | |
| Fail hard | Halt pipeline with clear error. Forces manual review. | |
| Configurable | Default to quarantine, --strict flag to fail hard. | ✓ |

**User's choice:** Configurable
**Notes:** Best of both for development vs production runs.

---

## NAS Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Environment variable | ICSKG_NAS_PATH env var. Default to data_sources/raw/ if unset. | |
| CLI argument | --nas-path flag on pipeline commands. | |
| Config file | A .env or config.yaml with paths. Keeps all settings in one place. | ✓ |

**User's choice:** Config file
**Notes:** All downloaded and processed data goes to NAS due to storage constraints. NAS is a Synology at smb://synology-rech._smb._tcp.local/docker/Downloads.

---

## CNES Source (user-initiated)

**User's input:** CNES data must be downloaded from FIOCRUZ BigData: https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/CNES/ETLCNES.zip (not PySUS/DATASUS FTP)

| Option | Description | Selected |
|--------|-------------|----------|
| Already downloaded | Pipeline just reads/parses from local path | |
| Pipeline downloads | Auto-download from FIOCRUZ URL | |
| Both options | Config for local path OR auto-download if not present | ✓ |

**User's choice:** Both options

---

## PolisPCDaS Dataset (user-initiated)

**User's input:** Recommended additional dataset from https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/PolisPCDaS/PolisPCDaS.zip — pre-aggregated municipal-level indicators covering mortality, maternal-child health, health infrastructure, education, sanitation.

**Notes:** Rich supplementary/validation source. Integration deferred to Phase 3.

---

## Claude's Discretion

- Project structure (database/utils.py vs new package)
- Config file format (.env vs config.yaml)
- AMC crosswalk source
- Validation check thresholds

## Deferred Ideas

- PolisPCDaS integration → Phase 3
- CNES ETLCNES.zip download/parsing → Phase 2
- SIOPS and RENAVAM format discovery → Phase 3
