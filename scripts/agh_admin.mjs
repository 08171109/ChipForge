// Bundle against this project's pinned AGH public SDK; no model or account calls.
import { readFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import { createClient, memoryJournal } from '../runtime/sdk-bundle.mjs'
const home = process.env.AGH_HOME || new URL('../runtime/agh-home/', import.meta.url).pathname
const profile = process.env.AGNES_PROFILE || 'local-dev'
const owner = JSON.parse(await readFile(`${home}/data/daemon/owner.json`, 'utf8'))
const client = createClient({ transport: { kind: 'unix', path: owner.socketPath }, auth: { kind: 'local' }, journal: memoryJournal() })
await client.initialize()
const id = '@chipforge/agh-tools'
const common = async () => ({ profile, clientId: await client.clientId(), commandId: `chipforge-${randomUUID()}` })
async function settle(receipt) {
  for (let n = 0; n < 180; n++) {
    const op = await client.packages.operation.get({ profile, operationId: receipt.operationId })
    if (['completed', 'rolled-back'].includes(op.state)) return op
    if (['failed', 'cancelled'].includes(op.state)) throw new Error(JSON.stringify(op.error || op))
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error('Operation still running: inspect receipt before recovery')
}
try {
  if (process.argv[2] === 'activate') {
    const inspected = await settle(await client.packages.inspect({ ...await common(), source: { type: 'file', ref: 'file:./plugins/chipforge-tools' } }))
    const preview = inspected.preview
    if (!preview || preview.id !== id || preview.blockers.length) throw new Error('Unexpected or blocked plugin preview')
    const installed = (await client.packages.list({ profile })).packages.find(p => p.id === id)
    if (!installed) throw new Error('Install the reviewed local plugin first')
    await settle(await client.packages.trust({ ...await common(), id, expectedIntegrity: preview.integrity, capabilityHash: preview.capabilityHash }))
    await settle(await client.packages.enable({ ...await common(), id }))
  } else if (process.argv[2] !== 'status') {
    throw new Error('Usage: agh_admin.mjs status|activate')
  }
  const installed = (await client.packages.list({ profile })).packages.find(p => p.id === id)
  console.log(JSON.stringify({ plugin: installed, evidence: 'real AGH package administration; not model invocation' }, null, 2))
} finally { await client.close() }

