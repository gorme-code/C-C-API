"""Quick live connectivity check against Salesforce.

Run from the project root:
    .venv\\Scripts\\python.exe scripts\\check_connection.py

Authenticates with whatever flow .env is configured for and runs one query.
Prints a clear OK/FAILED so you can confirm the connected app works before
exercising the real endpoints. Reads no secrets to stdout.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.salesforce import get_sf_connection, sf  # noqa: E402


def main() -> None:
    try:
        get_sf_connection()
        print("AUTH OK")
    except Exception as exc:  # noqa: BLE001
        print("AUTH FAILED:", type(exc).__name__)
        print(str(exc)[:800])
        return

    try:
        rows = sf.query(
            "SELECT Id, Name FROM Account "
            "WHERE RecordType.DeveloperName = 'District' LIMIT 3"
        )
        print(f"QUERY OK -> districts found: {len(rows)}")
        for r in rows:
            print("  -", r.get("Name"))
    except Exception as exc:  # noqa: BLE001
        print("QUERY FAILED:", type(exc).__name__)
        print(str(exc)[:800])


if __name__ == "__main__":
    main()
