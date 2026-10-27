"""Client for the Java tracer jar (see tracer/)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
JAR = REPO / "tracer" / "target" / "tracer.jar"
# The JVM prints its own warnings to stdout by default, which would corrupt the JSON the tracer writes there.
QUIET = ["-Xlog:disable", "-Xlog:all=warning:stderr"]


def java_executable() -> str:
    """The Java 21 runtime: $DSAVIZ_JAVA, then mise's pinned version, then whatever is on PATH."""
    if env := os.environ.get("DSAVIZ_JAVA"):
        return env
    mise = shutil.which("mise")
    if mise:
        try:
            found = subprocess.run(
                [mise, "which", "java"], cwd=REPO, capture_output=True, text=True, timeout=20, check=True
            ).stdout.strip()
            if found:
                return found
        except (subprocess.SubprocessError, OSError):
            pass
    return shutil.which("java") or "java"


class Tracer:
    """Runs the tracer. Analysis goes through one long-lived JVM (fast); each run gets its own JVM."""

    def __init__(self) -> None:
        if not JAR.exists():
            raise RuntimeError(f"Tracer jar missing at {JAR}. Build it with: cd tracer && mvn -q package")
        self._java = java_executable()
        self._lock = threading.Lock()
        self._server: subprocess.Popen[str] | None = None

    def analyze(self, code: str) -> dict[str, Any]:
        request = json.dumps({"op": "analyze", "code": code})
        with self._lock:
            for attempt in range(2):
                server = self._ensure_server()
                assert server.stdin and server.stdout
                try:
                    server.stdin.write(request + "\n")
                    server.stdin.flush()
                    line = server.stdout.readline()
                    if line:
                        return json.loads(line)
                except (BrokenPipeError, OSError):
                    pass
                self._server = None
        raise RuntimeError("The Java tracer stopped responding")

    def run(self, code: str, method: str | None, cls: str | None, inputs: dict[str, str]) -> dict[str, Any]:
        request = {"code": code, "method": method, "cls": cls, "inputs": inputs}
        result = subprocess.run(
            [self._java, *QUIET, "-jar", str(JAR), "run"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"Tracer failed: {result.stderr.strip()[-2000:]}")
        return json.loads(result.stdout)

    def _ensure_server(self) -> subprocess.Popen[str]:
        if self._server is None or self._server.poll() is not None:
            self._server = subprocess.Popen(
                [self._java, *QUIET, "-jar", str(JAR), "serve"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        return self._server

    def close(self) -> None:
        if self._server and self._server.poll() is None:
            self._server.terminate()
