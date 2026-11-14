#!/usr/bin/env python3
"""Background runner: llama3.1:8b on settlement / effective / clauses (holdout).

Pulls model if missing. Writes a live log with tqdm bars.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "outputs" / "tender_eval" / "experiments" / "llama31_weak_fields.log"
MODEL = "llama3.1:8b"
PY = str(ROOT / ".venv" / "bin" / "python")


def log(msg: str) -> None:
    line = msg.rstrip() + "\n"
    print(line, end="", flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


def run_step(title: str, argv: list[str]) -> int:
    log(f"\n===== {title} =====")
    log("cmd: " + " ".join(argv))
    t0 = time.time()
    proc = subprocess.run(argv, cwd=str(ROOT))
    dt = time.time() - t0
    log(f"exit={proc.returncode}  elapsed_sec={dt:.1f}")
    return int(proc.returncode)


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    log(f"start llama3.1 weak-field holdout probes  model={MODEL}")

    # Ensure model present
    log("pulling/ensuring model…")
    pull = subprocess.run(["ollama", "pull", MODEL], cwd=str(ROOT))
    if pull.returncode != 0:
        log("ollama pull failed")
        return pull.returncode

    smoke = subprocess.run(
        [
            PY,
            "-c",
            "import ollama; c=ollama.Client(); "
            "r=c.chat(model='llama3.1:8b', messages=[{'role':'user','content':'{\"ok\":true}'}], "
            "format='json', options={'temperature':0,'num_predict':20,'num_ctx':2048}); "
            "print(r['message']['content'] if isinstance(r,dict) else r.message.content)",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    log("smoke: " + (smoke.stdout or smoke.stderr or "").strip())
    if smoke.returncode != 0:
        return smoke.returncode

    steps = [
        (
            "1/3 settlement_date",
            [
                PY,
                "-u",
                str(ROOT / "scripts" / "eval_settlement_qwen.py"),
                "--model",
                MODEL,
                "--split",
                "holdout",
                "--run-name",
                "settlement_llama31_8b_holdout",
            ],
        ),
        (
            "2/3 effective_date (direct + Temporal→LLM)",
            [
                PY,
                "-u",
                str(ROOT / "scripts" / "eval_effective_date_qwen.py"),
                "--model",
                MODEL,
                "--mode",
                "both",
                "--split",
                "holdout",
            ],
        ),
        (
            "3/3 clauses (min tender + proration)",
            [
                PY,
                "-u",
                str(ROOT / "scripts" / "eval_llm_clause_fields.py"),
                "--model",
                MODEL,
                "--split",
                "holdout",
                "--run-name",
                "llm_llama31_8b_holdout_clauses_retrieve",
            ],
        ),
    ]

    rc = 0
    for title, argv in steps:
        code = run_step(title, argv)
        if code != 0:
            rc = code
            log(f"FAILED step: {title}")
            break

    log("\n===== DONE =====")
    log(f"log={LOG}")
    log("runs: settlement_llama31_8b_holdout, effective_date_*_llama3.1_8b_holdout, llm_llama31_8b_holdout_clauses_retrieve")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
