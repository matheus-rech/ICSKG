"""
ICSKG-BR STROBE/RECORD Compliance and Submission Statements
=============================================================
Generates STROBE (22-item) and RECORD (13-item) reporting compliance
checklists, an ethics statement citing Brazilian Resolution 510/2016,
and a data availability statement listing all 8+ source portals for
BMJ Global Health submission.

STROBE
------
  Strengthening the Reporting of Observational Studies in Epidemiology.
  22 items for cross-sectional / cohort studies. Every item is populated
  with an ICSKG-BR-specific manuscript section reference.

RECORD
------
  REporting of studies Conducted using Observational Routinely-collected
  health Data.  13 extension items. Every item cross-references the
  corresponding STROBE item.

Outputs
-------
  results/checklists/strobe_checklist.csv
  results/checklists/record_checklist.csv
  results/statements/ethics_statement.txt
  results/statements/data_availability.txt

Usage
-----
    python analysis/strobe_record.py --out-dir results

Exports
-------
    generate_strobe_checklist(out_dir) -> Path
    generate_record_checklist(out_dir) -> Path
    generate_ethics_statement(out_dir) -> Path
    generate_data_availability_statement(out_dir) -> Path
    main(argv) -> int
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# STROBE Checklist (22 items)
# ---------------------------------------------------------------------------

STROBE_ITEMS: list[dict] = [
    {
        "item_number": 1,
        "item_name": "Title and abstract",
        "recommendation": (
            "Indicate the study's design with a commonly used term in "
            "the title or abstract. Provide an informative and balanced "
            "summary of what was done and what was found."
        ),
        "manuscript_section": "Title page",
        "page_reference": "[p. 1]",
        "notes": (
            "Ecological panel study design stated in title: "
            "'longitudinal ecological panel study'"
        ),
    },
    {
        "item_number": 2,
        "item_name": "Abstract",
        "recommendation": (
            "Provide an informative and balanced summary including: "
            "background, objectives, data sources, study population, "
            "outcome measures, results, limitations, conclusions."
        ),
        "manuscript_section": "Abstract",
        "page_reference": "[p. 2]",
        "notes": (
            "Structured abstract per BMJ Global Health guidelines; "
            "50,130-observation panel (5,570 municipalities x 9 years)"
        ),
    },
    {
        "item_number": 3,
        "item_name": "Background/rationale",
        "recommendation": (
            "Explain the scientific background and rationale for the "
            "investigation being reported."
        ),
        "manuscript_section": "Introduction",
        "page_reference": "[Section 1]",
        "notes": (
            "Gap: no prior subnational cross-reference of urban "
            "development composite indices with surgical indicators"
        ),
    },
    {
        "item_number": 4,
        "item_name": "Objectives",
        "recommendation": (
            "State specific objectives, including any prespecified "
            "hypotheses."
        ),
        "manuscript_section": "Introduction",
        "page_reference": "[Section 1]",
        "notes": (
            "Primary: validate CUDS against LCoGS indicators; "
            "dose-response relationship between urban development "
            "and surgical system performance"
        ),
    },
    {
        "item_number": 5,
        "item_name": "Study design",
        "recommendation": (
            "Present key elements of study design early in the paper."
        ),
        "manuscript_section": "Methods: Study Design",
        "page_reference": "[Section 2.1]",
        "notes": (
            "Ecological study design -- all analyses at municipality "
            "level; 2015-2023 panel with two-way fixed effects"
        ),
    },
    {
        "item_number": 6,
        "item_name": "Setting",
        "recommendation": (
            "Describe the setting, locations, and relevant dates, "
            "including periods of recruitment, exposure, follow-up, "
            "and data collection."
        ),
        "manuscript_section": "Methods: Setting",
        "page_reference": "[Section 2.2]",
        "notes": (
            "All 5,570 Brazilian municipalities, 2015-2023; "
            "data from 8+ publicly available government sources"
        ),
    },
    {
        "item_number": 7,
        "item_name": "Participants",
        "recommendation": (
            "Give the eligibility criteria, and the sources and "
            "methods of selection of participants."
        ),
        "manuscript_section": "Methods: Participants",
        "page_reference": "[Section 2.3]",
        "notes": (
            "Unit of analysis: municipalities (not individuals); "
            "complete enumeration of all Brazilian municipalities "
            "via IBGE reference list"
        ),
    },
    {
        "item_number": 8,
        "item_name": "Variables",
        "recommendation": (
            "Clearly define all outcomes, exposures, predictors, "
            "potential confounders, and effect modifiers."
        ),
        "manuscript_section": "Methods: Variables",
        "page_reference": "[Section 2.4]",
        "notes": (
            "Exposure: CUDS (geometric mean of 8 CIMI dimensions); "
            "Outcomes: 6 LCoGS indicators; see Data Dictionary"
        ),
    },
    {
        "item_number": 9,
        "item_name": "Data sources/measurement",
        "recommendation": (
            "For each variable of interest, give sources of data and "
            "details of methods of assessment/measurement."
        ),
        "manuscript_section": "Methods: Data Sources",
        "page_reference": "[Section 2.5]",
        "notes": (
            "DATASUS (SIH/CNES), ANS, FIRJAN IFGF, IBGE SIDRA, "
            "IPEA IDHM, Census 2022, RENAVAM, SIOPS; all public"
        ),
    },
    {
        "item_number": 10,
        "item_name": "Bias",
        "recommendation": (
            "Describe any efforts to address potential sources of bias."
        ),
        "manuscript_section": "Methods: Bias",
        "page_reference": "[Section 2.6]",
        "notes": (
            "Two-way FE controls for time-invariant municipality "
            "confounders and common temporal shocks; cluster-robust "
            "SE for spatial autocorrelation"
        ),
    },
    {
        "item_number": 11,
        "item_name": "Study size",
        "recommendation": (
            "Explain how the study size was arrived at."
        ),
        "manuscript_section": "Methods: Study Size",
        "page_reference": "[Section 2.7]",
        "notes": (
            "Complete enumeration: 5,570 municipalities x 9 years = "
            "50,130 observations; no sampling"
        ),
    },
    {
        "item_number": 12,
        "item_name": "Quantitative variables",
        "recommendation": (
            "Explain how quantitative variables were handled in the "
            "analyses. State groupings and rationale."
        ),
        "manuscript_section": "Methods: Quantitative Variables",
        "page_reference": "[Section 2.8]",
        "notes": (
            "Within-year min-max normalization [0,1]; geometric mean "
            "for CUDS with epsilon=0.01 floor; monetary values "
            "deflated to constant 2023 BRL via IPCA"
        ),
    },
    {
        "item_number": 13,
        "item_name": "Statistical methods",
        "recommendation": (
            "Describe all statistical methods, including those used "
            "to control for confounding. Describe any methods for "
            "examining subgroups and interactions."
        ),
        "manuscript_section": "Methods: Statistical Methods",
        "page_reference": "[Section 2.9]",
        "notes": (
            "PanelOLS two-way FE; RF/XGBoost with SHAP; "
            "EconML DML causal inference; Moran's I spatial "
            "autocorrelation; sensitivity analyses "
            "(arithmetic CUDS, exclude missing dimensions)"
        ),
    },
    {
        "item_number": 14,
        "item_name": "Participants (results)",
        "recommendation": (
            "Report numbers of individuals at each stage of study. "
            "Consider use of a flow diagram."
        ),
        "manuscript_section": "Results: Participants",
        "page_reference": "[Section 3.1]",
        "notes": (
            "Ecological study: N municipalities per year reported; "
            "no individual-level attrition; missingness by source "
            "reported in Table 3"
        ),
    },
    {
        "item_number": 15,
        "item_name": "Descriptive data",
        "recommendation": (
            "Give characteristics of study participants and "
            "information on exposures and confounders."
        ),
        "manuscript_section": "Results: Descriptive Data",
        "page_reference": "[Section 3.2]",
        "notes": (
            "Table 1: descriptive statistics for all variables "
            "by macro-region with mean +/- SD (95%% CI); "
            "Table 2: CIMI dimension descriptives"
        ),
    },
    {
        "item_number": 16,
        "item_name": "Outcome data",
        "recommendation": (
            "Report numbers of outcome events or summary measures."
        ),
        "manuscript_section": "Results: Outcome Data",
        "page_reference": "[Section 3.3]",
        "notes": (
            "6 LCoGS indicators summarised per region; "
            "POMR suppressed for <10 events"
        ),
    },
    {
        "item_number": 17,
        "item_name": "Main results",
        "recommendation": (
            "Give unadjusted estimates and, if applicable, "
            "confounder-adjusted estimates and their precision."
        ),
        "manuscript_section": "Results: Main Results",
        "page_reference": "[Section 3.4]",
        "notes": (
            "Tables 5-8: PanelOLS coefficients with cluster-robust "
            "SE and 95%% CI; Fig 4 forest plot; R-squared within"
        ),
    },
    {
        "item_number": 18,
        "item_name": "Other analyses",
        "recommendation": (
            "Report other analyses done -- subgroup, interaction, "
            "sensitivity analyses."
        ),
        "manuscript_section": "Results: Other Analyses",
        "page_reference": "[Section 3.5]",
        "notes": (
            "Sensitivity: arithmetic CUDS vs geometric; "
            "exclude municipalities with <6 dimension coverage; "
            "ML dose-response (RF + XGBoost SHAP); "
            "causal inference (EconML DML + Causal Forest CATE)"
        ),
    },
    {
        "item_number": 19,
        "item_name": "Key results",
        "recommendation": (
            "Summarise key results with reference to study objectives."
        ),
        "manuscript_section": "Discussion: Key Results",
        "page_reference": "[Section 4.1]",
        "notes": (
            "CUDS-LCoGS dose-response associations and regional "
            "disparities (North-South gradient)"
        ),
    },
    {
        "item_number": 20,
        "item_name": "Limitations",
        "recommendation": (
            "Discuss limitations of the study, taking into account "
            "sources of potential bias or imprecision."
        ),
        "manuscript_section": "Discussion: Limitations",
        "page_reference": "[Section 4.2]",
        "notes": (
            "Ecological fallacy; SUS-funded procedures only; "
            "D3 (IDHM 2010) and D5 (Census 2022) are "
            "cross-sectional -- no genuine temporal variation; "
            "municipality of treatment, not residence; "
            "IFGF MNAR imputation assumptions"
        ),
    },
    {
        "item_number": 21,
        "item_name": "Interpretation",
        "recommendation": (
            "Give a cautious overall interpretation considering "
            "objectives, limitations, multiplicity of analyses, "
            "results from similar studies."
        ),
        "manuscript_section": "Discussion: Interpretation",
        "page_reference": "[Section 4.3]",
        "notes": (
            "Association, not causation; "
            "first subnational cross-reference of CIMI-based "
            "composite with LCoGS surgical indicators"
        ),
    },
    {
        "item_number": 22,
        "item_name": "Generalisability",
        "recommendation": (
            "Discuss the generalisability (external validity) of the "
            "study results."
        ),
        "manuscript_section": "Discussion: Generalisability",
        "page_reference": "[Section 4.4]",
        "notes": (
            "Framework replicable in any country with subnational "
            "administrative health data; results specific to "
            "Brazilian SUS context"
        ),
    },
]


# ---------------------------------------------------------------------------
# RECORD Extension (13 items)
# ---------------------------------------------------------------------------

RECORD_ITEMS: list[dict] = [
    {
        "item_number": 1,
        "record_item": "RECORD 1.1",
        "strobe_item_addressed": "1 (Title and abstract)",
        "recommendation": (
            "The type of data used should be specified in the title "
            "or abstract. When possible, the name of the databases "
            "used should be included."
        ),
        "manuscript_section": "Abstract",
        "page_reference": "[p. 2]",
        "notes": (
            "Title includes 'routinely collected health data'; "
            "abstract names DATASUS, ANS, IBGE as primary sources"
        ),
    },
    {
        "item_number": 2,
        "record_item": "RECORD 1.2",
        "strobe_item_addressed": "1 (Title and abstract)",
        "recommendation": (
            "If applicable, the geographic region and timeframe "
            "within which the study took place should be reported "
            "in the title or abstract."
        ),
        "manuscript_section": "Abstract",
        "page_reference": "[p. 2]",
        "notes": (
            "Title states 'Brazil (2015-2023)'"
        ),
    },
    {
        "item_number": 3,
        "record_item": "RECORD 1.3",
        "strobe_item_addressed": "1 (Title and abstract)",
        "recommendation": (
            "If linkage between databases was conducted for the study, "
            "this should be clearly stated in the title or abstract."
        ),
        "manuscript_section": "Abstract",
        "page_reference": "[p. 2]",
        "notes": (
            "Abstract states: municipality-level linkage of 8+ "
            "government data sources via IBGE municipality code "
            "(cod_ibge)"
        ),
    },
    {
        "item_number": 4,
        "record_item": "RECORD 6.1",
        "strobe_item_addressed": "6 (Setting)",
        "recommendation": (
            "The methods of study population selection should be "
            "listed in detail. If a code list was used to identify "
            "subjects, the full list should be provided."
        ),
        "manuscript_section": "Methods: Data Sources",
        "page_reference": "[Section 2.5]",
        "notes": (
            "Complete enumeration of 5,570 municipalities; "
            "data sources: DATASUS SIH (AIH hospitalisations), "
            "DATASUS CNES (facilities + professionals), "
            "ANS (private insurance), FIRJAN IFGF (fiscal), "
            "IBGE SIDRA (population + GDP), IPEA IDHM, "
            "Census 2022 (sanitation), RENAVAM (vehicle fleet), "
            "SIOPS (health expenditure)"
        ),
    },
    {
        "item_number": 5,
        "record_item": "RECORD 6.2",
        "strobe_item_addressed": "6 (Setting)",
        "recommendation": (
            "Any validation studies of the codes or algorithms "
            "used to select the population should be referenced."
        ),
        "manuscript_section": "Methods: Data Sources",
        "page_reference": "[Section 2.5]",
        "notes": (
            "ICD-10 procedure codes for bellwether classification "
            "based on Lancet Commission definitions; CBO codes "
            "for SAO professional classification; references "
            "provided for each mapping"
        ),
    },
    {
        "item_number": 6,
        "record_item": "RECORD 6.3",
        "strobe_item_addressed": "6 (Setting)",
        "recommendation": (
            "If the study involved linkage of databases, the methods "
            "used and how the quality of linkage was assessed should "
            "be provided."
        ),
        "manuscript_section": "Methods: Data Linkage",
        "page_reference": "[Section 2.5]",
        "notes": (
            "Linkage key: IBGE 7-digit municipality code (cod_ibge); "
            "AMC crosswalk for temporal harmonisation of "
            "municipality boundary changes; scaffold-first merge "
            "strategy preserving all 5,570 municipalities per year"
        ),
    },
    {
        "item_number": 7,
        "record_item": "RECORD 7.1",
        "strobe_item_addressed": "7 (Variables)",
        "recommendation": (
            "A complete list of codes and algorithms used to "
            "classify exposures, outcomes, confounders, and effect "
            "modifiers should be provided."
        ),
        "manuscript_section": "Methods: Variables",
        "page_reference": "[Section 2.4]",
        "notes": (
            "Exposure: CUDS = geometric mean of 8 CIMI dimensions "
            "(D1-D7, D9); D4 inverted; epsilon=0.01 floor; "
            "complete DIMENSION_MAP in supplementary code; "
            "6 LCoGS outcomes defined in Data Dictionary"
        ),
    },
    {
        "item_number": 8,
        "record_item": "RECORD 12.1",
        "strobe_item_addressed": "12 (Quantitative variables)",
        "recommendation": (
            "Authors should describe in detail the methods used to "
            "deal with missing data."
        ),
        "manuscript_section": "Results: Missing Data",
        "page_reference": "[Section 3.1]",
        "notes": (
            "Table 3 provides per-variable per-year missingness; "
            "IFGF MNAR imputation via IterativeImputer "
            "(BayesianRidge, m=5, Rubin's rules pooling); "
            "D3 (IDHM) and D5 (Census) are cross-sectional "
            "(no temporal missingness); POMR suppressed for <10 "
            "surgical events"
        ),
    },
    {
        "item_number": 9,
        "record_item": "RECORD 12.2",
        "strobe_item_addressed": "12 (Quantitative variables)",
        "recommendation": (
            "The methods used to determine completeness/accuracy "
            "of the data should be described."
        ),
        "manuscript_section": "Methods: Data Quality",
        "page_reference": "[Section 2.6]",
        "notes": (
            "Validation gate: validate_dataframe() checks dtype, "
            "range, duplicates, cod_ibge coverage per source; "
            "quarantine mechanism for failed rows; "
            "row-count invariant asserted per year"
        ),
    },
    {
        "item_number": 10,
        "record_item": "RECORD 13.1",
        "strobe_item_addressed": "13 (Statistical methods)",
        "recommendation": (
            "Describe the extent to which the investigators had "
            "access to the database population used to create "
            "the study population."
        ),
        "manuscript_section": "Methods: Data Access",
        "page_reference": "[Section 2.5]",
        "notes": (
            "All data publicly available under Lei de Acesso a "
            "Informacao (Law 12.527/2011); full population "
            "coverage (no sampling); no restricted access required"
        ),
    },
    {
        "item_number": 11,
        "record_item": "RECORD 19.1",
        "strobe_item_addressed": "19 (Key results, Discussion)",
        "recommendation": (
            "Discuss the implications of using data that were not "
            "created or collected to answer the specific research "
            "question(s). Include discussion of misclassification "
            "bias, unmeasured confounding, missing data, and "
            "changing eligibility over time."
        ),
        "manuscript_section": "Discussion: Data Quality",
        "page_reference": "[Section 4.2]",
        "notes": (
            "Administrative data limitations: SUS-funded only; "
            "IFGF MNAR ~420 municipalities/year; "
            "municipality of treatment not residence; "
            "ecological fallacy; D3/D5 cross-sectional limitation"
        ),
    },
    {
        "item_number": 12,
        "record_item": "RECORD 22.1",
        "strobe_item_addressed": "22 (Generalisability)",
        "recommendation": (
            "Authors should provide information on how to access "
            "any supplemental information, such as the study "
            "protocol, raw data, or programming code."
        ),
        "manuscript_section": "Other: Data Availability",
        "page_reference": "[Section 5]",
        "notes": (
            "GitHub repository with full reproducibility pipeline; "
            "Zenodo DOI for archived database; "
            "all raw data from public portals listed in "
            "Data Availability Statement"
        ),
    },
    {
        "item_number": 13,
        "record_item": "RECORD 22.2",
        "strobe_item_addressed": "22 (Generalisability)",
        "recommendation": (
            "Authors should provide information on the data "
            "cleaning and linkage procedures."
        ),
        "manuscript_section": "Methods: Data Linkage",
        "page_reference": "[Section 2.5]",
        "notes": (
            "Pipeline documented in GitHub: extraction -> "
            "validation -> deflation -> scaffold-first merge -> "
            "imputation -> dimension computation; "
            "AMC crosswalk for temporal harmonisation"
        ),
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_strobe_checklist(out_dir: Path) -> Path:
    """Generate STROBE 22-item checklist as CSV.

    Parameters
    ----------
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved CSV file.
    """
    out_dir = Path(out_dir)
    checklists_dir = out_dir / "checklists"
    checklists_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(STROBE_ITEMS)
    csv_path = checklists_dir / "strobe_checklist.csv"
    df.to_csv(csv_path, index=False)

    logger.info(
        "generate_strobe_checklist: %d items saved to %s",
        len(df), csv_path,
    )
    return csv_path


def generate_record_checklist(out_dir: Path) -> Path:
    """Generate RECORD 13-item extension checklist as CSV.

    Parameters
    ----------
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved CSV file.
    """
    out_dir = Path(out_dir)
    checklists_dir = out_dir / "checklists"
    checklists_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(RECORD_ITEMS)
    csv_path = checklists_dir / "record_checklist.csv"
    df.to_csv(csv_path, index=False)

    logger.info(
        "generate_record_checklist: %d items saved to %s",
        len(df), csv_path,
    )
    return csv_path


def generate_ethics_statement(out_dir: Path) -> Path:
    """Generate ethics statement citing Brazilian Resolution 510/2016.

    The ICSKG-BR study uses publicly available, aggregated,
    non-identifiable municipal-level data and is therefore exempt
    from ethics committee review under Brazilian regulations.

    Parameters
    ----------
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved text file.
    """
    out_dir = Path(out_dir)
    statements_dir = out_dir / "statements"
    statements_dir.mkdir(parents=True, exist_ok=True)

    text = (
        "Ethics Statement\n"
        "================\n\n"
        "This study used exclusively publicly available, aggregated, "
        "municipality-level data from Brazilian government sources. No "
        "individual-level data were accessed, processed, or analysed at "
        "any stage of this research. All data are aggregated at the "
        "municipality level (N = 5,570 municipalities).\n\n"
        "Under Brazilian National Health Council Resolution 510/2016 "
        "(Resolucao CNS 510/2016), research that uses publicly available "
        "information in aggregated form, without the possibility of "
        "individual identification, is exempt from review by a Research "
        "Ethics Committee (Comite de Etica em Pesquisa -- CEP). "
        "Accordingly, ethics committee approval was not required for "
        "this study.\n\n"
        "All data sources used in this study are made available by "
        "Brazilian federal government agencies under the Lei de Acesso "
        "a Informacao (Law 12.527/2011 -- Freedom of Information Act), "
        "which guarantees public access to government-produced data.\n\n"
        "Data sources include: DATASUS (SIH hospitalisation records, "
        "CNES facility and professional registries), Agencia Nacional "
        "de Saude Suplementar (ANS), Federacao das Industrias do Estado "
        "do Rio de Janeiro (FIRJAN/IFGF), Instituto Brasileiro de "
        "Geografia e Estatistica (IBGE/SIDRA, Census 2022), Instituto "
        "de Pesquisa Economica Aplicada (IPEA/IDHM), Registro Nacional "
        "de Veiculos Automotores (RENAVAM), and Sistema de Informacoes "
        "sobre Orcamentos Publicos em Saude (SIOPS).\n\n"
        "No patients or human subjects were involved in this study. "
        "All analyses were performed on municipality-level aggregates "
        "that cannot be linked to any individual.\n"
    )

    txt_path = statements_dir / "ethics_statement.txt"
    txt_path.write_text(text, encoding="utf-8")

    logger.info(
        "generate_ethics_statement: saved to %s", txt_path,
    )
    return txt_path


def generate_data_availability_statement(out_dir: Path) -> Path:
    """Generate data availability statement with all source portal URLs.

    Lists all 10 data source portals used in the ICSKG-BR study with
    their access URLs and a statement about code and database archival.

    Parameters
    ----------
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved text file.
    """
    out_dir = Path(out_dir)
    statements_dir = out_dir / "statements"
    statements_dir.mkdir(parents=True, exist_ok=True)

    text = (
        "Data Availability Statement\n"
        "===========================\n\n"
        "All data used in this study are publicly available from "
        "Brazilian government agencies. The specific data sources and "
        "their access points are:\n\n"
        "1. DATASUS/SIH (Sistema de Informacoes Hospitalares):\n"
        "   ftp://ftp.datasus.gov.br/dissemin/publicos/SIHSUS/\n\n"
        "2. DATASUS/CNES (Cadastro Nacional de Estabelecimentos de Saude):\n"
        "   ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/\n\n"
        "3. ANS (Agencia Nacional de Saude Suplementar):\n"
        "   https://dados.ans.gov.br/\n\n"
        "4. FIRJAN/IFGF (Indice FIRJAN de Gestao Fiscal):\n"
        "   https://www.firjan.com.br/ifgf/\n\n"
        "5. IBGE SIDRA (Population and GDP):\n"
        "   https://sidra.ibge.gov.br/\n\n"
        "6. IPEA (Instituto de Pesquisa Economica Aplicada -- IDHM):\n"
        "   http://www.ipeadata.gov.br/\n\n"
        "7. IBGE Census 2022 (Sanitation indicators):\n"
        "   https://censo2022.ibge.gov.br/panorama/\n\n"
        "8. RENAVAM (Vehicle fleet data):\n"
        "   https://dados.transportes.gov.br/\n\n"
        "9. SIOPS (Health expenditure):\n"
        "   https://portalfns.saude.gov.br/\n\n"
        "10. IBGE Geobr (Municipality shapefiles and centroids):\n"
        "    https://github.com/ipeaGIT/geobr\n\n"
        "The complete analysis code and reproducibility pipeline are "
        "available at [GitHub URL]. The assembled database is archived "
        "at [Zenodo DOI].\n"
    )

    txt_path = statements_dir / "data_availability.txt"
    txt_path.write_text(text, encoding="utf-8")

    logger.info(
        "generate_data_availability_statement: saved to %s", txt_path,
    )
    return txt_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Generate STROBE/RECORD checklists and submission statements.

    Usage
    -----
        python analysis/strobe_record.py --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR STROBE/RECORD compliance and statements",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory (default: results)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)

    logger.info("=" * 60)
    logger.info("STROBE/RECORD COMPLIANCE AND SUBMISSION STATEMENTS")
    logger.info("=" * 60)

    strobe_path = generate_strobe_checklist(out_dir)
    record_path = generate_record_checklist(out_dir)
    ethics_path = generate_ethics_statement(out_dir)
    data_avail_path = generate_data_availability_statement(out_dir)

    logger.info("─" * 60)
    logger.info("Outputs:")
    logger.info("  STROBE checklist:  %s", strobe_path)
    logger.info("  RECORD checklist:  %s", record_path)
    logger.info("  Ethics statement:  %s", ethics_path)
    logger.info("  Data availability: %s", data_avail_path)
    logger.info("─" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
