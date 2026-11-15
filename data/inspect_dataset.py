
from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent

print("\n=== DATASET FILES ===")

for file in sorted(DATA_DIR.rglob("*")):
    if file.is_file() and file.suffix.lower() in {".csv", ".xlsx", ".xls"}:
        # Skip files inside the existing EcomAssist data folder
        if "data" in file.relative_to(DATA_DIR).parts:
            continue

        print(f"\n{'=' * 60}")
        print(f"File: {file.relative_to(DATA_DIR)}")

        try:
            if file.suffix.lower() == ".csv":
                df = pd.read_csv(file, nrows=5)
                total_rows = sum(1 for _ in open(file, encoding="utf-8-sig")) - 1
            else:
                df = pd.read_excel(file, nrows=5)
                total_rows = len(pd.read_excel(file, usecols=[0]))

            print(f"Rows (approximate): {total_rows}")
            print("Columns:", list(df.columns))
            print("\nSample records:")
            print(df.head(2).to_string(index=False))

        except Exception as exc:
            print(f"Could not inspect file: {exc}")
