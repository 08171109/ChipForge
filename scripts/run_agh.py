"""Explicit user-started, finite AGH CLI bridge. Does not configure credentials."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.cli import ROOT, run_path, read, write, event, assert_frozen

parser=argparse.ArgumentParser()
target=parser.add_mutually_exclusive_group(required=True)
target.add_argument('--run-id')
target.add_argument('--smoke',action='store_true',help='Read-only model/plugin test; does not design RTL')
parser.add_argument('--model',help='Optional explicit selection; must match the configured ChipForge model')
parser.add_argument('--max-candidates',type=int,help='Per-design candidate allocation stated to the design agent; the global ledger still caps the project')
parser.add_argument('--timeout',type=int,default=1800)
args=parser.parse_args()
if not 10 <= args.timeout <= 3600:
    raise SystemExit('Timeout must be 10..3600 seconds')
assert_frozen()
selection_path=ROOT/'model.selection.json'
if not selection_path.is_file():
    raise SystemExit('Configure the ChipForge model account before starting AGH')
selection=read(selection_path)
if selection.get('model')!='deepseek-flash' or selection.get('profile')!='local-dev':
    raise SystemExit('Expected the configured DeepSeek Flash account in local-dev')
model=selection['route']+'/'+selection['model']
if args.model is not None and args.model!=model:
    raise SystemExit('Explicit model differs from the frozen ChipForge selection')
slots=['primary','escalation','fast','compaction','verifier']
if selection.get('slots')!=slots:
    raise SystemExit('Unexpected text model-slot mapping')
path=ROOT if args.smoke else run_path(args.run_id)
node=ROOT/'tools/node/bin/node'
entry=ROOT/'runtime/agh/agnes.mjs'
if not node.is_file() or not entry.is_file():
    raise SystemExit('AGH build not ready; read preparation status')
env={**os.environ,'PATH':str(node.parent)+':'+os.environ.get('PATH',''),
     'CHIPFORGE_ROOT':str(ROOT),'AGH_HOME':str(ROOT/'runtime/agh-home'),'AGNES_PROFILE':'local-dev'}
if args.smoke:
    prompt='''This is a read-only ChipForge model/plugin acceptance test, not a chip design task.
Call chip_get_spec with design_id=sobel_fast, then call chip_get_spec with design_id=image_multi.
Use the actual tool results to report the Sobel threshold, clock period, and image_multi operation list.
Answer briefly in Chinese. You must actually invoke the two chip_get_spec tools.
Do not submit RTL, launch physical jobs, edit files, use shell, create subagents, or design circuits.'''
else:
    run=read(path/'run.json')
    spec=read(path/'spec.json')
    if args.max_candidates is not None and not 1 <= args.max_candidates <= 20:
        raise SystemExit('Candidate allocation must be 1..20')
    allocation=args.max_candidates or 6
    design_id = run['design_id']
    L = spec.get('latency_after_last_sample')
    II = spec.get('minimum_window_initiation_interval')
    top = spec.get('top_module')

    timing_rules = ""
    if design_id == "sobel_fast":
        timing_rules = f"""- For L={L} and II={II}:
  * Clock edge 8 (9th sample accepted): state <= S_CALC1 (busy=1, in_ready=0, out_valid_r=0).
  * Clock edge 9 (cycle 1 after 9th sample): compute and register uo_r <= cmp_pix; state <= S_OUT; out_valid_r=0.
  * Clock edge 10 (cycle 2 after 9th sample): out_valid_r <= 1'b1; state <= S_IDLE.
  * Clock edge 11 (cycle 3 after 9th sample = cycle 11 from start): state is in S_IDLE, so out_valid_r=0, in_ready=1. Next start_window can be accepted on this edge (II=11!)."""
    elif design_id == "sobel_compact":
        timing_rules = f"""- For L={L} and II={II}:
  * Clock edge 8 (9th sample accepted): state <= S_COMPUTE, step <= 5'd1 (busy=1, in_ready=0, out_valid_r=0).
  * In S_COMPUTE, use a counter (step from 1 to 21):
    - During steps 1 to 20: calculate/accumulate arithmetic iteratively with shared ALU or registers; out_valid_r remains 0.
    - At step 20 (cycle 20 after 9th sample): register final result uo_r <= cmp_pix; out_valid_r remains 0.
    - At step 21 (cycle 21 after 9th sample): out_valid_r <= 1'b1; state <= S_IDLE.
    - Next cycle (step=22 = cycle 30 from window start): state is back in S_IDLE, so out_valid_r returns to 0, and in_ready is 1. Next start_window can be accepted on this edge (II=30!)."""
    elif design_id == "image_multi":
        timing_rules = f"""- For L={L} and II={II}:
  * Clock edge 8 (9th sample accepted): state <= S_CALC1 (busy=1, in_ready=0, out_valid_r=0).
  * Clock edge 9 (cycle 1 after 9th sample): compute and register uo_r <= selected_result; state <= S_OUT; out_valid_r=0.
  * Clock edge 10 (cycle 2 after 9th sample): out_valid_r <= 1'b1; state <= S_IDLE.
  * Clock edge 11 (cycle 3 after 9th sample = cycle 11 from start): state is in S_IDLE, so out_valid_r=0, in_ready=1. Next start_window can be accepted on this edge (II=11!).
- Mode latching and operations:
  * In IDLE or S_COLLECT when accept && start_window: latch mode <= uio_in[3:2]; later changes are ignored for that window.
  * mode 0: Sobel binary (M = |Gx| + |Gy|, strict > 160 -> 255, else 0).
  * mode 1: Gaussian blur: sum = (p00 + 2*p01 + p02 + 2*p10 + 4*p11 + 2*p12 + p20 + 2*p21 + p22); out = sum >> 4 (12-bit unsigned floor).
  * mode 2: Sharpen: sum = 5*p11 - p01 - p10 - p12 - p21 (12-bit signed); out = (sum < 0) ? 0 : (sum > 255) ? 255 : sum[7:0].
  * mode 3: out = 8'd0."""

    prompt=f'''You are the actual RTL design agent for ChipForge. run_id={args.run_id}, design_id={design_id}.
The top module name must be {top}.
The frozen spec and protocol rules are provided below. Verification is an external tool invoked exclusively via chip_validate_rtl. Do not explore or grep the workspace for testbenches (there are none).
Keep your reasoning direct and concise to avoid hitting output token limits: design the complete Verilog module, call chip_submit_rtl immediately, and then call chip_validate_rtl.
Implement the complete frozen protocol and integer arithmetic exactly as specified:
1. Ports:
   - ui_in[7:0]: input pixel
   - uio_in[0]: in_valid
   - uio_in[1]: start_window
   - uio_in[3:2]: mode (latched on first accepted sample if image_multi; ignored for Sobel-only)
   - uio_out[4]: in_ready (1 in IDLE and during collection; 0 during compute and when reset/ena is low)
   - uio_out[5]: out_valid (1-cycle pulse at exactly latency L={L} after 9th accepted sample; 0 otherwise)
   - uio_out[6]: busy (0 in IDLE waiting for first start; 1 during partial collection and computation)
   - uio_out[7], uio_out[3:0]: constant 0
   - uo_out[7:0]: output pixel when out_valid=1; must be 8'h00 when out_valid=0
   - uio_oe: constant 8'hF0 (240)
   - clk, rst_n, ena: synchronous active-low reset; ena=0 also synchronously aborts to IDLE. Use single-edge "always @(posedge clk)" ONLY.
2. Handshake and State:
   - In IDLE: only accept a sample if in_valid && in_ready && start_window. If in_valid is high but start_window is 0, DO NOT accept or start a window; stay in IDLE with busy=0 and out_valid=0.
   - During collection (first sample accepted to 8th accepted): if in_valid && in_ready && start_window, discard the partial window and treat this new sample as p00 of a new window.
   - Collect exactly 9 samples: p00, p01, p02, p10, p11, p12, p20, p21, p22 in row-major order. Valid gaps allowed.
   - Upon accepting the 9th sample, set in_ready=0. The testbench samples signals after the clock rising edge.
{timing_rules}
   - While computing, in_ready=0 and busy=1.
3. If validation returns errors, read the specific failure from the validator log and submit a revised candidate with parent_candidate_id.
Only after RTL_PASS enqueue chip_harden, read its receipt with chip_get_job, and preserve candidate/result references.
Do not alter the contract, oracle, constraints or evaluator. Do not claim gate-level or physical signoff from flow completion.
Work in this session yourself; do not spawn subagents, do not use shell or file tools. The candidate budget is finite: at most {allocation} chip_submit_rtl submissions for this design.
Keep working until you have a candidate with status RTL_PASS and a harden receipt, or until your allocation is exhausted; then report the candidate IDs, their tool results and the exact remaining problem.
Request: {run['request']}
Frozen spec: {json.dumps(spec,ensure_ascii=False)}'''
attempt_dir=(ROOT/'reports' if args.smoke else path/'agh')/(('agh-model-smoke-' if args.smoke else 'attempt-')+time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid()))
attempt_dir.mkdir(parents=True)
# Register the outer-layer toolchain version before this batch of design attempts.
toolchain={name:__import__('hashlib').sha256((ROOT/name).read_bytes()).hexdigest() for name in
           ['app/cli.py','plugins/chipforge-tools/index.mjs','scripts/run_agh.py','scripts/harden_worker.py']}
batch={'recorded_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'smoke':args.smoke,
       'run_id':None if args.smoke else args.run_id,'toolchain_sha256':toolchain,
       'model_route':model,'slots':slots,'profile':selection['profile'],
       'ledger_before':read(ROOT/'.ledger.json') if (ROOT/'.ledger.json').exists() else None,
       'candidate_allocation':None if args.smoke else allocation,'prompt':prompt}
write(attempt_dir/'batch.json',batch)
if not args.smoke: event(args.run_id,'batch_registered',attempt=str(attempt_dir),toolchain_sha256=toolchain,allocation=allocation)
command=[str(node),str(entry),'-p','--mode','json','--cwd',str(path)]
if args.smoke:
    command[command.index('--cwd')+1]=str(attempt_dir)
# The account is the only enabled/default account: new sessions resolve all five
# text slots to its selected model. Repeated --model flags are NOT supported by
# this pinned CLI; use the default configuration, and verify the native bindings.
started=time.time()
with (attempt_dir/'events.jsonl').open('w') as out,(attempt_dir/'stderr.log').open('w') as err:
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=out,stderr=err,cwd=ROOT,env=env,start_new_session=True,text=True)
    try:
        proc.communicate(prompt,timeout=args.timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGTERM)
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL)
            proc.wait()
        write(attempt_dir/'invocation.json',{'command':command,'model':model,'state':'TIMED_OUT_REQUIRES_SESSION_CHECK',
                                          'elapsed_seconds':time.time()-started,'note':'Check actual AGH turn and queued jobs before recovery; timeout is not success'})
        if not args.smoke: event(args.run_id,'agh_timeout',attempt=str(attempt_dir),elapsed_seconds=time.time()-started)
        raise SystemExit(124)
invocation={'command':command,'model':model,'slots':slots,'elapsed_seconds':time.time()-started,
            'exit_code':proc.returncode,'smoke':args.smoke}
summaries=[]
for line in (attempt_dir/'events.jsonl').read_text().splitlines():
    try: value=json.loads(line)
    except ValueError: continue
    if isinstance(value,dict) and isinstance(value.get('sessionId'),str): summaries.append(value)
if summaries:
    result=summaries[-1]
    session_id=result['sessionId']
    invocation.update(agh_session_id=session_id,turn_reason=result.get('reason'),final_text=result.get('text'))
    export=[str(node),str(entry),'export',session_id,'--format','agnes','--out',str(attempt_dir/'native.jsonl')]
    with (attempt_dir/'export.log').open('w') as log:
        exported=subprocess.run(export,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=60)
    invocation.update(native_export=str(attempt_dir/'native.jsonl'),native_export_exit=exported.returncode)
    if exported.returncode == 0:
        rows=[json.loads(line) for line in (attempt_dir/'native.jsonl').read_text().splitlines() if line.strip()]
        start=next(row for row in rows if row['type']=='session/start')
        bindings={item['slot']:item for item in start['data'].get('modelSettings',[])}
        matched=all(bindings.get(slot,{}).get('route')==selection['route'] and
                    bindings.get(slot,{}).get('model')==selection['model'] for slot in slots)
        invocation.update(model_bindings=bindings,model_bindings_match=matched)
        if not matched:
            invocation['state']='MODEL_BINDING_MISMATCH_REQUIRES_REVIEW'
            proc.returncode=1
    if not args.smoke:
        run['agh_session_id']=session_id
        write(path/'run.json',run)
write(attempt_dir/'invocation.json',invocation)
if not args.smoke: event(args.run_id,'agh_cli_finished',attempt=str(attempt_dir),exit_code=proc.returncode)
print(attempt_dir)
raise SystemExit(proc.returncode)
