"""Download the openly licensed UCI source and validate both archive layers."""
from pathlib import Path
import hashlib
import io
import urllib.request
import zipfile

SOURCE = "https://archive.ics.uci.edu/static/public/352/online+retail.zip"
DESTINATION = Path(__file__).resolve().parent / "data" / "Online Retail.xlsx"


def main():
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if DESTINATION.exists() and zipfile.is_zipfile(DESTINATION):
        print(f"Using existing dataset: {DESTINATION}")
        return
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "RetailInventoryProject/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        archive_bytes = response.read()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Incomplete source download; download manually from the UCI page")
        spreadsheet = archive.read("Online Retail.xlsx")
    with zipfile.ZipFile(io.BytesIO(spreadsheet)) as archive:
        if archive.testzip() is not None:
            raise ValueError("The downloaded Excel archive failed its integrity check")
    temporary = DESTINATION.with_suffix(".xlsx.part")
    temporary.write_bytes(spreadsheet)
    temporary.replace(DESTINATION)
    print(f"Saved {DESTINATION.name} ({len(spreadsheet):,} bytes)")
    print("SHA256:", hashlib.sha256(spreadsheet).hexdigest())


if __name__ == "__main__":
    main()
