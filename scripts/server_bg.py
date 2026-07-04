import subprocess, sys, os

log_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
log_path = os.path.join(log_dir, "server_bg.log")

proc = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--log-level",
        "info",
    ],
    stdout=open(log_path, "w", encoding="utf-8"),
    stderr=subprocess.STDOUT,
    cwd=os.path.join(os.path.dirname(__file__), "..", "backend"),
    env={**os.environ, "PYTHONUTF8": "1"},
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
)
print(f"Server PID: {proc.pid}")
