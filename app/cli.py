"""JSON tool bridge. Success comes from actual tools, never model prose."""
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(os.environ.get("CHIPFORGE_ROOT", Path(__file__).resolve().parents[1])).resolve()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+".tmp-"+uuid.uuid4().hex)
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")
    os.replace(temp, path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def log_tail(path, limit=12000):
    path = Path(path)
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell()-limit))
        return handle.read().decode("utf-8", errors="replace")


def valid_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
        raise ValueError("Invalid identifier")
    return value


@contextlib.contextmanager
def lock(name):
    directory = ROOT/".locks"
    directory.mkdir(exist_ok=True)
    with (directory/(name+".lock")).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def assert_frozen():
    expected = read(ROOT/"verification.freeze.json")
    changed = [name for name, sha in expected.items() if not (ROOT/name).is_file() or digest(ROOT/name) != sha]
    if changed:
        raise ValueError("Frozen contract/verification changed: "+", ".join(changed))


def run_path(run_id):
    path = ROOT/"runs"/valid_id(run_id)
    if not (path/"run.json").exists():
        raise ValueError("Unknown run")
    return path


def candidate_path(run_id, candidate_id):
    path = run_path(run_id)/"candidates"/valid_id(candidate_id)
    if not (path/"manifest.json").is_file():
        raise ValueError("Unknown candidate")
    if digest(path/"rtl/project.v") != read(path/"manifest.json")["rtl_sha256"]:
        raise ValueError("Candidate source changed; submit a new immutable candidate")
    design_id = read(path/"manifest.json")["design_id"]
    if digest(path/"spec.json") != digest(ROOT/"specs"/(design_id+".json")):
        raise ValueError("Candidate spec differs from frozen design contract")
    return path


def event(owner_run_id, kind, **data):
    with lock("events-"+valid_id(owner_run_id)):
        with (run_path(owner_run_id)/"events.jsonl").open("a") as handle:
            handle.write(json.dumps({"time":time.time(),"kind":kind,**data},ensure_ascii=False)+"\n")


def doctor(_):
    runtime = ROOT/"runtime/agh/agnes.mjs"
    sim = subprocess.run(["docker","image","inspect","chipforge-sim:20261003"],capture_output=True)
    return {"root":str(ROOT),"agh_built":runtime.is_file(),"node":(ROOT/"tools/node/bin/node").is_file(),
            "sim_image_ready":sim.returncode==0,"model_ready":"not_probed",
            "librelane_python":str(ROOT/".venv/bin/python"),"pdk_directory":str(ROOT/"pdk"),
            "preparation_status":read(ROOT/"reports/preparation_status.json") if (ROOT/"reports/preparation_status.json").exists() else {}}


def get_spec(args):
    return read(ROOT/"specs"/(valid_id(args["design_id"])+".json"))


def new_run(args):
    assert_frozen()
    spec = get_spec(args)
    run_id = "r-"+time.strftime("%Y%m%d-%H%M%S",time.gmtime())+"-"+uuid.uuid4().hex[:6]
    path = ROOT/"runs"/run_id
    path.mkdir(parents=True)
    value = {"run_id":run_id,"design_id":spec["design_id"],"created":time.time(),
             "state":"SPEC_FROZEN","request":args.get("request",""),"agh_session_id":None,
             "limits":{"rtl_candidates":20,"physical_jobs":8,"physical_parallel":1},
             "budget_scope":"project_global_including_calibration"}
    write(path/"run.json", value)
    write(path/"spec.json", spec)
    event(run_id,"run_created",design_id=spec["design_id"])
    return value


def submit_rtl(args):
    assert_frozen()
    run_id = args["run_id"]
    run = read(run_path(run_id)/"run.json")
    source = args["source"]
    if not isinstance(source,str) or not 1 <= len(source.encode()) <= 65536:
        raise ValueError("RTL source must be 1..65536 bytes")
    parent = args.get("parent_candidate_id")
    if parent:
        candidate_path(run_id,parent)
    with lock("ledger"):
        ledger = read(ROOT/".ledger.json") if (ROOT/".ledger.json").exists() else {"rtl_candidates":0,"physical_jobs":0}
        if ledger["rtl_candidates"] >= 20:
            raise ValueError("Project RTL candidate budget exhausted")
        candidate_id = "c"+str(ledger["rtl_candidates"]+1).zfill(3)
        path = run_path(run_id)/"candidates"/candidate_id
        (path/"rtl").mkdir(parents=True)
        (path/"rtl/project.v").write_text(source)
        shutil.copy2(ROOT/"specs"/(run["design_id"]+".json"),path/"spec.json")
        manifest={"candidate_id":candidate_id,"run_id":run_id,"design_id":run["design_id"],
                  "parent":parent,"created":time.time(),"rtl_sha256":digest(path/"rtl/project.v"),
                  "status":"RTL_SUBMITTED","origin":"tool_submission_pending_trace_binding"}
        write(path/"manifest.json",manifest)
        ledger["rtl_candidates"]+=1
        write(ROOT/".ledger.json",ledger)
    event(run_id,"rtl_submitted",**manifest)
    return manifest


def validate(args):
    assert_frozen()
    path = candidate_path(args["run_id"],args["candidate_id"])
    with lock("validate-"+args["run_id"]+"-"+args["candidate_id"]):
        output=path/"verification"
        if (output/"result.json").exists():
            return read(output/"result.json")
        output.mkdir(exist_ok=True)
        container_name="chipforge-sim-"+uuid.uuid4().hex[:12]
        command=["docker","run","--rm","--name",container_name,"--network","none","--cpus","2","--memory","2g",
                 "--pids-limit","256","--user",f"{os.getuid()}:{os.getgid()}",
                 "-e","PYTHONDONTWRITEBYTECODE=1","-e","PYTHONPATH=/workspace",
                 "-v",str(ROOT)+":/workspace:ro","-v",str(path)+":/candidate",
                 "chipforge-sim:20261003","python","/workspace/verification/run_sim.py"]
        started=time.time()
        try:
            with (output/"simulator.log").open("w") as log:
                proc=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600)
            code=proc.returncode
        except subprocess.TimeoutExpired:
            subprocess.run(["docker","stop","--time","10",container_name],capture_output=True,timeout=30)
            code=124
        xml=output/"results.xml"
        passed=False
        cases=0
        if xml.exists():
            try:
                tree=ET.parse(xml)
                tests=tree.findall(".//testcase")
                cases=len(tests)
                passed=code==0 and cases>0 and all(t.find("failure") is None and t.find("error") is None and t.find("skipped") is None for t in tests)
            except ET.ParseError:
                pass
        metrics_path=output/"protocol_metrics.json"
        passed=passed and metrics_path.exists()
        assert_frozen()
        candidate_path(args["run_id"],args["candidate_id"])
        result={"status":"RTL_PASS" if passed else "RTL_FAIL","exit_code":code,"testcases":cases,
                "elapsed_seconds":time.time()-started,"rtl_sha256":digest(path/"rtl/project.v"),
                "log":str(output/"simulator.log"),"xml":str(xml),
                "metrics":read(metrics_path) if metrics_path.exists() else None,
                "failure_excerpt":log_tail(output/"simulator.log") if not passed else None}
        write(output/"result.json",result)
        event(args["run_id"],"rtl_validated",candidate_id=args["candidate_id"],result=result)
        return result


def harden(args):
    assert_frozen()
    path=candidate_path(args["run_id"],args["candidate_id"])
    verified=path/"verification/result.json"
    if not verified.exists() or read(verified)["status"]!="RTL_PASS":
        raise ValueError("Full RTL verification required before physical implementation")
    if shutil.disk_usage(ROOT).free < 30*1024**3:
        raise ValueError("Physical implementation requires at least 30 GiB free disk")
    with lock("ledger"):
        job_path=path/"physical/job.json"
        if job_path.exists():
            return read(job_path)
        ledger=read(ROOT/".ledger.json")
        if ledger["physical_jobs"]>=8:
            raise ValueError("Project physical job budget exhausted")
        job={"job_id":"p-"+uuid.uuid4().hex[:10],"state":"QUEUED","created":time.time(),
             "run_id":args["run_id"],"candidate_id":args["candidate_id"],"final_acceptance":"NOT_EVALUATED"}
        write(job_path,job)
        ledger["physical_jobs"]+=1
        write(ROOT/".ledger.json",ledger)
        with (path/"physical/worker.log").open("w") as log:
            proc=subprocess.Popen([str(ROOT/".venv/bin/python"),str(ROOT/"scripts/harden_worker.py"),
                                   args["run_id"],args["candidate_id"]],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                  env={**os.environ,"CHIPFORGE_ROOT":str(ROOT)},start_new_session=True)
        job["worker_pid"]=proc.pid
        write(job_path,job)
    event(args["run_id"],"physical_queued",**job)
    return job


def job_status(args):
    path=candidate_path(args["run_id"],args["candidate_id"])/"physical/job.json"
    if not path.exists():
        return {"state":"NOT_SUBMITTED"}
    value=read(path)
    value["flow_log_tail"]=log_tail(path.parent/"flow.log")
    pid=value.get("worker_pid")
    if pid and value["state"] in ("QUEUED","RUNNING"):
        try:
            os.kill(pid,0)
        except ProcessLookupError:
            value["observation"]="WORKER_NOT_ALIVE_REQUIRES_RECOVERY"
    return value


def status(args):
    path=run_path(args["run_id"])
    candidates=[]
    for p in sorted((path/"candidates").glob("*/manifest.json")):
        record=read(p)
        for field,relative in [("verification","verification/result.json"),("physical","physical/job.json")]:
            q=p.parent/relative
            if q.exists(): record[field]=read(q)
        candidates.append(record)
    return {"run":read(path/"run.json"),"candidates":candidates,
            "project_usage":read(ROOT/".ledger.json") if (ROOT/".ledger.json").exists() else {"rtl_candidates":0,"physical_jobs":0}}


def cancel_job(args):
    assert_frozen()
    cand = candidate_path(args["run_id"], args["candidate_id"])
    path = cand / "physical/job.json"
    if not path.exists():
        return {"state": "NOT_SUBMITTED"}
    with lock("job-" + args["run_id"] + "-" + args["candidate_id"]):
        job = read(path)
        if job["state"] in ("QUEUED", "RUNNING"):
            pid = job.get("worker_pid")
            if pid:
                try:
                    os.kill(pid, 15)  # SIGTERM
                except ProcessLookupError:
                    pass
            cid = "chipforge-" + job.get("job_id", "")
            subprocess.run(["docker", "stop", "--time", "5", cid], capture_output=True)
            job.update(state="FLOW_CANCELLED", finished=time.time())
            write(path, job)
            event(args["run_id"], "physical_cancelled", candidate_id=args["candidate_id"], job=job)
    return job


def recover_job(args):
    assert_frozen()
    cand = candidate_path(args["run_id"], args["candidate_id"])
    path = cand / "physical/job.json"
    if not path.exists():
        return {"state": "NOT_SUBMITTED"}
    with lock("job-" + args["run_id"] + "-" + args["candidate_id"]):
        job = read(path)
        pid = job.get("worker_pid")
        dead = True
        if pid:
            try:
                os.kill(pid, 0)
                dead = False
            except ProcessLookupError:
                dead = True
        if dead and job["state"] in ("QUEUED", "RUNNING"):
            cid = "chipforge-" + job.get("job_id", "")
            subprocess.run(["docker", "stop", "--time", "5", cid], capture_output=True)
            job.update(state="FLOW_FAILED_RECOVERED", finished=time.time(), observation="WORKER_RECOVERED_AFTER_ABRUPT_EXIT")
            write(path, job)
            event(args["run_id"], "physical_recovered", candidate_id=args["candidate_id"], job=job)
    return job


VALID_RUN_STATES = {"SPEC_FROZEN", "RUN_ACTIVE", "FLOW_COMPLETED", "SIGNED_OFF", "FAILED"}


def audit_current_candidate(entry):
    """Run the independent auditor without writing or sharing global report state."""
    source = Path(__file__).resolve().parents[1] / "scripts/signoff_auditor.py"
    spec = importlib.util.spec_from_file_location("chipforge_current_signoff", source)
    auditor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor)
    auditor.ROOT = ROOT
    return auditor.audit_design(entry, read(ROOT / "verification.freeze.json"))


def require_current_signoff(run, candidate_id, cand, report):
    recorded = report.get("designs", {}).get(run["design_id"], {})
    entry = {"design_id": run["design_id"], "run_id": run["run_id"], "candidate_id": candidate_id}
    if any(recorded.get(key) != value for key, value in entry.items()):
        raise ValueError("Cannot transition to SIGNED_OFF: formal report design/run/candidate identity mismatch")
    manifest = read(cand / "manifest.json")
    if any(manifest.get(key) != value for key, value in entry.items()):
        raise ValueError("Cannot transition to SIGNED_OFF: candidate manifest identity mismatch")
    try:
        xml = ET.parse(cand / "verification_gate/results.xml").getroot()
        cases = list(xml.iter("testcase"))
        bad = any(next(xml.iter(tag), None) is not None for tag in ("failure", "error", "skipped"))
        declared_bad = any(int(node.get(key, "0")) for node in xml.iter()
                           for key in ("failures", "errors", "skipped"))
        if not cases or bad or declared_bad:
            raise ValueError("failed, skipped or empty gate test results")
    except (OSError, ET.ParseError, ValueError) as exc:
        raise ValueError(f"Cannot transition to SIGNED_OFF: current gate XML is not PASS: {exc}") from exc
    if report.get("errors"):
        raise ValueError("Cannot transition to SIGNED_OFF: formal audit has errors")
    try:
        current = audit_current_candidate(entry)
    except Exception as exc:
        raise ValueError(f"Cannot transition to SIGNED_OFF: current audit failed: {exc}") from exc
    expected = {f"C{i:02d}" for i in range(1, 20)}
    for label, rec in (("formal", recorded), ("current", current)):
        criteria = rec.get("criteria", [])
        if (rec.get("overall_status") != "PASS" or len(criteria) != len(expected)
                or {c.get("id") for c in criteria} != expected
                or any(c.get("status") != "PASS" for c in criteria)):
            failed = [c.get("id") for c in criteria if c.get("status") != "PASS"]
            raise ValueError(f"Cannot transition to SIGNED_OFF: {label} audit is incomplete or failed: {failed}")
    for key in ("hashes", "evidence_binding"):
        if not recorded.get(key) or recorded[key] != current.get(key):
            raise ValueError(f"Cannot transition to SIGNED_OFF: stale formal report {key}; rerun strict audit")
    return {"protocol": "delivery_closure_v3", "audited_at_utc": current["audited_at_utc"],
            "criteria_passed": len(current["criteria"]), "evidence_binding": current["evidence_binding"]}


def update_run_state(args):
    assert_frozen()
    path = run_path(args["run_id"])
    run = read(path / "run.json")
    new_state = valid_id(args["state"])
    if new_state not in VALID_RUN_STATES:
        raise ValueError(f"Invalid run state '{new_state}'. Allowed: {VALID_RUN_STATES}")

    winning_cand = args.get("winning_candidate_id")
    if new_state == "SIGNED_OFF":
        if not winning_cand:
            raise ValueError("winning_candidate_id is required to transition to SIGNED_OFF")
        cand_p = candidate_path(args["run_id"], winning_cand)
        v_res = cand_p / "verification/result.json"
        if not v_res.is_file() or read(v_res).get("status") != "RTL_PASS":
            raise ValueError(f"Cannot transition to SIGNED_OFF: candidate '{winning_cand}' has not passed RTL verification")
        p_res = cand_p / "physical/job.json"
        if not p_res.is_file() or read(p_res).get("state") not in ("FLOW_COMPLETED", "FLOW_COMPLETED_REVIEW_REQUIRED"):
            raise ValueError(f"Cannot transition to SIGNED_OFF: candidate '{winning_cand}' physical job is not completed")
        g_res = cand_p / "verification_gate/protocol_metrics.json"
        if not g_res.is_file() or read(g_res).get("kind") != "gate_level_simulation":
            raise ValueError(f"Cannot transition to SIGNED_OFF: candidate '{winning_cand}' lacks gate-level verification")
        signoff_f = ROOT / "reports/final_acceptance_signoff.json"
        if not signoff_f.is_file():
            raise ValueError(f"Cannot transition to SIGNED_OFF: reports/final_acceptance_signoff.json does not exist")
        signoff_data = read(signoff_f)
        des_signoff = signoff_data.get("designs", {}).get(run["design_id"], {})
        if des_signoff.get("candidate_id") != winning_cand or des_signoff.get("overall_status") != "PASS":
            raise ValueError(f"Cannot transition to SIGNED_OFF: candidate '{winning_cand}' is not PASS in formal acceptance signoff (status: {des_signoff.get('overall_status')})")
        receipt = require_current_signoff(run, winning_cand, cand_p, signoff_data)
        run["acceptance_receipt"] = receipt

    run["state"] = new_state
    if winning_cand:
        run["winning_candidate_id"] = valid_id(winning_cand)
    write(path / "run.json", run)
    event(args["run_id"], "run_state_updated", state=new_state, winning_candidate_id=winning_cand)
    return run


ACTIONS={"doctor":doctor,"get_spec":get_spec,"new_run":new_run,"submit_rtl":submit_rtl,
         "validate":validate,"harden":harden,"job_status":job_status,"status":status,
         "cancel_job":cancel_job,"recover_job":recover_job,"update_run_state":update_run_state}


def main():
    try:
        if len(sys.argv)!=2 or sys.argv[1] not in ACTIONS:
            raise ValueError("Action required: "+", ".join(ACTIONS))
        raw=sys.stdin.read()
        args=json.loads(raw) if raw.strip() else {}
        if not isinstance(args,dict): raise ValueError("JSON object required")
        result=ACTIONS[sys.argv[1]](args)
        print(json.dumps({"ok":True,"result":result},ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok":False,"error_type":type(exc).__name__,"error":str(exc)},ensure_ascii=False))
        raise SystemExit(1)


if __name__=="__main__":
    main()
