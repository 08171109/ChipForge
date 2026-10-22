// Official configuration SDK. Secret input is accepted only on stdin, never logged.
import { readFile, writeFile } from 'node:fs/promises'
import { createClient, memoryJournal } from '../runtime/sdk-bundle.mjs'
const root = process.env.CHIPFORGE_ROOT
const home = process.env.AGH_HOME
if (!root || !home) throw new Error('Source scripts/env.sh first')
const owner = JSON.parse(await readFile(`${home}/data/daemon/owner.json`, 'utf8'))
const client = createClient({ transport: { kind: 'unix', path: owner.socketPath }, auth: { kind: 'local' }, journal: memoryJournal() })
await client.initialize()
const action = process.argv[2]
let input = {}
let secret = ''
const safeSnapshot = value => ({
  profile: value.profile, revision: value.revision, configured: value.configured,
  effect: value.effect, defaultAccountId: value.defaultAccountId,
  provider: value.provider ? { id: value.provider.id, route: value.provider.route, model: value.provider.model, credentialConfigured: value.provider.credentialConfigured } : null,
  accounts: value.accounts?.map(a => ({ accountId: a.accountId, providerId: a.providerId, route: a.route, model: a.model, enabled: a.enabled, credentialConfigured: a.credentialConfigured })),
})
try {
  if (action === 'inspect') {
    const providers = await client.config.providers()
    console.log(JSON.stringify({ providers: providers.providers.map(p => ({ id: p.id, label: p.label, api: p.api })), snapshot: safeSnapshot(await client.config.get()) }, null, 2))
  } else if (action === 'configure') {
    let raw = ''
    for await (const chunk of process.stdin) raw += chunk
    input = JSON.parse(raw)
    raw = ''
    secret = input.apiKey
    if (input.model !== 'deepseek-flash' || !secret || !input.baseUrl) throw new Error('Expected the existing deepseek-flash route and credential')
    const before = await client.config.get()
    if (before.accounts?.some(a => a.accountId !== 'chipforge-deepseek-flash')) throw new Error('Unexpected existing account; do not overwrite it')
    const existing = before.accounts?.find(a => a.accountId === 'chipforge-deepseek-flash')
    const request = { providerId: 'deepseek', accountId: 'chipforge-deepseek-flash', baseUrl: input.baseUrl, apiKey: secret }
    const tested = await client.config.test(request)
    const selected = tested.models.find(m => m.id === input.model)
    if (!tested.verified || !selected) throw new Error('Existing gateway did not verify the requested model ID')
    const saved = await client.config.save({ ...request, model: input.model, label: 'ChipForge DeepSeek Flash', enabled: true, makeDefault: true, expectedRevision: before.revision })
    if (!saved.configured || saved.provider?.model !== input.model) throw new Error('Configuration did not activate')
    const evidence = { before: safeSnapshot(before), after: safeSnapshot(saved), selectedCatalogModel: selected, connectionTest: 'VERIFIED_CATALOG_AND_CREDENTIALS', inference: 'NOT_YET_TESTED', credentialSource: input.credentialSource, routeSource: input.routeSource }
    await writeFile(`${root}/reports/agh-model-configuration.json`, JSON.stringify(evidence, null, 2)+'\n')
    const selection = { route: saved.provider.route, model: input.model, profile: saved.profile, accountId: saved.defaultAccountId, slots: ['primary','escalation','fast','compaction','verifier'], configurationRevision: saved.revision, scope: 'text-only ChipForge; image/video not used' }
    await writeFile(`${root}/model.selection.json`, JSON.stringify(selection, null, 2)+'\n')
    console.log(JSON.stringify({ configured: saved.configured, effect: saved.effect, route: selection.route, model: selection.model, revision: saved.revision }))
  } else if (action === 'status') {
    console.log(JSON.stringify(safeSnapshot(await client.config.get()), null, 2))
  } else throw new Error('Usage: inspect|configure|status')
} catch (error) {
  let message = error instanceof Error ? error.message : String(error)
  if (secret) message = message.split(secret).join('[redacted]')
  console.error(message)
  process.exitCode = 1
} finally {
  input = {}; secret = ''; await client.close()
}
