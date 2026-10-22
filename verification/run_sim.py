import json
import os
import sys
from pathlib import Path
from cocotb_tools.runner import get_runner

root = Path("/workspace")
candidate = Path("/candidate")
spec = json.loads((candidate/"spec.json").read_text())
output = candidate/"verification"
output.mkdir(exist_ok=True)
runner = get_runner("icarus")
runner.build(sources=[candidate/"rtl"/"project.v"],hdl_toplevel=spec["top_module"],
             build_dir=output/"sim_build",always=True,build_args=["-g2012"],timescale=("1ns","1ps"))
runner.test(hdl_toplevel=spec["top_module"],test_module="verification.test_chip",
            test_dir=output,results_xml=str(output/"results.xml"),
            extra_env={"PYTHONPATH":str(root),"CHIP_SPEC":str(candidate/"spec.json"),
                       "CHIP_RESULTS":str(output),"CHIP_INPUTS":str(root/"assets/input")})
