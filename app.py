"""
Price Update Automation Tool
=============================

Streamlit app that validates a Marketplace Campaign Submission Report against a
Master Input File (Google Sheet), matching on Seller SKU and checking RRP and SRP.

Run locally:
    streamlit run app.py

Deploy: push this repo to GitHub and connect it in Streamlit Community Cloud
(share.streamlit.io) -> New app -> select repo/branch -> main file path: app.py
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src.data_loader import DataLoadError, MarketplaceReportLoader, MasterInputLoader
from src.report_builder import ExcelReportBuilder, build_summary
from src.validator import MarketplaceColumnMap, MasterColumnMap, PriceValidator

st.set_page_config(page_title="Price Update Automation Tool", page_icon="💲", layout="wide")


def _get_service_account_info() -> dict | None:
    """Read a Google service account JSON from Streamlit secrets, if configured."""
    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])
    return None


def _column_picker(label: str, options: list[str], key: str, allow_none: bool = False) -> str | None:
    choices = (["-- None --"] if allow_none else []) + options
    selection = st.selectbox(label, choices, key=key)
    if allow_none and selection == "-- None --":
        return None
    return selection


def main() -> None:
    st.title("💲 Price Update Automation Tool")
    st.caption(
        "Validate RRP and SRP in the Marketplace Campaign Submission Report against "
        "the Master Input File, matched by Seller SKU."
    )

    with st.sidebar:
        st.header("1. Marketplace Report")
        marketplace_file = st.file_uploader(
            "Upload the Marketplace Campaign Submission Report (.xlsx)", type=["xlsx"]
        )

        st.header("2. Master Input File")
        sheet_url = st.text_input("Google Sheet link")
        worksheet_name = st.text_input(
            "Worksheet/tab name (optional, service-account mode only)", value=""
        )

    if not marketplace_file or not sheet_url:
        st.info("Upload the Marketplace Report and provide the Master Input Google Sheet link to begin.")
        return

    # --- Load Marketplace Report ---------------------------------------------------
    marketplace_bytes = marketplace_file.getvalue()
    try:
        sheet_names = MarketplaceReportLoader.list_sheet_names(marketplace_bytes)
    except DataLoadError as exc:
        st.error(str(exc))
        return

    st.subheader("Marketplace Report settings")
    col1, col2 = st.columns(2)
    with col1:
        mkt_sheet_name = st.selectbox("Sheet to read", sheet_names)
    with col2:
        mkt_header_row = st.number_input(
            "Header row (1 = first row)", min_value=1, value=1, step=1
        )

    try:
        marketplace_df = MarketplaceReportLoader.load(
            marketplace_bytes, mkt_sheet_name, header_row=mkt_header_row - 1
        )
    except DataLoadError as exc:
        st.error(str(exc))
        return

    st.dataframe(marketplace_df.head(5), use_container_width=True)

    # --- Load Master Input File ------------------------------------------------------
    st.subheader("Master Input File settings")
    service_account_info = _get_service_account_info()
    if service_account_info:
        st.success("Using configured Google service account for authenticated access.")
    else:
        st.warning(
            "No service account configured — falling back to public CSV export. "
            "The Google Sheet must be shared as 'Anyone with the link can view'."
        )

    try:
        master_loader = MasterInputLoader(service_account_info=service_account_info)
        master_df = master_loader.load(sheet_url, worksheet_name=worksheet_name or None)
    except DataLoadError as exc:
        st.error(str(exc))
        return

    st.dataframe(master_df.head(5), use_container_width=True)

    # --- Column mapping ----------------------------------------------------------
    st.subheader("Column mapping")
    st.caption(
        "Map each required field to the matching column in your files. "
        "'Campaign Type' should hold values like BAU / A+ / Mega if available — "
        "used to pick the correct SRP to compare against."
    )

    mkt_cols = list(marketplace_df.columns)
    master_cols = list(master_df.columns)

    map_col1, map_col2 = st.columns(2)
    with map_col1:
        st.markdown("**Marketplace Report**")
        mkt_sku_col = _column_picker("Seller SKU column", mkt_cols, "mkt_sku")
        mkt_rrp_col = _column_picker("RRP column", mkt_cols, "mkt_rrp")
        mkt_srp_col = _column_picker("SRP column", mkt_cols, "mkt_srp")
        mkt_campaign_col = _column_picker(
            "Campaign Type column (BAU / A+ / Mega)", mkt_cols, "mkt_campaign", allow_none=True
        )

    with map_col2:
        st.markdown("**Master Input File**")
        master_sku_col = _column_picker("Seller SKU column", master_cols, "master_sku")
        master_rrp_col = _column_picker("RRP column", master_cols, "master_rrp")
        master_bau_col = _column_picker("BAU SRP column", master_cols, "master_bau")
        master_aplus_col = _column_picker("A+ SRP column", master_cols, "master_aplus")
        master_mega_col = _column_picker("Mega SRP column", master_cols, "master_mega")

    tolerance = st.number_input(
        "Price match tolerance", min_value=0.0, value=0.01, step=0.01, format="%.2f"
    )

    if st.button("Run Validation", type="primary"):
        marketplace_map = MarketplaceColumnMap(
            seller_sku=mkt_sku_col,
            rrp=mkt_rrp_col,
            srp=mkt_srp_col,
            campaign_type=mkt_campaign_col,
        )
        master_map = MasterColumnMap(
            seller_sku=master_sku_col,
            rrp=master_rrp_col,
            srp_bau=master_bau_col,
            srp_a_plus=master_aplus_col,
            srp_mega=master_mega_col,
        )

        validator = PriceValidator(marketplace_map, master_map, tolerance=tolerance)
        with st.spinner("Validating prices..."):
            result_df = validator.validate(marketplace_df, master_df)

        st.success("Validation complete.")

        summary = build_summary(result_df)
        summary_cols = st.columns(len(summary))
        for col, (label, value) in zip(summary_cols, summary.items()):
            col.metric(label, value)

        st.dataframe(result_df, use_container_width=True, height=500)

        report_bytes = ExcelReportBuilder().build(result_df)
        st.download_button(
            label="Download Validation Report (.xlsx)",
            data=report_bytes,
            file_name="Price_Validation_Report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
