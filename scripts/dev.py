"""Run backend (FastAPI + in-process simulator) and frontend (Vite) together. Ctrl-C stops both.

Usage: python scripts/dev.py           start everything (or: make dev)
       python scripts/dev.py --setup   install dependencies only (or: make install)

Works on Windows, macOS and Linux without make. On each start it:
  - creates backend/.venv and installs backend/requirements.txt when missing or changed
  - runs `npm install` when frontend/node_modules is missing or package-lock.json changed
  - checks Python, Node and the two ports, and says what to do if something is wrong
"""
from __future__ import annotations

import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"
WIN = os.name == "nt"
API_PORT, WEB_PORT = 8000, 5173


def say(msg: str) -> None:
    print(f"[dev] {msg}", flush=True)


def fail(msg: str) -> int:
    print(f"\n[dev] ERROR: {msg}\n", file=sys.stderr, flush=True)
    return 1


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if WIN else "bin/python")


def ensure_backend() -> None:
    py = venv_python()
    if not py.exists():
        say(f"creating {VENV.relative_to(ROOT)} ...")
        venv.EnvBuilder(with_pip=True).create(VENV)
    marker = VENV / ".requirements.sha256"
    want = digest(BACKEND / "requirements.txt")
    if marker.exists() and marker.read_text().strip() == want:
        return
    say("installing backend dependencies (first run takes a minute) ...")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(BACKEND / "requirements.txt")], check=True)
    marker.write_text(want)


def ensure_frontend(npm: str) -> None:
    marker = FRONTEND / "node_modules" / ".lockfile.sha256"
    want = digest(FRONTEND / "package-lock.json")
    if marker.exists() and marker.read_text().strip() == want:
        return
    say("installing frontend dependencies ...")
    subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True, shell=WIN)
    marker.write_text(want)


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def node_major(node: str) -> int:
    out = subprocess.run([node, "--version"], capture_output=True, text=True, shell=WIN).stdout.strip()
    try:
        return int(out.lstrip("v").split(".")[0])
    except ValueError:
        return 0


def pump(name: str, proc: subprocess.Popen) -> None:
    for line in iter(proc.stdout.readline, b""):
        sys.stdout.write(f"[{name}] {line.decode(errors='replace')}")
        sys.stdout.flush()


def wait_for_api(timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/api/health", timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    if sys.version_info < (3, 10):
        return fail(f"Python 3.10 or newer is required (this is {sys.version.split()[0]}). "
                    "Install it from https://www.python.org/downloads/ and run: python scripts/dev.py")
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        return fail("Node.js 18 or newer is required and was not found on PATH. Install it from https://nodejs.org/")
    if node_major(node) < 18:
        return fail("Node.js 18 or newer is required. Run `node --version` to check, then upgrade from https://nodejs.org/")
    for port, what in ((API_PORT, "API"), (WEB_PORT, "dashboard")):
        if "--setup" not in sys.argv and port_busy(port):
            return fail(f"port {port} (the {what}) is already in use. Stop the other process "
                        f"(maybe an earlier `make dev` that is still running) and try again.")
    try:
        ensure_backend()
        ensure_frontend(npm)
    except subprocess.CalledProcessError as e:
        return fail(f"setup step failed: {' '.join(map(str, e.cmd))}\nScroll up for the underlying error.")
    if "--setup" in sys.argv:
        say("dependencies are installed. Start with: python scripts/dev.py")
        return 0

    procs = {
        "api": subprocess.Popen([str(venv_python()), "-m", "uvicorn", "app.main:app", "--port", str(API_PORT), "--host", "127.0.0.1"],
                                cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT),
        "web": subprocess.Popen([npm, "run", "dev", "--", "--port", str(WEB_PORT), "--strictPort"], cwd=FRONTEND,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=WIN),
    }
    threads = [threading.Thread(target=pump, args=(n, p), daemon=True) for n, p in procs.items()]
    for t in threads:
        t.start()
    say("starting ... the API builds 6 months of simulated history on first start (10-20 s)")
    if wait_for_api():
        say(f"ready: open http://localhost:{WEB_PORT}")
        say(f"API docs: http://127.0.0.1:{API_PORT}/docs   Ctrl-C stops both")
    else:
        say("the API did not answer within 90 s; check the [api] lines above for the error")
    try:
        while all(p.poll() is None for p in procs.values()):
            time.sleep(0.5)
        for name, p in procs.items():
            if p.poll() is not None:
                say(f"{name} exited with code {p.returncode}; stopping the other one")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values():
            if p.poll() is None:
                if WIN:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
                else:
                    p.send_signal(signal.SIGINT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
