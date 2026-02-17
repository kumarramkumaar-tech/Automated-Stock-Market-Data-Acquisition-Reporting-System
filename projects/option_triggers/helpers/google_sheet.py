# helpers/google_sheet.py – Google Sheets integration for WBRam watchlist
#
# Reads the Google Sheet to:
#   1. Get the list of allowed stocks (Rule 3)
#   2. Check if Column O (LTP) is TRUE for each stock (Rule 4)
#   3. Read price columns for announcement
#
# Setup instructions:
#   Option A (Service Account - recommended for automation):
#     1. Go to Google Cloud Console -> APIs -> Enable Google Sheets API
#     2. Create a Service Account, download JSON key
#     3. Place JSON in credentials/google_service_account.json
#     4. Share your Google Sheet with the service account email
#
#   Option B (Public sheet fallback):
#     1. Publish your sheet to the web (File -> Share -> Publish to web)
#     2. Use the CSV export URL as fallback

import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# Try importing gspread; fall back to CSV if not available
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    logger.info("gspread not installed. Using CSV fallback for Google Sheets.")


def _get_gspread_client(credentials_file):
    """Authenticate and return a gspread client."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
    return gspread.authorize(creds)


def read_watchlist_gspread(sheet_id, worksheet_name, credentials_file):
    """
    Read the full watchlist from Google Sheets using gspread.
    Returns a pandas DataFrame with all columns.
    """
    client = _get_gspread_client(credentials_file)
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.worksheet(worksheet_name)
    records = worksheet.get_all_records()
    return pd.DataFrame(records)


def read_watchlist_csv(sheet_id, worksheet_name="Sheet1"):
    """
    Fallback: Read Google Sheet as published CSV.
    Sheet must be published to web first.
    """
    # gid=0 for first sheet; adjust if needed
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={worksheet_name}"
    try:
        df = pd.read_csv(url)
        return df
    except Exception as e:
        logger.error(f"CSV fallback failed: {e}")
        return pd.DataFrame()


def load_watchlist(cfg):
    """
    Load the WBRam watchlist from Google Sheets.
    Returns DataFrame with all sheet data.

    Tries gspread first, falls back to CSV export.
    """
    gs_cfg = cfg.get("google_sheet", {})
    sheet_id = gs_cfg.get("sheet_id") or os.getenv("GOOGLE_SHEET_ID", "")
    worksheet_name = gs_cfg.get("worksheet_name", "Sheet1")
    credentials_file = gs_cfg.get("credentials_file", "credentials/google_service_account.json")

    if not sheet_id or sheet_id == "YOUR_GOOGLE_SHEET_ID_HERE":
        logger.warning("Google Sheet ID not configured. Using empty watchlist.")
        return pd.DataFrame()

    # Try gspread first
    if GSPREAD_AVAILABLE and os.path.exists(credentials_file):
        try:
            logger.info("Reading watchlist via gspread service account...")
            df = read_watchlist_gspread(sheet_id, worksheet_name, credentials_file)
            logger.info(f"Loaded {len(df)} rows from Google Sheet via gspread")
            return df
        except Exception as e:
            logger.warning(f"gspread failed: {e}. Falling back to CSV.")

    # Fallback to CSV
    try:
        logger.info("Reading watchlist via CSV export...")
        df = read_watchlist_csv(sheet_id, worksheet_name)
        logger.info(f"Loaded {len(df)} rows from Google Sheet via CSV")
        return df
    except Exception as e:
        logger.error(f"All Google Sheet methods failed: {e}")
        return pd.DataFrame()


def get_allowed_symbols(watchlist_df):
    """
    Rule 3: Extract the list of stock symbols from the watchlist.
    Assumes first column contains symbol names.
    """
    if watchlist_df.empty:
        return []

    # Use first column as symbol column
    first_col = watchlist_df.columns[0]
    symbols = watchlist_df[first_col].dropna().astype(str).str.strip().str.upper().tolist()
    return [s for s in symbols if s and s != ""]


def check_ltp_status(watchlist_df, symbol, ltp_column="O"):
    """
    Rule 4: Check if Column O (LTP) is TRUE for a given symbol.
    Returns (is_true, row_data) tuple.

    Column O is typically the 15th column (0-indexed: 14).
    """
    if watchlist_df.empty:
        return False, {}

    first_col = watchlist_df.columns[0]

    # Find the row for this symbol
    mask = watchlist_df[first_col].astype(str).str.strip().str.upper() == symbol.upper()
    matching = watchlist_df[mask]

    if matching.empty:
        return False, {}

    row = matching.iloc[0]

    # Column O = 15th column (index 14)
    # Try by column letter mapping or by index
    ltp_value = None

    # Try by column index (O = 15th = index 14)
    col_index = ord(ltp_column.upper()) - ord('A')  # O=14
    if col_index < len(watchlist_df.columns):
        col_name = watchlist_df.columns[col_index]
        ltp_value = row[col_name]

    # Check if it's TRUE
    is_true = False
    if ltp_value is not None:
        val_str = str(ltp_value).strip().upper()
        is_true = val_str in ["TRUE", "YES", "1", "T"]

    return is_true, row.to_dict()


def get_price_columns(watchlist_df, symbol, price_columns=None):
    """
    Read price-related columns (P, Q, R etc.) for a given symbol.
    Returns dict of column_name -> value.
    """
    if watchlist_df.empty:
        return {}

    if price_columns is None:
        price_columns = ["P", "Q", "R"]

    first_col = watchlist_df.columns[0]
    mask = watchlist_df[first_col].astype(str).str.strip().str.upper() == symbol.upper()
    matching = watchlist_df[mask]

    if matching.empty:
        return {}

    row = matching.iloc[0]
    result = {}

    for col_letter in price_columns:
        col_index = ord(col_letter.upper()) - ord('A')
        if col_index < len(watchlist_df.columns):
            col_name = watchlist_df.columns[col_index]
            result[col_name] = row[col_name]

    return result
