"""python scripts/setup_tools.py : check the CLI tools the agent uses and fix what can be fixed portably."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import clitools  # noqa: E402

if __name__ == "__main__":
    clitools.ensure(auto_install=True)
    print(clitools.report())
