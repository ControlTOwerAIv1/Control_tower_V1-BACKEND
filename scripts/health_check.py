"""
scripts/health_check.py
========================
On-demand full system health check for the KOL Distributor Toys
AI Inventory Control Tower.

Checks:
    1. .env file and ANTHROPIC_API_KEY
    2. MySQL connectivity
    3. Required tables have rows
    4. Claude API reachability
    5. FastAPI server reachability

Usage:
    python scripts/health_check.py
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level up from scripts/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _print_result(label: str, passed: bool, detail: str = "") -> None:
    """Print a single check result with PASS/FAIL label."""
    status = "PASS" if passed else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")


def check_env() -> bool:
    """Check that .env exists and ANTHROPIC_API_KEY is set."""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        _print_result(".env file exists", False, ".env not found")
        return False

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        _print_result("ANTHROPIC_API_KEY present", False, "key is missing or empty")
        return False

    _print_result("ANTHROPIC_API_KEY present", True, f"prefix: {api_key[:10]}...")
    return True


def check_mysql() -> bool:
    """Check MySQL connectivity using DB_* env vars."""
    try:
        import pymysql
    except ImportError:
        _print_result("MySQL connection", False, "pymysql not installed")
        return False

    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "")

    if not user or not database:
        _print_result("MySQL connection", False, "DB_USER or DB_NAME not set")
        return False

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=5,
        )
        conn.close()
        _print_result("MySQL connection", True, f"{host}:{port}/{database}")
        return True
    except Exception as exc:
        _print_result("MySQL connection", False, str(exc))
        return False


def check_tables() -> bool:
    """Check that required tables exist and have rows > 0."""
    try:
        import pymysql
    except ImportError:
        _print_result("Table row counts", False, "pymysql not installed")
        return False

    required_tables = [
        "product",
        "warehouse_product_management",
        "invoice",
        "invoice_details",
        "lead_time_setting",
    ]

    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "")

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=5,
        )
    except Exception as exc:
        _print_result("Table row counts", False, f"cannot connect: {exc}")
        return False

    all_ok = True
    try:
        cursor = conn.cursor()
        for table in required_tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                row = cursor.fetchone()
                count = row[0] if row else 0
                if count > 0:
                    _print_result(f"  Table '{table}'", True, f"{count} rows")
                else:
                    _print_result(f"  Table '{table}'", False, "0 rows")
                    all_ok = False
            except Exception as exc:
                _print_result(f"  Table '{table}'", False, str(exc))
                all_ok = False
    finally:
        conn.close()

    return all_ok


def check_claude_api() -> bool:
    """Send a minimal ping to the Claude API."""
    try:
        import anthropic
    except ImportError:
        _print_result("Claude API reachable", False, "anthropic not installed")
        return False

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        _print_result("Claude API reachable", False, "no API key")
        return False

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=15.0)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        text = getattr(response.content[0], "text", "")
        _print_result("Claude API reachable", True, f"response: {text[:40]}")
        return True
    except Exception as exc:
        _print_result("Claude API reachable", False, str(exc))
        return False


def check_fastapi_server() -> bool:
    """POST to /api/chat to verify the FastAPI server is running."""
    url = "http://127.0.0.1:8000/api/chat"
    payload = json.dumps({"question": "test"}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            _print_result(
                "FastAPI server reachable",
                True,
                f"status {resp.status}, answer_len={len(body.get('answer', ''))}",
            )
            return True
    except urllib.error.HTTPError as exc:
        # Server responded but with an error status -- still reachable
        _print_result(
            "FastAPI server reachable",
            True,
            f"server responded with HTTP {exc.code}",
        )
        return True
    except Exception as exc:
        _print_result("FastAPI server reachable", False, str(exc))
        return False


def main() -> None:
    """Run all health checks and print a summary."""
    print("=" * 60)
    print("KOL Inventory Control Tower - Health Check")
    print("=" * 60)

    checks = [
        ("Environment (.env + API key)", check_env),
        ("MySQL connection", check_mysql),
        ("Table row counts", check_tables),
        ("Claude API reachable", check_claude_api),
        ("FastAPI server reachable", check_fastapi_server),
    ]

    results = []
    for name, fn in checks:
        print(f"\n[CHECK] {name}")
        try:
            passed = fn()
        except Exception as exc:
            _print_result(name, False, f"unexpected error: {exc}")
            passed = False
        results.append((name, passed))

    passed_count = sum(1 for _, p in results if p)
    failed_count = len(results) - passed_count

    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed_count} passed, {failed_count} failed out of {len(results)} checks")
    print("=" * 60)

    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
