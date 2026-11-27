// Runs under the node test runner: task test:mods.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  DEFAULTS,
  decide,
  freshState,
  isHandoffUrl,
  isVersionAtLeast,
  levelFor,
  readConfig,
  restorePrompt,
  silentReason,
  type State,
} from '../hooks/logic.ts'

const URL = 'https://github.com/example/repo/pull/12#issuecomment-99'
const state = (over: Partial<State> = {}): State => ({ ...freshState(), ...over })

test('levels follow the thresholds', () => {
  assert.equal(levelFor(undefined, DEFAULTS), 0)
  assert.equal(levelFor(59.9, DEFAULTS), 0)
  assert.equal(levelFor(60, DEFAULTS), 1)
  assert.equal(levelFor(70, DEFAULTS), 2)
  assert.equal(levelFor(80, DEFAULTS), 3)
  assert.equal(levelFor(100, DEFAULTS), 3)
})

test('configured thresholds replace the defaults', () => {
  const config = readConfig({ nudgePercent: 40, wrapUpPercent: 50, forcePercent: 60, maxRotations: 2 })
  assert.deepEqual(config, { nudge: 40, wrapUp: 50, force: 60, maxRotations: 2 })
})

test('unordered or invalid thresholds fall back to the defaults', () => {
  assert.deepEqual(readConfig({ nudgePercent: 90, wrapUpPercent: 50, forcePercent: 60 }), DEFAULTS)
  assert.deepEqual(readConfig({ forcePercent: 120 }), DEFAULTS)
  assert.deepEqual(readConfig({ nudgePercent: 'x' }), DEFAULTS)
  assert.equal(readConfig({ maxRotations: -1 }).maxRotations, DEFAULTS.maxRotations)
})

test('each level fires once until the state is reset', () => {
  assert.deepEqual(decide(state(), 65, DEFAULTS), { kind: 'nudge' })
  assert.deepEqual(decide(state({ reached: 1 }), 65, DEFAULTS), { kind: 'none' })
  assert.deepEqual(decide(state({ reached: 1 }), 75, DEFAULTS), { kind: 'wrapup' })
  assert.deepEqual(decide(state({ reached: 2 }), 85, DEFAULTS), { kind: 'force' })
  assert.deepEqual(decide(state({ reached: 3 }), 99, DEFAULTS), { kind: 'none' })
  assert.deepEqual(decide(state(), 10, DEFAULTS), { kind: 'none' })
})

test('a rotation needs a handoff url', () => {
  assert.deepEqual(decide(state(), 95, DEFAULTS), { kind: 'force' })
  assert.deepEqual(decide(state({ handoffUrl: 'nope' }), 95, DEFAULTS), { kind: 'none' })
  assert.deepEqual(decide(state({ handoffUrl: URL }), 5, DEFAULTS), { kind: 'rotate', url: URL })
})

test('the cap stops a rotation', () => {
  const full = state({ handoffUrl: URL, rotations: DEFAULTS.maxRotations })
  assert.deepEqual(decide(full, 90, DEFAULTS), { kind: 'capped' })
  assert.deepEqual(decide(state({ handoffUrl: URL, rotations: 4 }), 90, DEFAULTS), {
    kind: 'rotate',
    url: URL,
  })
  assert.deepEqual(decide(state({ handoffUrl: URL }), 90, { ...DEFAULTS, maxRotations: 0 }), {
    kind: 'capped',
  })
})

test('a disabled mod does nothing', () => {
  assert.deepEqual(decide(state({ disabled: true, handoffUrl: URL }), 99, DEFAULTS), { kind: 'none' })
})

test('only a comment url counts as a handoff', () => {
  assert.equal(isHandoffUrl(URL), true)
  assert.equal(isHandoffUrl('https://git.example.org/o/r/issues/3#issuecomment-1'), true)
  assert.equal(isHandoffUrl('https://github.com/example/repo/pull/12#pullrequestreview-4'), true)
  assert.equal(isHandoffUrl('https://github.com/example/repo/issues/12'), false)
  assert.equal(isHandoffUrl('http://github.com/example/repo/issues/1#issuecomment-1'), false)
  assert.equal(isHandoffUrl('done'), false)
  assert.equal(isHandoffUrl(undefined), false)
})

test('the version check compares numerically', () => {
  assert.equal(isVersionAtLeast('2.1.293'), true)
  assert.equal(isVersionAtLeast('2.1.311'), true)
  assert.equal(isVersionAtLeast('2.2.0'), true)
  assert.equal(isVersionAtLeast('3.0.0'), true)
  assert.equal(isVersionAtLeast('2.1.292'), false)
  assert.equal(isVersionAtLeast('2.0.999'), false)
  assert.equal(isVersionAtLeast('2.1.9'), false)
  assert.equal(isVersionAtLeast(undefined), false)
  assert.equal(isVersionAtLeast('dev'), false)
})

test('the mod is silent in CI, in a subagent and on an old engine', () => {
  const version = '2.1.311'
  assert.equal(silentReason({ version }), undefined)
  assert.equal(silentReason({ ci: 'true', version }), 'ci')
  assert.equal(silentReason({ ci: '1', version }), 'ci')
  assert.equal(silentReason({ ci: 'false', version }), undefined)
  assert.equal(silentReason({ ci: '', version }), undefined)
  assert.equal(silentReason({ agentId: 'a1', version }), 'subagent')
  assert.equal(silentReason({ version: '2.1.100' }), 'version')
  assert.equal(silentReason({}), 'version')
})

test('the restore prompt points to the comment, not the conversation', () => {
  const text = restorePrompt(URL)
  assert.ok(text.includes(URL))
  assert.ok(text.includes('Do not rely on'))
})
