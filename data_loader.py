"""
Data loading utilities for the Price Update Automation Tool.

Handles:
    - Reading the Marketplace Campaign Submission Report (Excel, uploaded by the user).
    - Reading the Master Input File from a Google Sheet, either via a service-account
      (gspread) connection when credentials are available in Streamlit secrets, or via
      the public CSV export endpoint as a fallback for link-shared sheets.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

try:
    import gspread
    from google.oauth2.service_account import Credentials
    _GSPREAD_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency at runtime
    _GSPREAD_AVAILABLE = False


GOOGLE_SHEET_ID_PATTERN = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
GOOGLE_SHEET_GID_PATTERN = re.compile(r"[?&#]gid=([0-9]+)")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class DataLoadError(Exception):
    """Raised when a source file or Google Sheet cannot be loaded or parsed."""


@dataclass(frozen=True)
class SheetReference:
    """Parsed components of a Google Sheet URL."""

    sheet_id: str
    gid: Optional[str] = None


def parse_google_sheet_url(url: str) -> SheetReference:
    """Extract the spreadsheet ID and (optional) worksheet gid from a Google Sheet URL.

    Args:
        url: A full Google Sheets URL, e.g.
            "https://docs.google.com/spreadsheets/d/<ID>/edit#gid=<GID>".

    Returns:
        A SheetReference with the sheet_id and optional gid.

    Raises:
        DataLoadError: If the URL does not contain a recognizable spreadsheet ID.
    """
    match = GOOGLE_SHEET_ID_PATTERN.search(url)
    if not match:
        raise DataLoadError(
            "Could not find a spreadsheet ID in the provided Google Sheet URL."
        )
    gid_match = GOOGLE_SHEET_GID_PATTERN.search(url)
    return SheetReference(sheet_id=match.group(1), gid=gid_match.group(1) if gid_match else None)


class MarketplaceReportLoader:
    """Loads the Marketplace Campaign Submission Report from an uploaded Excel file."""

    @staticmethod
    def list_sheet_names(file_bytes: bytes) -> list[str]:
        """Return the list of sheet names contained in the uploaded workbook."""
        try:
            workbook = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
        except Exception as exc:  # noqa: BLE001
            raise DataLoadError(f"Unable to read the uploaded Excel file: {exc}") from exc
        return workbook.sheet_names

    @staticmethod
    def load(file_bytes: bytes, sheet_name: str, header_row: int = 0) -> pd.DataFrame:
        """Load a specific sheet from the uploaded Marketplace Report.

        Args:
            file_bytes: Raw bytes of the uploaded .xlsx file.
            sheet_name: Name of the worksheet to read.
            header_row: Zero-indexed row number containing column headers.

        Returns:
            A DataFrame with all columns read as strings/objects preserved as-is
            (numeric coercion happens later, during validation).
        """
        try:
            df = pd.read_excel(
                io.BytesIO(file_bytes),
                sheet_name=sheet_name,
                header=header_row,
                engine="openpyxl",
            )
        except Exception as exc:  # noqa: BLE001
            raise DataLoadError(f"Unable to parse sheet '{sheet_name}': {exc}") from exc
        df.columns = [str(c).strip() for c in df.columns]
        return df


class MasterInputLoader:
    """Loads the Master Input File from a Google Sheet.

    Prefers an authenticated gspread connection using a service account (read from
    Streamlit secrets under the key ``gcp_service_account``), and falls back to the
    public CSV export endpoint if no credentials are configured. The CSV fallback only
    works when the sheet's sharing setting is "Anyone with the link can view".
    """

    def __init__(self, service_account_info: Optional[dict] = None) -> None:
        self._service_account_info = service_account_info

    def _load_via_gspread(self, ref: SheetReference, worksheet_name: Optional[str]) -> pd.DataFrame:
        if not _GSPREAD_AVAILABLE:
            raise DataLoadError("gspread/google-auth is not installed.")
        if not self._service_account_info:
            raise DataLoadError("No service account credentials configured.")

        credentials = Credentials.from_service_account_info(
            self._service_account_info, scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(ref.sheet_id)

        if worksheet_name:
            worksheet = spreadsheet.worksheet(worksheet_name)
        elif ref.gid is not None:
            worksheet = next(
                (ws for ws in spreadsheet.worksheets() if str(ws.id) == ref.gid),
                spreadsheet.sheet1,
            )
        else:
            worksheet = spreadsheet.sheet1

        records = worksheet.get_all_records()
        return pd.DataFrame(records)

    def _load_via_csv_export(self, ref: SheetReference) -> pd.DataFrame:
        export_url = f"https://docs.google.com/spreadsheets/d/{ref.sheet_id}/export?format=csv"
        if ref.gid is not None:
            export_url += f"&gid={ref.gid}"
        try:
            df = pd.read_csv(export_url)
        except Exception as exc:  # noqa: BLE001
            raise DataLoadError(
                "Unable to read the Google Sheet via public CSV export. "
                "Make sure the sheet is shared as 'Anyone with the link can view', "
                "or configure a service account in Streamlit secrets. "
                f"Original error: {exc}"
            ) from exc
        return df

    def load(self, sheet_url: str, worksheet_name: Optional[str] = None) -> pd.DataFrame:
        """Load the Master Input File as a DataFrame.

        Args:
            sheet_url: Full URL to the Google Sheet.
            worksheet_name: Optional specific tab name to read (service-account path only).

        Returns:
            A DataFrame of the master input data.
        """
        ref = parse_google_sheet_url(sheet_url)

        if self._service_account_info:
            df = self._load_via_gspread(ref, worksheet_name)
        else:
            df = self._load_via_csv_export(ref)

        if df.empty:
            raise DataLoadError("The Master Input File loaded successfully but contains no rows.")

        df.columns = [str(c).strip() for c in df.columns]
        return df
