// The orchestrator clears its own context at a work package boundary.
//
// The model asks for it through the request_rotation tool, which carries the URL
// of the written handoff comment and only sets a flag. The clear runs after the
// turn ends. Every error disables the mod for the session and says so once.
import type { Register } from 'claude-code'
import {
  type Config,
  type State,
  compactInstructions,
  decide,
  freshState,
  isHandoffUrl,
  readConfig,
  restorePrompt,
  silentReason,
  wrapUpPrompt,
} from './logic.ts'

const TOOL = 'mcp__self-clear__request_rotation'
// The engine refuses a command run inside a hook the turn waits on, so every
// action after a turn waits one tick on the clock.
const DELAY_MS = 1000

type Ctx = { config: Config; state: State; isTold: boolean }

const disable = ($: any, ctx: Ctx, err: unknown) => {
  ctx.state.disabled = true
  ctx.state.handoffUrl = undefined
  if (ctx.isTold) return
  ctx.isTold = true
  const why = err instanceof Error ? err.message : String(err)
  $.ui.toast(`self-clear: disabled for this session: ${why}`.slice(0, 300))
}

// The reason to stay silent, or undefined.
const silence = async ($: any, agentId?: string) => {
  const ci = await $.env.get('CI')
  const { base, version } = await $.session.version()
  return silentReason({ ci, agentId, version: base ?? version })
}

const later = ($: any, ctx: Ctx, work: () => Promise<void>) =>
  $.clock.after(DELAY_MS, async () => {
    try {
      await work()
    } catch (err) {
      disable($, ctx, err)
    }
  })

const rotate = async ($: any, ctx: Ctx, url: string) => {
  ctx.state.rotations += 1
  ctx.state.handoffUrl = undefined
  ctx.state.reached = 0
  try {
    await $.command.run({ command: 'clear' })
  } catch {
    // The compaction keeps a summary that points to the handoff comment.
    await $.session.compact({ instructions: compactInstructions(url) })
  }
  await $.prompt.submit({ text: restorePrompt(url) })
}

const registerTool = async ($: any, ctx: Ctx) => {
  try {
    if ((await silence($)) !== undefined) return
    await $.tool.register({
      name: 'request_rotation',
      description:
        'Asks the session to clear its context after this turn. Call it only once the handoff skill has written the state to the issue or pull request, and pass the URL of that comment. Without a written handoff the call is refused.',
      inputSchema: {
        type: 'object',
        properties: { handoff_url: { type: 'string', description: 'URL of the handoff comment' } },
        required: ['handoff_url'],
      },
    })
  } catch (err) {
    disable($, ctx, err)
  }
}

const requestRotation = async ($: any, ctx: Ctx, e: any) => {
  try {
    if (ctx.state.disabled) return { deny: 'self-clear is disabled for this session.' }
    if ((await silence($, e.agentId)) !== undefined) return { deny: 'self-clear is not active here.' }
    if (!isHandoffUrl(e.handoff_url)) {
      return {
        deny: 'No rotation: pass the URL of the handoff comment on the issue or pull request. Write it with the handoff skill first.',
      }
    }
    if (ctx.state.rotations >= ctx.config.maxRotations) {
      return { deny: `No rotation: the cap of ${ctx.config.maxRotations} per session is reached.` }
    }
    ctx.state.handoffUrl = e.handoff_url
    return {
      result:
        'Rotation requested. End the turn now. The context is cleared after it and restarts from the handoff comment.',
    }
  } catch (err) {
    disable($, ctx, err)
    return { deny: 'self-clear failed and is disabled for this session.' }
  }
}

const turnEnd = async ($: any, ctx: Ctx, e: any) => {
  try {
    if (ctx.state.disabled || e.reason !== 'answer') return
    if ((await silence($, e.agentId)) !== undefined) return
    const { context } = await $.session.usage()
    const action = decide(ctx.state, context.percent, ctx.config)
    const percent = Math.round(context.percent ?? 0)
    if (action.kind === 'nudge') {
      ctx.state.reached = 1
      $.ui.toast(`Context at ${percent} percent. Hand off at the next package boundary.`)
    } else if (action.kind === 'wrapup' || action.kind === 'force') {
      ctx.state.reached = action.kind === 'force' ? 3 : 2
      const text = wrapUpPrompt(action.kind, percent)
      later($, ctx, () => $.prompt.submit({ text }))
    } else if (action.kind === 'rotate') {
      const url = action.url
      later($, ctx, () => rotate($, ctx, url))
    } else if (action.kind === 'capped') {
      ctx.state.handoffUrl = undefined
      $.ui.toast(`Rotation cap of ${ctx.config.maxRotations} reached. Clear the context by hand.`)
    }
  } catch (err) {
    disable($, ctx, err)
  }
}

export const register: Register = (on, options) => {
  const ctx: Ctx = { config: readConfig(options), state: freshState(), isTold: false }

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await registerTool($, ctx)
    return started
  })

  on('tool.call', { tool: TOOL }, ($, e) => requestRotation($, ctx, e)).catch(($, e, next) =>
    next.called ? next(e) : { deny: 'self-clear failed and is disabled for this session.' },
  )

  on('turn.complete', async ($, e, next) => {
    const out = await next(e)
    await turnEnd($, ctx, e)
    return out
  })

  // A clear the owner typed resets the levels: the old context is gone.
  on('session.end', async ($, e, next) => {
    if (e.reason === 'clear') {
      ctx.state.reached = 0
      ctx.state.handoffUrl = undefined
    }
    return next(e)
  })
}
