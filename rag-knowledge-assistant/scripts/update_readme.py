"""Copy the latest eval summary into README.md between the EVAL markers.

Keeps README numbers tied to a real, saved run (eval_results/latest/summary.md).
Usage: python scripts/update_readme.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
summary = (ROOT / "eval_results" / "latest" / "summary.md").read_text()
readme = ROOT / "README.md"
text = readme.read_text()
new = re.sub(r"(<!-- EVAL:START -->\n).*?(<!-- EVAL:END -->)", lambda m: m.group(1) + summary + m.group(2), text, flags=re.S)
readme.write_text(new)
print("README updated from eval_results/latest/summary.md")
