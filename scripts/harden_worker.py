"""Single physical queue; completion is explicitly not final signoff."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import signal
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.cli import ROOT, read, write, lock, event, assert_frozen, candidate_path, digest

run_id,candidate_id=sys.argv[1:]
candidate=candidate_path(run_id,candidate_id)
job_path=candidate/"physical/job.json"
try:
    with lock("physical-global"):
        assert_frozen()
        with lock("ledger"):
            job=read(job_path)
            job.update(state="RUNNING",started=time.time())
            write(job_path,job)
        project=candidate/"physical/project"
        # Preserve the upstream template's git identity, with candidate RTL hash bound separately.
        shutil.copytree(ROOT/"upstream/ttsky-template",project,ignore=shutil.ignore_patterns("runs","tt"))
        # tt_tool reads its own Git revision; a source-only copy breaks hardening.
        shutil.copytree(ROOT/"upstream/tt-support-tools",project/"tt")
        spec=read(candidate/"spec.json")
        info=yaml.safe_load((project/"info.yaml").read_text())
        info["project"].update(title="ChipForge "+spec["design_id"],author="ChipForge Agent",description="Verified image arithmetic core",
                                clock_hz=10000000,tiles=spec["tiles"],top_module=spec["top_module"],source_files=["project.v"])
        info["pinout"]={**{f"ui[{i}]":f"pixel[{i}]" for i in range(8)},
                        **{f"uo[{i}]":f"result[{i}]" for i in range(8)},
                        **{f"uio[{i}]":name for i,name in enumerate(
                            ["in_valid","start_window","mode[0]","mode[1]","in_ready","out_valid","busy",""])}}
        (project/"info.yaml").write_text(yaml.safe_dump(info,sort_keys=False))
        shutil.copy2(candidate/"rtl/project.v",project/"src/project.v")
        shutil.copy2(ROOT/"constraints/image_chip.sdc",project/"src/chipforge.sdc")
        config=read(project/"src/config.json")
        config["CLOCK_PERIOD"]=spec["clock_period_ns"]
        config["PNR_SDC_FILE"]="dir::chipforge.sdc"
        config["SIGNOFF_SDC_FILE"]="dir::chipforge.sdc"
        write(project/"src/config.json",config)
        wrapper_dir=ROOT/"tools/container-bin"
        wrapper_dir.mkdir(parents=True,exist_ok=True)
        wrapper=wrapper_dir/"docker"
        shutil.copy2(ROOT/"scripts/docker_limited.py",wrapper)
        wrapper.chmod(0o755)
        container_name="chipforge-"+job["job_id"]
        environment={**os.environ,"PDK_ROOT":str(ROOT/"pdk"),"PDK":"sky130A",
                     "LIBRELANE_IMAGE_OVERRIDE":"ghcr.io/librelane/librelane:3.0.14",
                     "CHIPFORGE_CONTAINER_NAME":container_name,
                     "PATH":str(wrapper_dir)+":"+str(ROOT/".venv/bin")+":"+os.environ.get("PATH","")}
        commands=[[str(ROOT/".venv/bin/python"),"tt/tt_tool.py","--create-user-config"],
                  [str(ROOT/".venv/bin/python"),"tt/tt_tool.py","--harden"],
                  [str(ROOT/".venv/bin/python"),"tt/tt_tool.py","--print-warnings"]]
        deadline=time.monotonic()+7200
        with (candidate/"physical/flow.log").open("w") as log:
            for command in commands:
                proc=subprocess.Popen(command,cwd=project,env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    code=proc.wait(timeout=max(1,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGTERM)
                    subprocess.run(['/usr/bin/docker','stop','--time','10',container_name],capture_output=True)
                    try: proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid,signal.SIGKILL)
                        proc.wait()
                    raise
                if code: raise RuntimeError("Backend failed at "+command[-1]+" exit="+str(code))
        assert_frozen()
        candidate_path(run_id,candidate_id)
        final=project/"runs/wokwi/final"
        gds=[str(p) for p in (final/"gds").glob("*.gds")]
        state_files=[str(p) for p in (project/"runs").rglob("state_out.json")]
        job.update(state="FLOW_COMPLETED_REVIEW_REQUIRED",finished=time.time(),gds_files=gds,
                   gds_sha256={p:digest(p) for p in gds},
                   final_netlists=[str(p) for p in (final/"nl").glob("*.v")],
                   final_metrics=[str(p) for p in final.glob("metrics*")],
                   state_files=state_files,final_acceptance="NOT_EVALUATED",
                   remaining_checks=["parse post-route timing and physical checks","gate-level protocol/image verification","bind final netlist/GDS/source","template precheck","export replay bundle"])
        if not gds: raise RuntimeError("No GDS produced")
        write(job_path,job)
        event(run_id,"physical_flow_completed",candidate_id=candidate_id,job=job)
except Exception as exc:
    job=read(job_path)
    job.update(state="FLOW_FAILED",finished=time.time(),error_type=type(exc).__name__,error=str(exc),final_acceptance="NOT_EVALUATED")
    write(job_path,job)
    event(run_id,"physical_failed",candidate_id=candidate_id,job=job)
    raise
