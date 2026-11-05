#!/usr/bin/env python3
"""Start the MLflow tracking UI against this repo's local store.

  python scripts/mlflow_ui.py
  python scripts/mlflow_ui.py --port 5001

Override store with MLFLOW_TRACKING_URI.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.mlflow_tracking import configure, tracking_dir, tracking_uri


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Launch MLflow UI for tender experiments")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    args = p.parse_args(argv)

    from src.evaluation.mlflow_tracking import artifact_root

    configure()
    uri = tracking_uri()
    arts = artifact_root()
    arts.mkdir(parents=True, exist_ok=True)
    tracking_dir().mkdir(parents=True, exist_ok=True)
    print(f"tracking_uri={uri}")
    print(f"artifact_root={arts}")
    print(f"UI → http://{args.host}:{args.port}")
    env = os.environ.copy()
    env["MLFLOW_TRACKING_URI"] = uri
    cmd = [
        sys.executable,
        "-m",
        "mlflow",
        "ui",
        "--backend-store-uri",
        uri,
        "--default-artifact-root",
        arts.as_uri(),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    return subprocess.call(cmd, env=env, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
