import { expect, mock, test } from 'claude-code/testing'

const URL = 'https://github.com/example/repo/issues/7#issuecomment-123'
const TOOL = 'mcp__self-clear__request_rotation'
const SESSION = { cwd: '/', surface: 'terminal', isInteractive: true } as const

type World = {
  percent: number
  version: string
  calls: string[]
  clearFails: boolean
  usageFails: boolean
}

// Every call the mod makes on the engine ends here, in the order it was made.
const world = (on: any, overrides: Partial<World> = {}, env: Record<string, string> = {}) => {
  const w: World = { percent: 10, version: '2.1.311', calls: [], clearFails: false, usageFails: false, ...overrides }
  const clock = mock.clock(on)
  mock.env(on, env)
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.version', () => ({ value: { version: w.version, base: w.version } }))
  on('session.usage', () => {
    if (w.usageFails) throw new Error('boom')
    return { value: { startedAt: 0, context: { window: 200000, percent: w.percent }, rateLimits: [] } }
  })
  on('tool.register', (_: unknown, e: any) => {
    w.calls.push(`register:${e.name}`)
    return { value: { tool: `mcp__self-clear__${e.name}` } }
  })
  on('ui.toast', (_: unknown, e: any) => {
    w.calls.push(`toast:${e.text}`)
    return { value: undefined }
  })
  on('prompt.submit', (_: unknown, e: any) => {
    w.calls.push(`submit:${e.text}`)
    return { text: e.text }
  })
  // Left unanswered, the call rejects as an engine without the command would.
  if (!w.clearFails) {
    on('command.run', (_: unknown, e: any) => {
      w.calls.push(`command:${e.command}`)
      return { text: '' }
    })
  }
  on('session.compact', () => {
    w.calls.push('compact')
    return { skip: 'test' }
  })
  on('turn.complete', () => ({ text: '' }))
  return { w, clock }
}

const endTurn = async ($: any, clock: any, agentId?: string) => {
  await $.turn.complete({ answer: 'ok', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer', agentId })
  await clock.advance(2000)
}

const request = ($: any, handoff_url: unknown, agentId?: string) =>
  $.tool.call({ tool: TOOL, handoff_url, agentId })

test('rotates after the turn once the handoff url is given', async ($, on) => {
  const { w, clock } = world(on)
  await $.session.start(SESSION)
  const answer = await request($, URL)
  expect(answer.deny).toBeUndefined()
  await endTurn($, clock)
  expect(w.calls.filter(c => !c.startsWith('register'))).toEqual([
    'command:clear',
    expect.stringContaining(`submit:The context was rotated`),
  ])
  expect(w.calls.some(c => c.includes(URL))).toBe(true)
})

test('refuses a rotation request without a handoff url', async ($, on) => {
  const { w, clock } = world(on)
  await $.session.start(SESSION)
  for (const bad of [undefined, '', 'not a url', 'https://github.com/example/repo']) {
    const answer = await request($, bad)
    expect(answer.deny).toContain('handoff')
  }
  await endTurn($, clock)
  expect(w.calls.some(c => c.startsWith('command:'))).toBe(false)
})

test('falls back to compact when clear fails', async ($, on) => {
  const { w, clock } = world(on, { clearFails: true })
  await $.session.start(SESSION)
  await request($, URL)
  await endTurn($, clock)
  expect(w.calls).toContain('compact')
  expect(w.calls.some(c => c.startsWith('submit:') && c.includes(URL))).toBe(true)
})

test('stops rotating at the cap', async ($, on) => {
  const { w, clock } = world(on)
  await $.session.start(SESSION)
  for (let i = 0; i < 5; i++) {
    await request($, URL)
    await endTurn($, clock)
  }
  expect(w.calls.filter(c => c === 'command:clear')).toHaveLength(5)
  const sixth = await request($, URL)
  expect(sixth.deny).toContain('cap')
  await endTurn($, clock)
  expect(w.calls.filter(c => c === 'command:clear')).toHaveLength(5)
})

test('asks for a wrap up once per level', async ($, on) => {
  const { w, clock } = world(on, { percent: 72 })
  await $.session.start(SESSION)
  await endTurn($, clock)
  await endTurn($, clock)
  const submits = w.calls.filter(c => c.startsWith('submit:'))
  expect(submits).toHaveLength(1)
  expect(submits[0]).toContain('handoff skill')
  w.percent = 85
  await endTurn($, clock)
  expect(w.calls.filter(c => c.startsWith('submit:'))).toHaveLength(2)
})

test('nudges the owner below the wrap up level', async ($, on) => {
  const { w, clock } = world(on, { percent: 62 })
  await $.session.start(SESSION)
  await endTurn($, clock)
  expect(w.calls.some(c => c.startsWith('toast:Context at 62'))).toBe(true)
  expect(w.calls.some(c => c.startsWith('submit:'))).toBe(false)
})

test('stays silent in CI', async ($, on) => {
  const { w, clock } = world(on, { percent: 90 }, { CI: 'true' })
  await $.session.start(SESSION)
  await endTurn($, clock)
  expect(w.calls).toEqual([])
  const answer = await request($, URL)
  expect(answer.deny).toBeDefined()
})

test('stays silent in a subagent', async ($, on) => {
  const { w, clock } = world(on, { percent: 90 })
  await $.session.start(SESSION)
  w.calls.length = 0
  await endTurn($, clock, 'agent-1')
  expect(w.calls).toEqual([])
  const answer = await request($, URL, 'agent-1')
  expect(answer.deny).toBeDefined()
})

test('stays silent on an engine that is too old', async ($, on) => {
  const { w, clock } = world(on, { percent: 90, version: '2.1.200' })
  await $.session.start(SESSION)
  await endTurn($, clock)
  expect(w.calls).toEqual([])
})

test('an error disables the mod and says so once', async ($, on) => {
  const { w, clock } = world(on, { percent: 90, usageFails: true })
  await $.session.start(SESSION)
  await endTurn($, clock)
  await endTurn($, clock)
  expect(w.calls.filter(c => c.startsWith('toast:self-clear: disabled'))).toHaveLength(1)
  expect(w.calls.some(c => c.startsWith('submit:'))).toBe(false)
})
