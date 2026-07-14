import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Marketplace Price Validator", layout="wide")
st.title("Marketplace Price Validator")
st.caption(
    "Validates and prepares marketplace price updates by comparing the Marketplace (MP) report "
    "with the Google Sheets Master Reference file."
)

# --- GitHub & Deployment Instructions in Sidebar ---
with st.sidebar:
    st.header(":gear: Deployment Guide")
    st.markdown(
        """
        ### :rocket: How to deploy this on GitHub & Streamlit

        1. **Create GitHub Repository**:
           Create a repository on GitHub (e.g., `marketplace-price-validator`).

        2. **Create `requirements.txt`**:
           Make sure to include these dependencies in your repository:
           ```text
           streamlit
           pandas
           openpyxl
           ```

        3. **Upload Files**:
           Commit your `validator_app.py` and `requirements.txt` to GitHub.

        4. **Deploy on Streamlit Sharing**:
           - Go to [share.streamlit.io](https://share.streamlit.io).
           - Connect your GitHub account.
           - Click **New App**, select your repository, branch, and enter `validator_app.py` as the main file path.
           - Click **Deploy!**
        """
    )

st.write("---")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Master Reference (Google Sheets)")
    sheet_url = st.text_input(
        "Google Sheets Link",
        placeholder="https://docs.google.com/spreadsheets/d/...",
        help="Make sure the Google Sheet sharing setting is set to 'Anyone with the link can view'."
    )

    price_types = st.multiselect(
        "Filter Price Type(s)",
        options=["BAU", "A+", "Mega"],
        default=["BAU", "A+", "Mega"],
        help="Only compare SKUs matching the selected price types."
    )

    clearance_mode = st.checkbox(
        "Clearance & Exclusion Mode",
        value=False,
        help="Only compare RRP (Price). SRP (Special Price) is completely ignored in status evaluation."
    )

with col2:
    st.subheader("2. Marketplace Report (Excel)")
    mp_file = st.file_uploader(
        "Upload Marketplace Report",
        type=["xlsx", "xls"],
        key="mp_file"
    )

def normalize_sku(val):
    """Normalize Seller SKU key for clean matching."""
    if pd.isna(val):
        return ""
    s = str(val).strip().replace("\xa0", "")
    if s.endswith(".0"):
        s = s[:-2]
    return s.lower()

def clean_price(val):
    """Clean and standardize price values. Blanks and 0s are returned as None."""
    if pd.isna(val):
        return None
    s = str(val).strip().replace("$", "").replace("₱", "").replace(",", "")
    if s == "" or s.lower() == "nan":
        return None
    try:
        f = float(s)
        if f == 0.0:
            return None
        return round(f, 2)
    except ValueError:
        return None

def fetch_google_sheet(url):
    """Parse Google Sheet URL and retrieve sheet as CSV."""
    match_id = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match_id:
        raise ValueError("Invalid Google Sheets URL. Could not parse Spreadsheet ID.")
    spreadsheet_id = match_id.group(1)

    gid = "0"
    match_gid = re.search(r"gid=([0-9]+)", url)
    if match_gid:
        gid = match_gid.group(1)

    export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    return pd.read_csv(export_url)

# --- Processing Logic ---
master_df = None
mp_df = None

if sheet_url:
    try:
        master_df = fetch_google_sheet(sheet_url)
        st.success("Successfully fetched Master Reference Google Sheet!")
        with st.expander("Preview Master Reference (First 5 Rows)"):
            st.dataframe(master_df.head(5), use_container_width=True)
    except Exception as e:
        st.error(f"Error fetching Google Sheet: {e}. Check sharing permissions and sheet URL.")

if mp_file is not None:
    try:
        mp_df = pd.read_excel(mp_file)
        st.success("Successfully loaded Marketplace Report!")
        with st.expander("Preview Marketplace Report (First 5 Rows)"):
            st.dataframe(mp_df.head(5), use_container_width=True)
    except Exception as e:
        st.error(f"Error reading Marketplace Report: {e}")

if master_df is not None and mp_df is not None:
    # Validate columns
    required_master_cols = ["Seller SKU", "RRP", "SRP", "Price Type"]
    required_mp_cols = ["Seller SKU", "Price", "Special Price"]

    master_col_check = all(c in master_df.columns for c in required_master_cols)
    mp_col_check = all(c in mp_df.columns for c in required_mp_cols)

    if not master_col_check:
        st.error(f"Master Sheet is missing required columns. Must contain: {required_master_cols}. Found: {list(master_df.columns)}")
    if not mp_col_check:
        st.error(f"Marketplace Report is missing required columns. Must contain: {required_mp_cols}. Found: {list(mp_df.columns)}")

    if master_col_check and mp_col_check:
        if st.button("Validate and Prepare Updates", type="primary"):
            # 1. Filter Master sheet by selected Price Types
            master_filtered = master_df[master_df["Price Type"].isin(price_types)].copy()
            master_filtered["_norm_sku"] = master_filtered["Seller SKU"].apply(normalize_sku)
            # Remove duplicate SKUs in Master to ensure correct matching
            master_filtered = master_filtered.drop_duplicates(subset=["_norm_sku"])

            # Map SKU -> (RRP, SRP, Price Type)
            master_map = master_filtered.set_index("_norm_sku")[["RRP", "SRP", "Price Type"]].to_dict("index")

            # 2. Run validations
            results = []
            mp_df_copy = mp_df.copy()
            mp_df_copy["_norm_sku"] = mp_df_copy["Seller SKU"].apply(normalize_sku)

            for _, row in mp_df_copy.iterrows():
                orig_sku = row["Seller SKU"]
                norm_sku = row["_norm_sku"]
                mp_rrp = clean_price(row["Price"])
                mp_srp = clean_price(row["Special Price"])

                if norm_sku not in master_map:
                    results.append({
                        "Seller SKU": orig_sku,
                        "Master RRP": None,
                        "Master SRP": None,
                        "MP Price": mp_rrp,
                        "MP Special Price": mp_srp,
                        "Price Type": None,
                        "Validation Status": "Seller SKU Not Found",
                        "Remarks": "SKU not found in Master reference"
                    })
                    continue

                master_row = master_map[norm_sku]
                m_rrp = clean_price(master_row["RRP"])
                m_srp = clean_price(master_row["SRP"])
                price_type = master_row["Price Type"]

                # Check RRP match
                rrp_match = (m_rrp == mp_rrp)

                if clearance_mode:
                    # Ignore SRP completely, only validate RRP
                    status = "Price Matched" if rrp_match else "RRP Mismatch"
                    remarks = f"Clearance/Exclusion Mode. Master RRP={m_rrp}, MP RRP={mp_rrp}"
                else:
                    # Validate both RRP and SRP
                    srp_match = (m_srp == mp_srp)

                    if rrp_match and srp_match:
                        status = "Price Matched"
                        remarks = "Both RRP and SRP match"
                    elif not rrp_match and srp_match:
                        status = "RRP Mismatch"
                        remarks = f"RRP Mismatch: Master RRP={m_rrp}, MP RRP={mp_rrp}"
                    elif rrp_match and not srp_match:
                        status = "SRP Mismatch"
                        remarks = f"SRP Mismatch: Master SRP={m_srp}, MP SRP={mp_srp}"
                    else:
                        status = "Both RRP & SRP Mismatch"
                        remarks = (
                            f"RRP Mismatch: Master={m_rrp}, MP={mp_rrp} | "
                            f"SRP Mismatch: Master={m_srp}, MP={mp_srp}"
                        )

                results.append({
                    "Seller SKU": orig_sku,
                    "Master RRP": m_rrp,
                    "Master SRP": m_srp,
                    "MP Price": mp_rrp,
                    "MP Special Price": mp_srp,
                    "Price Type": price_type,
                    "Validation Status": status,
                    "Remarks": remarks
                })

            res_df = pd.DataFrame(results)

            # Display results
            st.subheader("Validation Result Summary")

            status_counts = res_df["Validation Status"].value_counts()

            # Show metrics
            cols = st.columns(len(status_counts))
            for col, (status, count) in zip(cols, status_counts.items()):
                col.metric(status, count)

            st.dataframe(res_df, use_container_width=True)

            # Excel export using in-memory byte buffer
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                res_df.to_excel(writer, index=False, sheet_name="Validation Results")
            excel_buffer.seek(0)

            st.download_button(
                label=":inbox_tray: Download Validation Report (Excel)",
                data=excel_buffer,
                file_name="Price_Validation_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
