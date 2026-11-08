"""Run the complete local sync without a console, including child processes."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    # Scheduled tasks inherit the signed-in user's environment.
    from lectio_sync.local_sync import main as sync_main
    with open(os.devnull, "w", encoding="utf-8") as quiet:
        sys.stdout = sys.stderr = quiet
        return sync_main()


if __name__ == "__main__":
    raise SystemExit(main())
