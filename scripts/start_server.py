import subprocess
import sys
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend = os.path.join(root, "backend")
os.chdir(backend)

env = os.environ.copy()
env["TRANSFORMERS_OFFLINE"] = "1"
env["HF_DATASETS_OFFLINE"] = "1"
env["HF_HUB_OFFLINE"] = "1"
env["TQDM_DISABLE"] = "1"

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    env=env,
)
print(f"Server started PID={proc.pid}")
