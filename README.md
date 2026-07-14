Price Update Automation Tool
A Streamlit app that validates a Marketplace Campaign Submission Report (Excel)
against a Master Input File (Google Sheet), matched by Seller SKU, checking
whether RRP and SRP are up to date.
What it does
Upload the Marketplace Campaign Submission Report (`.xlsx`).
Provide the Master Input File's Google Sheet link.
Map each file's columns (Seller SKU, RRP, SRP, and — for the master file — the
three SRP tiers: BAU / A+ / Mega).
Click Run Validation. The app matches rows on Seller SKU and produces:
Column	Meaning
Seller SKU	From the Marketplace Report
RRP	RRP as submitted in the Marketplace Report
RRP Check	`OK` / `Need Update` / `N/A`
SRP	SRP as submitted in the Marketplace Report
SRP Check	`OK` / `Need Update` / `N/A`
Need to Update	`Yes` / `No` / `N/A`
Download the result as a styled `.xlsx` (green = OK/No, red = Need Update/Yes,
grey = N/A), or preview it in the browser first.
Validation logic
Match: rows are joined on Seller SKU. A SKU missing from the Master Input
File is treated as unmatched.
RRP Check: compares the Marketplace Report's RRP to the Master Input File's
RRP for that SKU (numeric match within a configurable tolerance, default 0.01).
SRP Check: the Master Input File holds three SRP tiers — BAU, A+, and Mega.
The correct one to compare against is chosen using the Campaign Type column
in the Marketplace Report (values like `BAU`, `A+`, `Mega`), since the report is
a campaign submission report and each submission belongs to one campaign.
If no Campaign Type column is mapped, or a row's value isn't recognized, the
app falls back to checking the submitted SRP against all three master
tiers — it's marked `OK` if it matches any of them, `Need Update` otherwise.
N/A is used whenever the Seller SKU doesn't match, or the relevant price
field is blank/missing on either side.
Need to Update:
`Yes` — if either RRP or SRP is `Need Update` (takes priority).
`N/A` — if neither needs an update, but either check came back `N/A` due to
missing data.
`No` — both RRP and SRP checks are `OK`.
> If your files use a different structure for indicating campaign/price type,
> adjust the "Campaign Type" mapping in the sidebar, or edit
> `src/validator.py::PriceValidator._compare_srp` to match your exact business rule.
Project structure
```
price-update-automation/
├── app.py                          # Streamlit UI
├── src/
│   ├── data_loader.py              # Excel upload + Google Sheet loading
│   ├── validator.py                # Core vectorized validation logic
│   └── report_builder.py           # Styled Excel output
├── requirements.txt
├── .streamlit/
│   └── secrets.toml.example        # Template for Google service account
└── README.md
```
Running locally
```bash
git clone <your-repo-url>
cd price-update-automation
pip install -r requirements.txt
streamlit run app.py
```
Connecting the Master Input Google Sheet
The app supports two ways to read the Google Sheet:
Option A — Public link (no setup required)
Share the Google Sheet as "Anyone with the link can view". The app reads it
via the public CSV export endpoint automatically. No credentials needed.
Option B — Service account (recommended for private/internal sheets)
In Google Cloud Console, create a Service Account and a JSON key
(APIs & Services → Credentials).
Enable the Google Sheets API and Google Drive API for the project.
Share the target Google Sheet with the service account's email address
(found in the JSON key as `client_email`), with at least Viewer access.
Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (local) or
paste the equivalent into your Streamlit Community Cloud app's Secrets
settings, and fill in your service account's JSON fields.
The app automatically detects and prefers the service account if configured.
Deploying via GitHub + Streamlit Community Cloud
Push this project to a GitHub repository.
Go to share.streamlit.io → New app.
Select your repo, branch, and set the main file path to `app.py`.
If using a service account (Option B above), add the `gcp_service_account`
secret block under the app's Settings → Secrets.
Deploy. Every push to the connected branch redeploys the app automatically.
Notes
Validation is fully vectorized with pandas/numpy, so large reports (100K+
rows) validate in a couple of seconds.
Excel styling uses openpyxl's declarative conditional formatting (not per-cell
fill loops), keeping the styled workbook write fast even at scale.
Price strings with currency symbols, commas, or spaces (e.g. `"$1,234.50"`)
are cleaned automatically before numeric comparison.
