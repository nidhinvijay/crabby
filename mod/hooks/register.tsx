import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Yard } from '../types'

const BS = String.fromCharCode(92)

// The desktop pet (the crabby folder inside your Claude config folder) reads a small state file per chat from here.
let petDirCache = ''
async function petDir($: EngineInterface): Promise<string> {
  if (petDirCache) return petDirCache
  const cfg = await $.env.get('CLAUDE_CONFIG_DIR')
  const home = (await $.env.get('USERPROFILE')) || (await $.env.get('HOME')) || ''
  const base = cfg || `${home}/.claude`
  petDirCache = `${base.split(BS).join('/')}/crabby`
  return petDirCache
}
// One state file per chat: the session id keeps the name stable across reloads of this mod.
let sid = ''
const meta = { project: '', closed: false }
let beat: { cancel: () => void } | undefined

// The folder name of the chat's working directory; the app's own scratch folders have no sensible name.
const projectOf = (cwd: string): string => {
  const parts = cwd.split(/[\\/]+/).filter(Boolean)
  const last = parts[parts.length - 1] ?? ''
  if (!last || /scratch-workspaces/i.test(cwd) || /^[A-Za-z]:$/.test(last)) return 'Chat (no folder)'
  return last
}

const yard = atom({ plugin: 'crabby', key: 'yard' } as const, { busy: false, doneAt: 0, crabs: [] } as Yard)

// What the desktop pet also wants to know: plan usage, the tool in use, errors, "needs you".
const extra = { usage: -1, resetsAt: '', busySince: 0, tool: '', toolAt: 0, errorAt: 0, needs: false, needsAt: 0 }

async function writePet($: EngineInterface): Promise<void> {
  try {
    const y = await read($, yard)
    sid = sid || (await $.session.id())
    const body = {
      sid,
      project: meta.project,
      closed: meta.closed,
      busy: y.busy,
      doneAt: y.doneAt,
      agents: y.crabs.map(c => ({ id: c.id, tier: c.tier })),
      usage: extra.usage,
      resetsAt: extra.resetsAt,
      busySince: extra.busySince,
      tool: extra.tool,
      errorAt: extra.errorAt,
      needs: extra.needs,
      needsAt: extra.needsAt,
      updatedAt: await $.clock.now(),
    }
    await $.fs.write(`${await petDir($)}/state-${sid.replace(/[^A-Za-z0-9_-]/g, '')}.json`, JSON.stringify(body))
  } catch {}
}

// Every change also goes to the pet's state file, so the desktop crab knows what Claude is doing.
async function setYard($: EngineInterface, fn: (y: Yard) => Yard): Promise<void> {
  await update($, yard, fn)
  await writePet($)
}

// Starts the pet unless it is already running. Returns true if it was started.
async function startPet($: EngineInterface): Promise<boolean> {
  const dir = await petDir($)
  const age = await $.fs
    .stat(`${dir}/alive`)
    .then(st => (st.kind === 'file' ? (async () => (await $.clock.now()) - st.mtimeMs)() : Promise.resolve(1e9)))
    .catch(() => Promise.resolve(1e9))
  if (age < 6000) return false
  if (await $.env.get('USERPROFILE')) await $.process.run(['wscript.exe', dir.split('/').join(BS) + BS + 'start.vbs'], { timeoutMs: 15000 })
  else await $.process.run(['/bin/sh', `${dir}/start.sh`], { timeoutMs: 15000 }) // macOS
  return true
}

// ---- Helper crabs: a stable outfit per subagent ----
const TIERS: readonly string[] = ['chef', 'pirate', 'dev', 'student', 'manager', 'teacher', 'wizard', 'scientist', 'ninja', 'musician', 'gardener', 'viking']
const hash = (s: string): number => {
  let h = 0
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h
}
// Random look: the costume comes from the agent's id, so it stays the same for that agent.
const pickTier = (id: string): string => TIERS[hash(id) % TIERS.length] ?? "chef"

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'pet',
      description: 'Start or stop the crab desktop pet, a little crab that walks around your screen while Claude works',
    })
    meta.project = projectOf(e.cwd)
    meta.closed = false
    beat?.cancel()
    beat = $.clock.every(60000, () => {
      void writePet($)
    })
    await writePet($)
    if (options.autoStart === true) {
      try {
        await startPet($)
        await writePet($)
      } catch {}
    }
    return next(e)
  })

  // The chat is closing (not a /clear): tell the pet at once.
  on('session.end', async ($, e, next) => {
    if (e.reason !== 'clear') {
      meta.closed = true
      beat?.cancel()
      await writePet($)
    }
    return next(e)
  })

  on('command.run', { command: 'pet' }, async $ => {
    const dir = await petDir($)
    const age = await $.fs
      .stat(`${dir}/alive`)
      .then(st => (st.kind === 'file' ? (async () => (await $.clock.now()) - st.mtimeMs)() : Promise.resolve(1e9)))
      .catch(() => Promise.resolve(1e9))
    if (age < 6000) {
      await $.fs.write(`${dir}/quit`, '1')
      return { text: 'Crab pet is going to sleep. It closes in a few seconds.' }
    }
    await setYard($, y => y)
    try {
      await startPet($)
    } catch {
      return { text: 'Could not start the crab pet. You can run start.vbs (Windows) or start.sh (macOS) in the crabby folder inside your .claude folder.' }
    }
    return { text: 'Crab pet started. Right-click it for a menu. Run /pet again to stop it.' }
  })

  // The main loop starts a turn: the main crab sets off.
  on('turn.start', async ($, e, next) => {
    if (!e.agentId) {
      extra.needs = false
      extra.tool = ''
    }
    if (!e.agentId && !extra.busySince) extra.busySince = await $.clock.now()
    await setYard($, y => ({ ...y, busy: true }))
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const at = await $.clock.now()
    const agentId = e.agentId
    if (agentId) {
      await setYard($, y => ({ ...y, crabs: y.crabs.filter(c => c.agentId !== agentId) }))
    } else {
      extra.needs = false
      extra.tool = ''
      extra.busySince = 0
      if (e.reason === 'error' || e.reason === 'refusal') extra.errorAt = at
      // helpers may outlive the main turn (background agents): they leave on their own turn.complete, or after 30 minutes
      await setYard($, y => ({ ...y, busy: false, crabs: y.crabs.filter(c => at - (c.at ?? at) < 1800000), doneAt: e.reason === 'answer' ? at : 0 }))
    }
    return next(e)
  })

  // The tool in use, so the pet can hold a prop (magnifier, hammer...). Cleared when the tool ends.
  on('tool.call', async ($, e, next) => {
    if (e.agentId) return next(e)
    extra.tool = e.tool
    extra.toolAt = await $.clock.now()
    if (e.tool === 'AskUserQuestion') {
      extra.needs = true
      extra.needsAt = extra.toolAt
    } else {
      extra.needs = false // another tool started: nothing is waiting for the person any more
    }
    await writePet($)
    try {
      return await next(e)
    } finally {
      extra.needs = false
      if (extra.tool === e.tool) extra.tool = ''
      await writePet($)
    }
  })

  // The engine says "ask": Claude is waiting for the person to allow something.
  on('tool.check', async ($, e, next) => {
    const v = await next(e)
    if (v.decision === 'ask' && e.tool_use_id && !e.agentId) {
      extra.needs = true
      extra.needsAt = await $.clock.now()
      await writePet($)
    }
    return v
  })

  // Plan usage (five-hour window), for the pet's tired mood.
  on('session.measure', async ($, e, next) => {
    const w = e.rateLimits.find(r => r.kind === 'five_hour')
    const pct = w ? w.percentUsed : -1
    const resets = w?.resetsAt ?? ''
    if (pct !== extra.usage || resets !== extra.resetsAt) {
      extra.usage = pct
      extra.resetsAt = resets
      await writePet($)
    }
    return next(e)
  })

  // Every subagent brings its own crab, in a costume picked from its id.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    if (started.deny !== undefined) return started
    const id = started.agentId ?? e.tool_use_id
    const now = await $.clock.now()
    await setYard($, y => ({
      ...y,
      crabs: [...y.crabs.filter(c => c.id !== id && now - (c.at ?? now) < 1800000), { id, agentId: started.agentId, tier: pickTier(id), at: now }].slice(-8),
    }))
    return started
  })
}
