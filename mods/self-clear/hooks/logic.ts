// Pure decision logic of the self-clear mod. No engine call lives here, so the
// node test runner covers it. Erasable TypeScript syntax only.

export const MIN_VERSION = '2.1.293'

export type Config = {
  nudge: number
  wrapUp: number
  force: number
  maxRotations: number
}

export const DEFAULTS: Config = { nudge: 60, wrapUp: 70, force: 80, maxRotations: 5 }

// 0 none, 1 nudge, 2 wrap up, 3 force.
export type Level = 0 | 1 | 2 | 3

export type State = {
  rotations: number
  reached: Level
  handoffUrl?: string
  disabled: boolean
}

export type Action =
  | { kind: 'none' }
  | { kind: 'nudge' | 'wrapup' | 'force' }
  | { kind: 'rotate'; url: string }
  | { kind: 'capped' }

export const freshState = (): State => ({ rotations: 0, reached: 0, disabled: false })

const toNumber = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined

// An invalid or unordered set of thresholds falls back to the defaults as a whole.
export const readConfig = (options: Readonly<Record<string, unknown>>): Config => {
  const nudge = toNumber(options.nudgePercent) ?? DEFAULTS.nudge
  const wrapUp = toNumber(options.wrapUpPercent) ?? DEFAULTS.wrapUp
  const force = toNumber(options.forcePercent) ?? DEFAULTS.force
  const max = toNumber(options.maxRotations) ?? DEFAULTS.maxRotations
  const isOrdered = nudge > 0 && nudge < wrapUp && wrapUp < force && force <= 100
  const maxRotations = Number.isInteger(max) && max >= 0 ? max : DEFAULTS.maxRotations
  return isOrdered
    ? { nudge, wrapUp, force, maxRotations }
    : { ...DEFAULTS, maxRotations }
}

export const levelFor = (percent: number | undefined, config: Config): Level => {
  if (percent === undefined || !Number.isFinite(percent)) return 0
  if (percent >= config.force) return 3
  if (percent >= config.wrapUp) return 2
  if (percent >= config.nudge) return 1
  return 0
}

// A comment of an issue, a pull request or a review, as any tracker host spells it.
const HANDOFF_URL = /^https:\/\/[^\s/]+\/[^\s/]+\/[^\s/]+\/(issues|pull)\/\d+#(issuecomment|pullrequestreview)-\d+$/

export const isHandoffUrl = (value: unknown): value is string =>
  typeof value === 'string' && HANDOFF_URL.test(value)

const parts = (version: string): number[] | undefined => {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(version)
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : undefined
}

// An unreadable version counts as too old: the mod stays silent.
export const isVersionAtLeast = (version: string | undefined, min: string = MIN_VERSION): boolean => {
  const have = version === undefined ? undefined : parts(version)
  const need = parts(min)
  if (have === undefined || need === undefined) return false
  for (let i = 0; i < 3; i++) {
    if (have[i] !== need[i]) return have[i] > need[i]
  }
  return true
}

export type Silence = { ci?: string; agentId?: string; version?: string }

// The reason the mod stays silent, or undefined when it acts.
export const silentReason = (input: Silence): string | undefined => {
  if (input.ci !== undefined && input.ci !== '' && input.ci !== 'false' && input.ci !== '0') return 'ci'
  if (input.agentId !== undefined) return 'subagent'
  if (!isVersionAtLeast(input.version)) return 'version'
  return undefined
}

export const decide = (state: State, percent: number | undefined, config: Config): Action => {
  if (state.disabled) return { kind: 'none' }
  // The handoff comes first: no URL, no rotation.
  if (state.handoffUrl !== undefined) {
    if (!isHandoffUrl(state.handoffUrl)) return { kind: 'none' }
    if (state.rotations >= config.maxRotations) return { kind: 'capped' }
    return { kind: 'rotate', url: state.handoffUrl }
  }
  const level = levelFor(percent, config)
  if (level <= state.reached) return { kind: 'none' }
  return { kind: level === 3 ? 'force' : level === 2 ? 'wrapup' : 'nudge' }
}

export const restorePrompt = (url: string): string =>
  [
    'The context was rotated at a work package boundary.',
    `Read the handoff comment first: ${url}`,
    'It holds the state, the open items and the next steps. Continue from it.',
    'The earlier conversation is gone. Do not rely on it.',
  ].join('\n')

export const wrapUpPrompt = (level: 'wrapup' | 'force', percent: number): string =>
  level === 'force'
    ? `The context is at ${percent} percent. Stop starting new work. Finish or park the current step, write the handoff with the handoff skill, then call the request_rotation tool with the comment URL.`
    : `The context is at ${percent} percent. Finish the current step, then write the handoff with the handoff skill and call the request_rotation tool with the comment URL.`

export const compactInstructions = (url: string): string =>
  `Keep only what the handoff comment at ${url} does not hold. Point to that comment for the state.`
