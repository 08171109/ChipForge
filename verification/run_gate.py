"""In-container gate-level (mapped netlist) runner, modelled on verification/run_sim.py.

Environment:
  CHIP_SPEC       frozen spec JSON (top_module must match the netlist)
  CHIP_NETLIST    mapped gate-level netlist file(s), os.pathsep-separated
  CHIP_PDK_MODELS PDK cell model files, os.pathsep-separated
  CHIP_RESULTS    output directory (results.xml, protocol_metrics.json, PNGs)
  CHIP_INPUTS     optional input image directory (passed through to the test)
  CHIP_SEED       deterministic seed

Simulation is zero-delay logic/cycle verification only: no SDF, no dynamic timing claim.
"""
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from cocotb_tools.runner import get_runner

root = Path(os.environ.get("CHIPFORGE_ROOT", "/workspace"))
# cocotb_tools.runner overwrites the simulator's PYTHONPATH with this process's
# sys.path, so the repository root must be importable here for verification.* imports.
sys.path.insert(0, str(root))
spec = json.loads(Path(os.environ["CHIP_SPEC"]).read_text())
netlists = [Path(p) for p in os.environ["CHIP_NETLIST"].split(os.pathsep) if p]
models = [Path(p) for p in os.environ.get("CHIP_PDK_MODELS", "").split(os.pathsep) if p]
results = Path(os.environ["CHIP_RESULTS"])
results.mkdir(parents=True, exist_ok=True)

runner = get_runner("icarus")
# -DFUNCTIONAL selects the behavioral cell models. Without it iverilog compiles the
# timing models, whose $setuphold-delayed CLK/D signals are never driven (iverilog
# does not implement timing checks), so every flop would stay X forever.
runner.build(sources=models + netlists, hdl_toplevel=spec["top_module"],
             build_dir=results/"sim_build", always=True,
             build_args=["-g2012", "-DFUNCTIONAL"], timescale=("1ns", "1ps"))

env = {key: os.environ[key] for key in
       ("CHIP_SPEC", "CHIP_NETLIST", "CHIP_PDK_MODELS", "CHIP_RESULTS", "CHIP_INPUTS", "CHIP_SEED")
       if key in os.environ}
env["PYTHONPATH"] = str(root)
xml = runner.test(hdl_toplevel=spec["top_module"], test_module="verification.test_gate",
                  test_dir=results, results_xml=str(results/"results.xml"), extra_env=env)

# A missing or failing results file is never a pass.
if not Path(xml).is_file():
    print("gate runner: results.xml missing", file=sys.stderr)
    sys.exit(2)
tests = ET.parse(xml).getroot().findall(".//testcase")
failed = [t.get("name") for t in tests
          if t.find("failure") is not None or t.find("error") is not None or t.find("skipped") is not None]
if not tests or failed:
    print(f"gate runner: {len(failed)}/{len(tests)} testcases failed", file=sys.stderr)
    sys.exit(1)
if not (results/"protocol_metrics.json").is_file():
    print("gate runner: protocol_metrics.json missing", file=sys.stderr)
    sys.exit(1)
print(f"gate runner: {len(tests)} testcase(s) passed")
