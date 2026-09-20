from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)

    if not os.getenv("NEURALAKE_API_KEY"):
        env_file = root / ".env"
        if not env_file.exists():
            print("Missing .env. Copy .env.example to .env and set NEURALAKE_API_KEY.", file=sys.stderr)
            return 2

    env = os.environ.copy()
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "neura_marketplace.marcelo_app:app", "--host", "127.0.0.1", "--port", "8001"], env=env),
        subprocess.Popen([sys.executable, "-m", "uvicorn", "neura_marketplace.jarvis_app:app", "--host", "127.0.0.1", "--port", "8000"], env=env),
    ]

    def stop(*_):
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 5
        for proc in procs:
            try:
                proc.wait(timeout=max(0.1, deadline-time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("JARVIS:  http://127.0.0.1:8000")
    print("MARCELO: http://127.0.0.1:8001")
    try:
        while all(proc.poll() is None for proc in procs):
            time.sleep(0.5)
    finally:
        stop()
    return next((proc.returncode for proc in procs if proc.returncode), 0) or 0


if __name__ == "__main__":
    raise SystemExit(main())
