"""Retry transient download failures without retrying tests or solver conflicts."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

TRANSIENT = re.compile(
    r"HTTP(?:Error|\s+error)?[^\n]*(?:429|50[0-9])|(?:429|50[0-9]) (?:Server Error|Client Error|Bad Gateway|Service Unavailable)|"
    r"CondaHTTPError|ReadTimeout|ConnectTimeout|ConnectionError|"
    r"connection (?:reset|aborted|timed out)|temporary failure (?:in name resolution|resolving)|"
    r"RemoteDisconnected|network is unreachable|failed to establish a new connection|"
    r"failed to download|download.*(?:timeout|timed out)|curl: \((?:5|6|7|18|28|35|52|56)\)",
    re.IGNORECASE,
)
PERMANENT = re.compile(
    r"UnsatisfiableError|PackagesNotFoundError|ResolutionImpossible|"
    r"No matching distribution found|Could not find a version that satisfies|"
    r"HTTP[^\n]*\b4(?!29)\d{2}\b|UnavailableInvalidChannel|"
    r"(?:401|403) (?:Client Error|Unauthorized|Forbidden)", re.IGNORECASE,
)


def run(command, retries=3, delay=10, clean_prefix=None, runner=subprocess.Popen,
        sleep=time.sleep):
    """Return the original exit status after at most ``retries`` additional attempts."""
    if retries < 0 or retries > 10 or delay < 0 or delay > 60:
        raise ValueError("retries must be 0–10 and delay 0–60 seconds")
    if clean_prefix is not None:
        clean_prefix = Path(clean_prefix).resolve()
        temporary_root = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
        if not clean_prefix.is_relative_to(temporary_root) or clean_prefix == temporary_root:
            raise ValueError("the environment prefix must be inside RUNNER_TEMP")
    for attempt in range(retries + 1):
        if clean_prefix is not None:
            shutil.rmtree(clean_prefix, ignore_errors=True)
        process = runner(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
        # Keep a bounded diagnostic tail; never print the command or its credentials.
        tail = ""
        for line in process.stdout:
            print(line, end="", flush=True)
            tail = (tail + line)[-65536:]
        status = process.wait()
        if status == 0:
            return 0
        if attempt == retries or PERMANENT.search(tail) or not TRANSIENT.search(tail):
            return status
        wait = min(delay * (attempt + 1), 60)
        print(f"::warning::Temporary download failure; retry {attempt + 1}/{retries} "
              f"in {wait} seconds.", flush=True)
        sleep(wait)
    raise AssertionError("unreachable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retries", type=int, default=int(os.environ.get("MPS_RETRIES", "3")))
    parser.add_argument("--delay", type=int, default=int(os.environ.get("MPS_RETRY_DELAY", "10")))
    parser.add_argument("--clean-prefix")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command is required")
    return run(command, arguments.retries, arguments.delay, arguments.clean_prefix)


if __name__ == "__main__":
    sys.exit(main())
