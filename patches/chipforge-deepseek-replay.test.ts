import { afterEach, expect, it } from 'vitest'
import { PiAdapter } from '../src/index.js'
import { fakeModel, fakeRequest } from '../testkit/index.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

it.each(['deepseek', undefined])('replays original reasoning and tool IDs for provider identity %s', async (providerId) => {
  const route = 'account-chipforge-deepseek-flash'
  let sent: Record<string, any> | undefined
  globalThis.fetch = async (input, init) => {
    const request = new Request(input, init)
    sent = JSON.parse(await request.text())
    return new Response('data: {"id":"test","object":"chat.completion.chunk","model":"deepseek-flash","choices":[{"index":0,"delta":{"content":"160"},"finish_reason":null}]}\n\ndata: {"id":"test","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n', { headers: { 'content-type': 'text/event-stream' } })
  }
  const adapter = new PiAdapter({ providerId, maxRetries: 0, manualRoutes: [{
    route, api: 'openai-completions', baseUrl: 'https://gateway.invalid/v1', credentialRef: 'secret://deepseek/account-test-r1',
    models: [fakeModel({ id: 'deepseek-flash', route, api: 'openai-completions',
      baseUrl: 'https://gateway.invalid/v1', reasoning: true,
      thinkingLevelMap: { max: 'max' }, compat: { thinkingFormat: 'deepseek' } })],
  }] })
  adapter.bindCredential(route, 'test-only-not-a-real-key')
  const request = fakeRequest({ route, model: 'deepseek-flash', sampling: { thinking: 'max' },
    messages: [
      { role: 'user', content: [{ type: 'text', text: 'Read x' }] },
      { role: 'assistant', content: [{ type: 'thinking', text: 'Read x using the provided tool.' }],
        toolCalls: [{ toolUseId: 'call_original', name: 'read_x', args: {}, ordinal: 0 }] },
      { role: 'tool_result', toolUseId: 'call_original', content: [{ type: 'text', text: '{"x":160}' }], isError: false },
    ], tools: [{ name: 'read_x', description: 'read', parameters: { type: 'object', properties: {} } }],
  })
  const events = []
  for await (const event of adapter.stream(route, request, {
    signal: new AbortController().signal, toolNames: ['read_x'], sessionKey: 'test',
    timeoutMs: { firstToken: 2000, total: 5000 },
  })) events.push(event)
  expect(events.some(event => event.type === 'error')).toBe(false)
  expect(sent?.model).toBe('deepseek-flash')
  expect(sent?.tools[0].function.parameters.required).toEqual([])
  expect(request.tools[0].parameters).not.toHaveProperty('required')
  const assistant = sent?.messages.find((message: any) => message.role === 'assistant')
  expect(assistant.reasoning_content).toBe('Read x using the provided tool.')
  expect(assistant.tool_calls[0].id).toBe('call_original')
  expect(sent?.messages.find((message: any) => message.role === 'tool').tool_call_id).toBe('call_original')
})
