"""Atomic calendar-only GitHub publication without touching the local git tree."""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote


CALENDAR_FILES = ("calendar.ics", "calendar-67380948067.ics", "assignments.ics", "free_classrooms.ics")


class PublishError(RuntimeError):
    pass


class GitHubError(PublishError):
    def __init__(self, status=None):
        self.status = status
        super().__init__(f"GitHub API request failed (HTTP {status or 'unknown'}); calendar files retained locally")


class GitHubAPI:
    def __init__(self, repository: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("GitHub repository must be owner/name")
        self.prefix = f"repos/{repository}/git/"

    def call(self, endpoint, data=None, method=None):
        command = ["gh", "api", self.prefix + endpoint, "--method", method or ("POST" if data is not None else "GET")]
        kwargs = dict(capture_output=True, text=True, encoding="utf-8", timeout=60)
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        if data is not None:
            command += ["--input", "-"]
            kwargs["input"] = json.dumps(data)
        try:
            result = subprocess.run(command, **kwargs)
        except (OSError, subprocess.TimeoutExpired):
            raise PublishError("GitHub CLI could not complete publication; retry later") from None
        if result.returncode:
            status = re.search(r"HTTP (\d{3})", result.stderr)
            raise GitHubError(int(status[1]) if status else None)
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise PublishError("GitHub returned an invalid API response") from None


def canonical_calendar(data: bytes) -> str:
    """DTSTAMP describes generation time, not a change to calendar content."""
    return "\n".join(line for line in data.decode("utf-8-sig").splitlines()
                     if not line.startswith("DTSTAMP:")).strip()


def validate_calendar(data: bytes) -> None:
    text = data.decode("utf-8-sig").replace("\r\n ", "").replace("\r\n\t", "")
    lines = text.splitlines()
    if not lines or lines[0] != "BEGIN:VCALENDAR" or lines[-1] != "END:VCALENDAR" or "VERSION:2.0" not in lines:
        raise ValueError("Invalid iCalendar envelope")
    stack, event_lines, uids = [], [], set()
    for line in lines:
        if line.startswith("BEGIN:"):
            stack.append(line[6:])
            if line == "BEGIN:VEVENT":
                event_lines = []
        elif line.startswith("END:"):
            if not stack or stack.pop() != line[4:]:
                raise ValueError("Unbalanced iCalendar components")
            if line == "END:VEVENT":
                uid = [p[4:] for p in event_lines if p.startswith("UID:")]
                if (len(uid) != 1 or not uid[0] or uid[0] in uids
                        or not any(p.startswith(("DTSTART:", "DTSTART;")) for p in event_lines)):
                    raise ValueError("An event has a missing/duplicate UID or start date")
                uids.add(uid[0])
        elif stack and stack[-1] == "VEVENT":
            event_lines.append(line)
    if stack:
        raise ValueError("Unclosed iCalendar component")


def load_calendars(directory: Path) -> dict[str, bytes]:
    result = {}
    for name in CALENDAR_FILES:
        path = directory / name
        if path.is_symlink():
            raise ValueError("Calendar files must not be symbolic links")
        data = path.read_bytes()
        validate_calendar(data)
        result[f"docs/{name}"] = data
    return result


def publish_calendars(directory: Path, *, repository="2zap2/Lectio", branch="main", api=None) -> str:
    files = load_calendars(directory)  # Validate the entire generation before any API writes.
    api = api or GitHubAPI(repository)
    ref = "heads/" + quote(branch, safe="")
    blobs = {}
    for attempt in range(4):
        head = api.call("ref/" + ref)["object"]["sha"]
        base_tree = api.call("commits/" + head)["tree"]["sha"]
        tree = api.call("trees/" + base_tree + "?recursive=1")
        if tree.get("truncated"):
            raise PublishError("GitHub returned an incomplete repository tree")
        entries = {e["path"]: e for e in tree["tree"]}
        changes = []
        for path, data in files.items():
            current = entries.get(path)
            if current and current.get("type") == "blob" and current.get("mode") == "100644":
                old = api.call("blobs/" + current["sha"])
                if canonical_calendar(base64.b64decode(old["content"])) == canonical_calendar(data):
                    continue
            if path not in blobs:
                blobs[path] = api.call("blobs", {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})["sha"]
            changes.append({"path": path, "mode": "100644", "type": "blob", "sha": blobs[path]})
        if not changes:
            print("Calendar content unchanged; no commit needed")
            return head
        new_tree = api.call("trees", {"base_tree": base_tree, "tree": changes})["sha"]
        commit = api.call("commits", {"message": "Update calendars from local browser", "tree": new_tree, "parents": [head]})["sha"]
        try:
            api.call("refs/" + ref, {"sha": commit, "force": False}, method="PATCH")
            print(f"Published complete calendar generation: {commit}")
            return commit
        except GitHubError as exc:
            if exc.status not in {409, 422}:
                raise
            # Rebuild on the new head. Never force-push or drop other changes.
    raise PublishError("The branch kept changing; retry publication later")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", type=Path, required=True)
    args = parser.parse_args()
    load_calendars(args.validate)
    print("All four calendar files are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
