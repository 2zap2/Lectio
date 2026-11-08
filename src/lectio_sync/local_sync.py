"""Quiet daily local sync with a durable publication queue and process lock."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from .browser_fetch import build_calendars
from .browser_session import LoginRequired
from .cookie_refresh import _default_profile_dir
from .publish import load_calendars, publish_calendars


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def sync_lock(path: Path):
    """OS-owned lock releases on crashes; duplicate wake/logon runs exit quietly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise AlreadyRunning from None
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise AlreadyRunning from None
        yield
    finally:
        handle.close()


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def same_school_day(stamp: str | None, now: datetime) -> bool:
    if not stamp:
        return False
    previous = datetime.fromisoformat(stamp).astimezone(ZoneInfo("Europe/Copenhagen"))
    local = now.astimezone(ZoneInfo("Europe/Copenhagen"))
    # A resume before today's 08:05 refresh must not suppress that refresh.
    boundary = local.replace(hour=8, minute=5, second=0, microsecond=0)
    return previous >= boundary if local >= boundary else previous.date() == local.date()


def retry(operation, *, delays=(10, 30), sleep=time.sleep):
    for attempt in range(len(delays) + 1):
        try:
            return operation()
        except LoginRequired:
            raise
        except Exception:
            if attempt == len(delays):
                raise
            logging.warning("Temporary failure; retrying in %s seconds", delays[attempt])
            sleep(delays[attempt])


def run_sync(*, config: dict, state_dir: Path, schedule_url: str, profile: Path | None = None,
             force=False, build_only=False, interactive=False, allow_recovery=True,
             builder=build_calendars, publisher=publish_calendars, now=None, retry_delays=(10, 30)) -> int:
    now = now or datetime.now(timezone.utc)
    state_dir.mkdir(parents=True, exist_ok=True)
    with sync_lock(state_dir / "sync.lock"):
        state_path = state_dir / "sync-state.json"
        state = read_json(state_path)
        pending = state_dir / "pending"
        if pending.exists() and not build_only:
            logging.info("Retrying publication of the saved complete generation")
            # Publication failure never requires another browser/login.
            commit = retry(lambda: publisher(pending, repository=config["repository"], branch=config["branch"]),
                           delays=retry_delays)
            state.update(last_published=datetime.now(timezone.utc).isoformat(), commit=commit,
                         last_fetched=read_json(pending / "generation.json")["fetched_at"])
            state.pop("recovery_offered", None)
            write_json(state_path, state)
            shutil.rmtree(pending)
        if not force and same_school_day(state.get("last_fetched"), now):
            logging.info("Today's calendar update is already complete")
            return 0
        staging = state_dir / ("generation-" + uuid4().hex)
        staging.mkdir()

        def build(visible=False):
            logging.info("Fetching all four calendars through the local browser (interactive=%s)", visible)
            return builder(staging, schedule_url=schedule_url, rooms_url=config["rooms_url"],
                           additional_student_ids=config["additional_student_ids"],
                           assignments_url=os.environ.get("LECTIO_ASSIGNMENTS_URL") or None,
                           profile=profile, interactive=visible,
                           days_past=config["days_past"], days_future=config["days_future"])
        try:
            try:
                retry(lambda: build(interactive), delays=retry_delays)
            except LoginRequired:
                last = state.get("recovery_offered")
                due = not last or now - datetime.fromisoformat(last) >= timedelta(hours=24)
                if interactive or not allow_recovery or not due:
                    logging.warning("Local login is required; the last published calendars remain available")
                    return 2
                state["recovery_offered"] = now.isoformat()
                write_json(state_path, state)
                logging.info("Opening the browser for required Lectio login")
                build(True)  # Same process/lock; no console or repeated login windows.
            load_calendars(staging)
            write_json(staging / "generation.json", {"fetched_at": now.isoformat()})
            if build_only:
                logging.info("Complete generation verified at %s", staging)
                return 0
            staging.rename(pending)
            logging.info("Complete generation validated; publishing to GitHub")
            commit = retry(lambda: publisher(pending, repository=config["repository"], branch=config["branch"]),
                           delays=retry_delays)
            state.update(last_fetched=now.isoformat(), last_published=datetime.now(timezone.utc).isoformat(), commit=commit)
            state.pop("recovery_offered", None)
            write_json(state_path, state)
            shutil.rmtree(pending)
            logging.info("Calendar sync completed: %s", commit)
            return 0
        finally:
            if staging.exists() and not build_only:
                shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Update Lectio calendars through the local browser")
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[2] / "sync-config.json")
    parser.add_argument("--state-dir", type=Path, default=_default_profile_dir().parent / "local-sync")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--no-recovery", action="store_true")
    args = parser.parse_args(argv)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(args.state_dir / "sync.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[handler])
    schedule_url = os.environ.get("LECTIO_SCHEDULE_URL", "")
    env_path = args.config.resolve().parent / ".env.local"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() in {"LECTIO_SCHEDULE_URL", "LECTIO_ASSIGNMENTS_URL"}:
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        schedule_url = os.environ.get("LECTIO_SCHEDULE_URL", "")
    if not schedule_url:
        logging.error("LECTIO_SCHEDULE_URL is missing; configure .env.local")
        return 1
    try:
        return run_sync(config=read_json(args.config), state_dir=args.state_dir, schedule_url=schedule_url,
                        profile=args.profile, force=args.force, build_only=args.build_only,
                        interactive=args.interactive, allow_recovery=not args.no_recovery)
    except AlreadyRunning:
        logging.info("Another local sync is already running")
        return 0
    except LoginRequired:
        logging.warning("Login was not completed; calendars preserved")
        return 2
    except Exception as exc:
        # Playwright exceptions can contain full URLs/HTML; keep private data out of logs.
        logging.error("Sync failed (%s); last published calendars and queued files preserved", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
