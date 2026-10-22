import sys, os, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstream/tt-support-tools/precheck"))

import gdstk
import klayout.db as pya
from tech_data import valid_layers, forbidden_layers, boundary_layer, lyp_filename
from pin_check import parse_def, pin_check
from precheck_failure import PrecheckFailure
import precheck

PDK_ROOT = str(ROOT / "pdk")
PDK_NAME = "sky130A"
os.environ["PDK_ROOT"] = PDK_ROOT
os.environ["PDK"] = PDK_NAME
precheck.PDK_ROOT = PDK_ROOT
precheck.PDK_NAME = PDK_NAME
precheck.LYP_DIR = f"{PDK_ROOT}/{PDK_NAME}/libs.tech/klayout/tech"

def check_candidate(design_name, cand_rel, top_module):
    cand_path = ROOT / cand_rel
    gds_path = cand_path / f"physical/project/runs/wokwi/final/gds/{top_module}.gds"
    lef_path = cand_path / f"physical/project/runs/wokwi/final/lef/{top_module}.lef"
    def_path = ROOT / "upstream/tt-support-tools/tech/sky130A/def/tt_block_2x2_pg.def"
    
    print(f"\n==========================================")
    print(f"Direct Template Precheck: {design_name} ({top_module})")
    print(f"GDS: {gds_path}")
    print(f"==========================================")
    
    results = {}
    
    # 1. cell name check
    try:
        precheck.cell_name_check(str(gds_path))
        results["cell_name_check"] = {"status": "PASS", "details": "No invalid cell names (# or /)"}
    except Exception as e:
        results["cell_name_check"] = {"status": "FAIL", "details": str(e)}
        
    # 2. layer check
    try:
        precheck.layer_check(str(gds_path), "sky130A")
        results["layer_check"] = {"status": "PASS", "details": "All GDS layers valid for sky130A"}
    except Exception as e:
        results["layer_check"] = {"status": "FAIL", "details": str(e)}
        
    # 3. klayout macro, forbidden layers, prBoundary
    try:
        precheck.klayout_checks(str(gds_path), top_module, "sky130A")
        results["klayout_checks"] = {"status": "PASS", "details": "Top macro name, forbidden layers, prBoundary verified"}
    except Exception as e:
        results["klayout_checks"] = {"status": "FAIL", "details": str(e)}
        
    # 4. boundary check
    try:
        precheck.boundary_check(str(gds_path), str(def_path), "sky130A")
        results["boundary_check"] = {"status": "PASS", "details": "All shapes inside 2x2 project boundary rectangle"}
    except Exception as e:
        results["boundary_check"] = {"status": "FAIL", "details": str(e)}
        
    # 5. pin check
    try:
        pin_check(str(gds_path), str(lef_path), str(def_path), top_module, False, "sky130A")
        results["pin_check"] = {"status": "PASS", "details": "LEF, GDS, and template DEF pin geometries match exactly"}
    except Exception as e:
        results["pin_check"] = {"status": "FAIL", "details": str(e)}

    # 6. power pin check
    pnl_candidates = list(cand_path.glob(f"physical/project/runs/wokwi/*/{top_module}.pnl.v"))
    pnl_path = pnl_candidates[0] if pnl_candidates else None
    if pnl_path and pnl_path.exists():
        try:
            precheck.power_pin_check(str(pnl_path), str(lef_path), False)
            results["power_pin_check"] = {"status": "PASS", "details": "VPWR/VGND power pins defined in powered netlist and LEF"}
        except Exception as e:
            results["power_pin_check"] = {"status": "FAIL", "details": str(e)}
    else:
        results["power_pin_check"] = {"status": "SKIPPED", "details": "Powered netlist not located"}

    for k, v in results.items():
        print(f"  {k:20s}: {v['status']} - {v['details']}")
    return results

if __name__ == "__main__":
    import argparse,re
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--candidate-id',required=True)
    args=parser.parse_args()
    if not all(re.fullmatch(r'[A-Za-z0-9_-]{1,80}',x) for x in [args.run_id,args.candidate_id]):parser.error('Invalid run or candidate identifier')
    run=json.loads((ROOT/'runs'/args.run_id/'run.json').read_text())
    cand_rel=f'runs/{args.run_id}/candidates/{args.candidate_id}'
    spec=json.loads((ROOT/cand_rel/'spec.json').read_text())
    entry={'design_id':run['design_id'],'run_id':args.run_id,'candidate_id':args.candidate_id,'top_module':spec['top_module'],'cand_rel':cand_rel}
    (ROOT/'reports').mkdir(exist_ok=True)
    all_res={entry['design_id']:check_candidate(entry['design_id'],entry['cand_rel'],entry['top_module'])}
    out_file=ROOT/'reports/template_precheck_results.json'
    out_file.write_text(json.dumps(all_res,indent=2))
    print(out_file)
