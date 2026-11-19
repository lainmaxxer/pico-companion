"""Look for newer firmware in the original project repositories (github.com/whowechina/<project>).

The projects do not publish GitHub releases; the author commits the finished .uf2 into the repository (usually
`Production/Firmware/<project>.uf2`). Every firmware also contains the date and time it was compiled, in the same
format the controller prints as "Built:", so "is it newer?" is a comparison of two build times.

Network access goes through two small functions (`fetch_json`, `fetch_bytes`) that tests replace.
"""
import datetime
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import firmware_update as fw

OWNER = "whowechina"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = "PicoCompanion"
MONTHS = {m: i + 1 for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}
BUILD_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +(\d{1,2}) (\d{4}) (\d\d):(\d\d):(\d\d)")


class CheckError(Exception):
    """Something went wrong while checking (no network, GitHub limit, repository not found...)."""


class NotFound(CheckError):
    """The requested file or repository does not exist."""


def _open(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            wait = ""
            try:
                minutes = max(1, int((int(e.headers.get("X-RateLimit-Reset", "0")) - time.time()) / 60) + 1)
                wait = f" Try again in about {minutes} minute{'s' if minutes != 1 else ''}."
            except (TypeError, ValueError):
                wait = " Try again in a while."
            raise CheckError("GitHub limits how often a network may check (60 requests an hour)." + wait)
        if e.code == 404:
            raise NotFound("Not found on GitHub.")
        raise CheckError(f"GitHub answered with an error ({e.code}).")
    except (urllib.error.URLError, OSError) as e:
        raise CheckError(f"Cannot reach GitHub ({getattr(e, 'reason', e)}). Check your internet connection.")


def fetch_json(url):
    try:
        return json.loads(_open(url))
    except ValueError:
        raise CheckError("GitHub sent an unexpected answer.")


def fetch_bytes(url):
    return _open(url)


def parse_build_time(text):
    """datetime from a compiler timestamp such as 'Oct  5 2026 12:55:09' (None if it does not parse)."""
    m = BUILD_RE.search(text or "")
    if not m:
        return None
    mon, day, year, hh, mm, ss = m.groups()
    return datetime.datetime(int(year), MONTHS[mon], int(day), int(hh), int(mm), int(ss))


def uf2_build_time(path):
    """Compile time embedded in a UF2 file, or None. Uses the newest timestamp if several are present."""
    with open(path, "rb") as f:
        data = f.read()
    payload = fw.uf2_payload(data).decode("latin-1")
    times = [parse_build_time(m.group(0)) for m in BUILD_RE.finditer(payload)]
    times = [t for t in times if t]
    return max(times) if times else None


def find_firmware(repo, chip="RP2040", fetch_json=fetch_json):
    """Repository path of the published firmware for `chip`, or None."""
    tree = fetch_json(f"{API}/repos/{OWNER}/{repo}/git/trees/HEAD?recursive=1")
    uf2 = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob" and t["path"].lower().endswith(".uf2")]
    uf2 = [p for p in uf2 if "production" in p.lower()] or uf2

    def usable(path):
        name = os.path.basename(path).lower()
        return "test" not in name and ("rp2350" in name) == (chip == "RP2350")

    candidates = [p for p in uf2 if usable(p)]
    candidates.sort(key=lambda p: (not os.path.basename(p).lower().startswith(repo.lower()),
                                   len(os.path.basename(p)), p))
    return candidates[0] if candidates else None


def _raw_url(repo, path):
    return f"{RAW}/{OWNER}/{repo}/HEAD/{urllib.parse.quote(path)}"


def quick_fetch(repo, chip, fetch_bytes=fetch_bytes):
    """Try the usual locations of the published firmware first. raw.githubusercontent.com is not subject to the
    API's 60-requests-an-hour limit, so most checks need no API call at all. Returns (path, bytes) or (None, None)."""
    suffix = "_rp2350" if chip == "RP2350" else ""
    for folder in ("Production/Firmware", "Production/firmware"):
        path = f"{folder}/{repo}{suffix}.uf2"
        try:
            return path, fetch_bytes(_raw_url(repo, path))
        except NotFound:
            continue
    return None, None


@dataclass
class UpdateResult:
    status: str                      # newer | current | older | unknown | no_firmware | error
    message: str = ""
    file: str = ""                   # local path of the downloaded firmware (when there is one)
    name: str = ""
    repo_build: object = None        # datetime
    device_build: object = None      # datetime
    commit_message: str = ""
    commit_date: str = ""


def _last_change(repo, path, fetch_json):
    try:
        items = fetch_json(f"{API}/repos/{OWNER}/{repo}/commits?path={urllib.parse.quote(path)}&per_page=1")
        c = items[0]["commit"]
        return c["message"].splitlines()[0], c["committer"]["date"][:10]
    except (CheckError, KeyError, IndexError, TypeError):
        return "", ""


def check_for_update(prompt_name, device_build_text, chip="RP2040", fetch_json=fetch_json,
                     fetch_bytes=fetch_bytes, dest_dir=None):
    """Compare the controller's firmware with the one published in its project repository.

    prompt_name: CLI prompt name without '>', e.g. 'musec_pico' (it is also the repository name).
    device_build_text: the controller's "Built:" text.
    """
    try:
        repo = prompt_name
        path, data = quick_fetch(repo, chip, fetch_bytes)
        if path is None:                      # unusual name or folder: look through the repository
            path = find_firmware(repo, chip, fetch_json)
            if path is None:
                return UpdateResult("no_firmware", f"The {repo} project does not publish ready-made {chip} "
                                                   "firmware. It has to be built from the source.")
            data = fetch_bytes(_raw_url(repo, path))
        dest_dir = dest_dir or os.path.join(tempfile.gettempdir(), "PicoCompanion")
        os.makedirs(dest_dir, exist_ok=True)
        name = os.path.basename(path)
        local = os.path.join(dest_dir, name)
        with open(local, "wb") as f:
            f.write(data)
        info = fw.check_uf2(local)
        if not info.ok:
            return UpdateResult("error", f"The published file is not usable: {info.error}", name=name)
        if info.prompts and prompt_name not in info.prompts:
            return UpdateResult("error", f"The published file looks like firmware for {', '.join(info.prompts)}, "
                                         f"not {prompt_name}.", name=name)
        repo_build, device_build = uf2_build_time(local), parse_build_time(device_build_text)
        base = dict(file=local, name=name, repo_build=repo_build, device_build=device_build)
        if repo_build is not None and device_build is not None:
            if repo_build == device_build:
                return UpdateResult("current", "The controller has the published firmware.", **base)
            if repo_build < device_build:
                return UpdateResult("older", "The controller has a newer or custom build than the published "
                                             "one.", **base)
        # newer or unknown: now the author's latest commit message is worth the (rate-limited) API call
        message, date = _last_change(repo, path, fetch_json)
        base.update(commit_message=message, commit_date=date)
        if repo_build is None or device_build is None:
            return UpdateResult("unknown", "Cannot tell which version is newer.", **base)
        return UpdateResult("newer", "A newer firmware is published.", **base)
    except CheckError as e:
        return UpdateResult("error", str(e))
