import { expect, it } from 'vitest'
import { ToolRegistry } from '../src/registry/tools.js'
import { presetDefaults } from '../src/step/preset.js'
import { fakeProvider, textTurn, toolTurn } from './helpers/fake-provider.js'
import { actor, openSession, readTool } from './helpers/open-session.js'

it.each(['account-chipforge-deepseek-flash', 'default'])('keeps the scoped gateway tool/result ID round trip on %s', async route => {
  const first = toolTurn('read', {})
  const call = first.find(event => event.type === 'toolcall_end')
  if (!call || call.type !== 'toolcall_end') throw new Error('fixture missing call')
  call.call.toolUseId = 'call_upstream_original'
  const provider = fakeProvider([first, textTurn('done')])
  const registry = new ToolRegistry()
  registry.add(readTool(), { source: 'agnes/tools-core', trust: 'builtin' })
  const preset = presetDefaults()
  preset.model.route.primary = route
  preset.model.id.primary = 'deepseek-flash'
  const { session } = await openSession({ provider, registry, preset })
  await session.enqueue('next-turn', { content: [{ type: 'text', text: 'Read x.' }], actor })
  await session.acceptInput()
  const outcome = await session.run({ until: 'turn-end', signal: new AbortController().signal })
  expect(outcome.reason).toBe('completed')
  const continuation = provider.requests[1]
  const assistant = continuation?.messages.find(message => message.role === 'assistant')
  const result = continuation?.messages.find(message => message.role === 'tool_result')
  if (assistant?.role !== 'assistant' || result?.role !== 'tool_result') throw new Error('missing actual continuation')
  const id = assistant.toolCalls?.[0]?.toolUseId
  expect(id).toBe(result.toolUseId)
  if (route === 'account-chipforge-deepseek-flash') expect(id).toBe('call_upstream_original')
  else expect(id).not.toBe('call_upstream_original')
})
