"""Template for wiring in your own agent: read inputs/<id>/, write preds/<id>.json.

The built-in naive baseline (slipshod/baseline.py) is a good starting point:

    uv run python examples/naive_agent.py corpus/inputs preds/
    uv run slipshod score corpus preds/
"""

import json
import sys
from pathlib import Path

from slipshod.baseline import extract


def my_agent(submission_dir: Path) -> dict:
    # Replace with your agent. It gets a folder of .eml files plus attachments/.
    return extract(submission_dir)


if __name__ == "__main__":
    inputs, preds = Path(sys.argv[1]), Path(sys.argv[2])
    preds.mkdir(parents=True, exist_ok=True)
    for sub in sorted(p for p in inputs.iterdir() if p.is_dir()):
        (preds / f"{sub.name}.json").write_text(json.dumps(my_agent(sub), indent=2, default=str))
    print(f"wrote predictions to {preds}/")
