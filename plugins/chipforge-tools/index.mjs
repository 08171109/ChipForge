import { spawn } from 'node:child_process'
import { isAbsolute, join } from 'node:path'

const Kind = Symbol.for('TypeBox.Kind')
const string = (extra = {}) => ({ [Kind]: 'String', type: 'string', minLength: 1, ...extra })
const identifier = () => string({ pattern: '^[a-z0-9_-]{1,80}$', maxLength: 80 })
const object = (properties, required = Object.keys(properties)) => ({
  [Kind]: 'Object', type: 'object', properties, required, additionalProperties: false,
})
const pair = () => ({ run_id: identifier(), candidate_id: identifier() })

function bridge(root, action, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(join(root, '.venv/bin/python'), [join(root, 'app/cli.py'), action], {
      cwd: root, env: { ...process.env, CHIPFORGE_ROOT: root }, stdio: ['pipe', 'pipe', 'pipe'],
    })
    let stdout = '', stderr = ''
    child.stdout.on('data', data => { stdout += data; if (stdout.length > 2_000_000) child.kill('SIGTERM') })
    child.stderr.on('data', data => { if (stderr.length < 8192) stderr += data })
    child.on('error', reject)
    child.on('close', code => {
      try { resolve({ ...JSON.parse(stdout), bridge_exit_code: code }) }
      catch { reject(new Error(`ChipForge bridge returned no valid JSON (exit ${code}); ${stderr.slice(0, 500)}`)) }
    })
    child.stdin.end(JSON.stringify(args))
  })
}

export const chipforgeTools = {
  inject: ['extension'],
  apply(ctx) {
    const root = process.env.CHIPFORGE_ROOT
    if (!root || !isAbsolute(root)) throw new Error('Set absolute CHIPFORGE_ROOT before starting this AGH daemon')
    const agnes = ctx.extension()
    const tools = [
      ['chip_get_spec', 'get_spec', object({ design_id: identifier() }), true,
        'Read the frozen image-chip arithmetic, pins and cycle contract.'],
      ['chip_submit_rtl', 'submit_rtl', object({ run_id: identifier(), source: string({ maxLength: 65536 }), parent_candidate_id: identifier() }, ['run_id', 'source']), false,
        'Submit new Verilog source as an immutable candidate. Each revision consumes the finite project budget.'],
      ['chip_validate_rtl', 'validate', object(pair()), false,
        'Run real compiler, independent arithmetic/protocol tests and images. May take minutes; returns logs and counterexamples.'],
      ['chip_harden', 'harden', object(pair()), false,
        'Enqueue one physical implementation only after RTL_PASS. Returns a job receipt. Flow completion still requires final review.'],
      ['chip_get_job', 'job_status', object(pair()), true,
        'Read physical job state and raw artifact references. Do not infer signoff from a GDS file alone.'],
      ['chip_get_run', 'status', object({ run_id: identifier() }), true,
        'Read immutable candidates, tool results and cumulative project budget.'],
    ]
    for (const [name, action, parameters, readOnly, description] of tools) {
      agnes.registerTool({ name, description, parameters,
        meta: { isReadOnly: readOnly, isDestructive: false, isConcurrencySafe: false,
          isOpenWorld: false, replay: readOnly ? 'safe' : (action === 'harden' || action === 'validate' ? 'idempotent' : 'never'),
          costHint: undefined, deferLoading: false, requiresApproval: 'never' },
        async execute(args) {
          const structured = await bridge(root, action, args)
          return { content: [{ type: 'text', text: JSON.stringify(structured) }], structured }
        },
      })
    }
    agnes.registerHook('context', () => ({ sections: [{
      id: 'chipforge/contract', order: 250,
      content: 'ChipForge: design and revise RTL through chip_* tools. The outer owner supplies run_id. Keep the frozen contract, tests, clock and PDK unchanged. Submit a new candidate for every edit. First inspect real verification feedback; then repair or improve the circuit. Use at most the available candidate/physical budget. Never declare final signoff from prose or placement alone. Bind your actual tool records to the returned candidate IDs. This workflow improves circuits, not the AGH harness.',
    }] }))
  },
}

