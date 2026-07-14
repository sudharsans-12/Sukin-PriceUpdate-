"""
Core price validation logic for the Price Update Automation Tool.

All comparisons are vectorized with pandas/numpy for performance on large
(100K+ row) marketplace reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

OK = "OK"
NEED_UPDATE = "Need Update"
NOT_APPLICABLE = "N/A"

NEED_UPDATE_YES = "Yes"
NEED_UPDATE_NO = "No"
NEED_UPDATE_NA = "N/A"


@dataclass(frozen=True)
class MarketplaceColumnMap:
    """Column names to use from the Marketplace Campaign Submission Report."""

    seller_sku: str
    rrp: str
    srp: str
    campaign_type: Optional[str] = None  # Expected values like BAU / A+ / Mega, if present


@dataclass(frozen=True)
class MasterColumnMap:
    """Column names to use from the Master Input File."""

    seller_sku: str
    rrp: str
    srp_bau: str
    srp_a_plus: str
    srp_mega: str


def _to_numeric(series: pd.Series) -> pd.Series:
    """Coerce a series to numeric, cleaning common currency/formatting artifacts."""
    cleaned = (
        series.astype(str)
        .str.replace(r"[^\d.\-]", "", regex=True)
        .replace("", np.nan)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _normalize_campaign_type(series: pd.Series) -> pd.Series:
    """Normalize free-text campaign type values to one of BAU / A+ / MEGA / '' (unknown)."""
    normalized = series.astype(str).str.strip().str.upper()
    normalized = normalized.str.replace("A PLUS", "A+", regex=False)
    normalized = normalized.str.replace("APLUS", "A+", regex=False)
    return normalized


class PriceValidator:
    """Validates Marketplace Campaign Submission Report prices against a Master Input File."""

    def __init__(
        self,
        marketplace_cols: MarketplaceColumnMap,
        master_cols: MasterColumnMap,
        tolerance: float = 0.01,
    ) -> None:
        self._mkt_cols = marketplace_cols
        self._master_cols = master_cols
        self._tolerance = tolerance

    def validate(self, marketplace_df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
        """Run the full validation and return a result DataFrame.

        Output columns: Seller SKU, RRP, RRP Check, SRP, SRP Check, Need to Update.
        """
        mkt = self._prepare_marketplace(marketplace_df)
        master = self._prepare_master(master_df)

        merged = mkt.merge(
            master,
            on="Seller SKU",
            how="left",
            suffixes=("", "_master"),
            indicator=True,
        )

        sku_missing = (
            merged["Seller SKU"].isna()
            | (merged["Seller SKU"].astype(str).str.strip() == "")
            | (merged["_merge"] == "left_only")
        )

        merged["RRP Check"] = self._compare_rrp(merged, sku_missing)
        merged["SRP Check"], merged["Correct SRP"] = self._compare_srp(merged, sku_missing)
        merged["Need to Update"] = self._compute_need_update(
            merged["RRP Check"], merged["SRP Check"]
        )

        result = merged[
            ["Seller SKU", "RRP", "RRP Check", "SRP", "SRP Check", "Need to Update"]
        ].copy()
        return result

    def _prepare_marketplace(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = self._mkt_cols
        out = pd.DataFrame()
        out["Seller SKU"] = df[cols.seller_sku].astype(str).str.strip()
        out["RRP"] = _to_numeric(df[cols.rrp])
        out["SRP"] = _to_numeric(df[cols.srp])
        if cols.campaign_type:
            out["Campaign Type"] = _normalize_campaign_type(df[cols.campaign_type])
        else:
            out["Campaign Type"] = ""
        return out

    def _prepare_master(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = self._master_cols
        out = pd.DataFrame()
        out["Seller SKU"] = df[cols.seller_sku].astype(str).str.strip()
        out["RRP_master"] = _to_numeric(df[cols.rrp])
        out["SRP_BAU"] = _to_numeric(df[cols.srp_bau])
        out["SRP_A+"] = _to_numeric(df[cols.srp_a_plus])
        out["SRP_MEGA"] = _to_numeric(df[cols.srp_mega])
        # Guard against duplicate SKUs in the master file: keep the first occurrence.
        out = out.drop_duplicates(subset="Seller SKU", keep="first")
        return out

    def _compare_rrp(self, merged: pd.DataFrame, sku_missing: pd.Series) -> pd.Series:
        rrp_blank = merged["RRP"].isna() | merged["RRP_master"].isna()
        na_mask = sku_missing | rrp_blank
        is_match = np.isclose(
            merged["RRP"].fillna(-1),
            merged["RRP_master"].fillna(-2),
            atol=self._tolerance,
        )
        return pd.Series(
            np.select(
                [na_mask, is_match],
                [NOT_APPLICABLE, OK],
                default=NEED_UPDATE,
            ),
            index=merged.index,
        )

    def _compare_srp(self, merged: pd.DataFrame, sku_missing: pd.Series):
        """Determine the correct SRP to compare against, then check the match.

        If a campaign type is available on the marketplace row (BAU / A+ / MEGA),
        the corresponding master column is used. If it's missing or unrecognized,
        the reported SRP is checked against all three master SRP columns and
        counted as a match if it equals any of them.
        """
        campaign = merged["Campaign Type"]

        selected_srp = pd.Series(np.nan, index=merged.index, dtype="float64")
        selected_srp = selected_srp.where(campaign != "BAU", merged["SRP_BAU"])
        selected_srp = selected_srp.where(campaign != "A+", merged["SRP_A+"])
        selected_srp = selected_srp.where(campaign != "MEGA", merged["SRP_MEGA"])

        has_known_campaign = campaign.isin(["BAU", "A+", "MEGA"])

        match_known = has_known_campaign & np.isclose(
            merged["SRP"].fillna(-1), selected_srp.fillna(-2), atol=self._tolerance
        )

        match_any = (
            np.isclose(merged["SRP"].fillna(-1), merged["SRP_BAU"].fillna(-2), atol=self._tolerance)
            | np.isclose(merged["SRP"].fillna(-1), merged["SRP_A+"].fillna(-2), atol=self._tolerance)
            | np.isclose(merged["SRP"].fillna(-1), merged["SRP_MEGA"].fillna(-2), atol=self._tolerance)
        )

        srp_blank = merged["SRP"].isna() | (
            merged["SRP_BAU"].isna() & merged["SRP_A+"].isna() & merged["SRP_MEGA"].isna()
        )
        na_mask = sku_missing | srp_blank

        is_match = np.where(has_known_campaign, match_known, match_any)

        check = pd.Series(
            np.select([na_mask, is_match], [NOT_APPLICABLE, OK], default=NEED_UPDATE),
            index=merged.index,
        )

        # For reference/debugging: the master SRP value that was actually compared against.
        correct_srp = selected_srp.where(has_known_campaign, np.nan)
        return check, correct_srp

    @staticmethod
    def _compute_need_update(rrp_check: pd.Series, srp_check: pd.Series) -> pd.Series:
        # Priority: an actionable "Need Update" on either field always wins (Yes),
        # then missing/incomplete data on either field (N/A), otherwise both matched (No).
        either_need_update = (rrp_check == NEED_UPDATE) | (srp_check == NEED_UPDATE)
        either_na = (rrp_check == NOT_APPLICABLE) | (srp_check == NOT_APPLICABLE)
        return pd.Series(
            np.select(
                [either_need_update, either_na],
                [NEED_UPDATE_YES, NEED_UPDATE_NA],
                default=NEED_UPDATE_NO,
            ),
            index=rrp_check.index,
        )
