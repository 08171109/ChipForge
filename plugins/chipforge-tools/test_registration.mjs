import assert from 'node:assert/strict'
import { chipforgeTools } from './index.mjs'
process.env.CHIPFORGE_ROOT ||= '/tmp/chipforge-registration-only'
const definitions = [], hooks = []
chipforgeTools.apply({ extension: () => ({ registerTool: x => definitions.push(x), registerHook: (...x) => hooks.push(x) }) })
assert.equal(definitions.length, 6)
assert.equal(new Set(definitions.map(x => x.name)).size, 6)
for (const x of definitions) {
  assert.equal(x.parameters[Symbol.for('TypeBox.Kind')], 'Object')
  assert.equal(x.parameters.additionalProperties, false)
  assert.equal(typeof x.execute, 'function')
}
assert.equal(hooks[0][0], 'context')
assert.match(hooks[0][1]().sections[0].content, /frozen contract/)
assert.equal(definitions.find(x => x.name === 'chip_submit_rtl').meta.replay, 'never')
assert.equal(definitions.find(x => x.name === 'chip_harden').meta.isReadOnly, false)
console.log('PLUGIN_REGISTRATION_CHECK_PASS: this is not live AGH activation or a model call')

