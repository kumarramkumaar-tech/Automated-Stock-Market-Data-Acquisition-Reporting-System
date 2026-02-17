import os
from openpyxl import load_workbook
import pandas as pd


def append_df_to_excel(filename, df, sheet_name="Chain_Log", index=False):
    """
    Append DataFrame into an existing Excel file.
    Creates file with headers if it doesn't exist.
    """
    folder = os.path.dirname(filename)
    if folder:
        os.makedirs(folder, exist_ok=True)

    if not os.path.exists(filename):
        df.to_excel(filename, sheet_name=sheet_name, index=index)
        return

    book = load_workbook(filename)
    if sheet_name in book.sheetnames:
        ws = book[sheet_name]
        start_row = ws.max_row + 1
        with pd.ExcelWriter(filename, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
            df.to_excel(
                writer,
                sheet_name=sheet_name,
                index=index,
                header=False,
                startrow=start_row
            )
    else:
        with pd.ExcelWriter(filename, engine='openpyxl', mode='a') as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=index)
