import os
import json
import pathlib

from typing import Any


def load_tidepool_token() -> str:
    token = os.environ.get("TIDEPOOL_API_TOKEN")
    if not token:
        raise EnvironmentError("TIDEPOOL_API_TOKEN is not set. Store your Tidepool API token in an environment variable.")
    return token


def download_tidepool_export(export_path: pathlib.Path) -> None:
    """Placeholder: replace this with a Tidepool API call or local export loader."""
    print("Replace download_tidepool_export() with Tidepool export retrieval logic.")
    export_path.write_text(json.dumps({"placeholder": True}, indent=2))


def parse_export(export_path: pathlib.Path) -> Any:
    with export_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    token = load_tidepool_token()
    print("Loaded Tidepool token from environment.")

    export_path = pathlib.Path("data/tidepool_export.json")
    export_path.parent.mkdir(parents=True, exist_ok=True)

    download_tidepool_export(export_path)
    data = parse_export(export_path)
    print(f"Loaded export data with keys: {list(data.keys())}")

    # TODO: add logic to upload parsed data to Databricks / DBFS / Delta tables.


if __name__ == "__main__":
    main()
