"""Run backend (FastAPI + in-process simulator) and frontend (Vite) together. Ctrl-C stops both.

Usage: python scripts/dev.py   (or: make dev)
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
WIN = os.name == "nt"


def venv_python() -> str:
    candidate = BACKEND / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def pump(name: str, proc: subprocess.Popen) -> None:
    for line in iter(proc.stdout.readline, b""):
        sys.stdout.write(f"[{name}] {line.decode(errors='replace')}")
        sys.stdout.flush()


def main() -> int:
    npm = shutil.which("npm") or "npm"
    if not (FRONTEND / "node_modules").exists():
        print("[dev] installing frontend dependencies...")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True, shell=WIN)
    procs = {
        "api": subprocess.Popen([venv_python(), "-m", "uvicorn", "app.main:app", "--port", "8000", "--host", "127.0.0.1"],
                                cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT),
        "web": subprocess.Popen([npm, "run", "dev", "--", "--port", "5173", "--strictPort"], cwd=FRONTEND,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=WIN),
    }
    threads = [threading.Thread(target=pump, args=(n, p), daemon=True) for n, p in procs.items()]
    for t in threads:
        t.start()
    print("[dev] dashboard: http://localhost:5173   api: http://127.0.0.1:8000/docs")
    try:
        while all(p.poll() is None for p in procs.values()):
            threads[0].join(0.5)
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
