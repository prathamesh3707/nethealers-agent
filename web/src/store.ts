import { create } from 'zustand'
import { api, ApiError, liveUrl, type AgentEvent, type Frame, type NewGame, type NewProblem, type Scene } from './api'

export type Tool =
  | { kind: 'bus' | 'truck' | 'car'; drive: boolean }
  | { kind: 'crowd' | 'kiosk' | 'hoarding' | 'stuck_beam' | 'booster' | 'crowd_surge' | 'misconfig' }
  | null

export interface HistoryPoint { tick: number; good: number; fair: number; poor: number; degraded: number }

const MAX_EVENTS = 800
const MAX_HISTORY = 180
const SESSION_KEY = 'nethealers.session'
const MODE_KEY = 'nethealers.mode'
const INTRO_KEY = 'nethealers.introSeen'

function load(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
function save(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* storage blocked: keep it in memory */ }
}

interface Store {
  sessionId: string | null
  scene: Scene | null
  frame: Frame | null
  events: AgentEvent[]
  history: HistoryPoint[]
  plannedTowers: Record<number, { power: number; tilt: number }>
  connected: boolean
  starting: boolean
  languageModel: boolean
  tool: Tool
  selected: string | null // incident the side panel focuses on; null = follow the latest
  toast: { text: string; tone: 'info' | 'error' } | null
  mode: 'simple' | 'expert'
  introOpen: boolean
  movable: string | null // the blocker the arrow controls move

  setMode: (m: 'simple' | 'expert') => void
  setIntro: (open: boolean) => void
  setMovable: (id: string | null) => void
  nudge: (dx: number, dy?: number) => Promise<void>

  start: (opts?: Partial<NewGame>) => Promise<void>
  resume: () => Promise<void>
  setTool: (t: Tool) => void
  select: (id: string | null) => void
  place: (x: number, y: number) => Promise<void>
  addProblem: (p: NewProblem) => Promise<void>
  removeProblem: (id: string) => Promise<void>
  sendAway: (id: string) => Promise<void>
  control: (action: 'pause' | 'resume' | 'step' | 'speed', value?: number) => Promise<void>
  answer: (incident: string, decision: 'approve' | 'reject') => Promise<void>
  notify: (text: string, tone?: 'info' | 'error') => void
}

export const BOX_KINDS = new Set(['bus', 'truck', 'car', 'crowd', 'kiosk', 'hoarding'])

let socket: WebSocket | null = null
let retry: ReturnType<typeof setTimeout> | null = null
let startedOnce = false

export const useGame = create<Store>((set, get) => {
  const fail = (e: unknown) => get().notify(e instanceof Error ? e.message : String(e), 'error')

  function ingest(f: Frame) {
    const s = get()
    const last = s.frame?.tick ?? -1
    const fresh = f.tick > last
    const events = fresh && f.events.length ? [...s.events, ...f.events].slice(-MAX_EVENTS) : s.events
    const history = fresh
      ? [...s.history, { tick: f.tick, good: f.score.good, fair: f.score.fair, poor: f.score.poor,
          degraded: f.score.degraded_now }].slice(-MAX_HISTORY)
      : s.history
    set({ frame: f, events, history })
  }

  function connect(id: string) {
    if (retry) clearTimeout(retry)
    socket?.close()
    const ws = new WebSocket(liveUrl(id))
    socket = ws
    ws.onopen = () => {
      set({ connected: true })
      api.events(id).then((events) => set({ events: events.slice(-MAX_EVENTS) })).catch(() => {})
    }
    ws.onmessage = (m) => ingest(JSON.parse(m.data) as Frame)
    ws.onclose = (ev) => {
      if (socket !== ws) return
      set({ connected: false })
      if (ev.code === 4404 || ev.code === 4410) {
        // the server no longer has this game (restart or eviction): start a fresh one
        get().notify('The game ended on the server. Starting a new one.', 'info')
        void get().start()
        return
      }
      retry = setTimeout(() => connect(id), 1500)
    }
  }

  return {
    sessionId: null, scene: null, frame: null, events: [], history: [], plannedTowers: {},
    connected: false, starting: false, languageModel: false, tool: null, selected: null, toast: null,
    mode: load(MODE_KEY) === 'expert' ? 'expert' : 'simple',
    introOpen: load(INTRO_KEY) !== '1',
    movable: null,

    setMode(mode) { save(MODE_KEY, mode); set({ mode }) },
    setIntro(open) { if (!open) save(INTRO_KEY, '1'); set({ introOpen: open }) },
    setMovable: (movable) => set({ movable }),

    async nudge(dx, dy = 0) {
      const { sessionId, frame, movable } = get()
      const pid = movable ?? frame?.problems.find((p) => p.x != null && BOX_KINDS.has(p.kind))?.id
      const p = frame?.problems.find((q) => q.id === pid)
      if (!sessionId || !p || p.x == null || p.y == null) return
      set({ movable: p.id })
      try {
        await api.moveProblem(sessionId, p.id, p.x + dx, p.y + dy)
      } catch (e) {
        fail(e)
      }
    },

    async start(opts) {
      set({ starting: true })
      try {
        const old = get().sessionId
        if (old) api.stop(old).catch(() => {})
        const g = await api.newGame({ language_model: true, speed: 1, ...opts })
        sessionStorage.setItem(SESSION_KEY, g.id)
        set({
          sessionId: g.id, scene: g.scene, frame: g.state, events: [], history: [], selected: null,
          languageModel: g.language_model,
          plannedTowers: Object.fromEntries(g.state.towers.map((t) => [t.id, { power: t.power_dbm, tilt: t.tilt }])),
        })
        connect(g.id)
      } catch (e) {
        fail(e)
      } finally {
        set({ starting: false })
      }
    },

    async resume() {
      if (startedOnce) return
      startedOnce = true
      const saved = sessionStorage.getItem(SESSION_KEY)
      if (saved) {
        try {
          const [scene, frame] = await Promise.all([api.scene(saved), api.state(saved)])
          set({
            sessionId: saved, scene, frame, languageModel: !!frame.llm.live,
            plannedTowers: Object.fromEntries(frame.towers.map((t) => [t.id, { power: t.power_dbm, tilt: t.tilt }])),
          })
          connect(saved)
          return
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 404)) fail(e)
        }
      }
      await get().start()
    },

    setTool: (tool) => set({ tool }),
    select: (selected) => set({ selected }),

    async place(x, y) {
      const { tool, frame } = get()
      if (!tool || !frame) return
      const p: NewProblem = { kind: tool.kind, x, y }
      if ('drive' in tool) {
        // vehicles stay in a lane of Station Road
        p.y = y > 100 ? 107.8 : 92.2
        p.drive = tool.drive
        p.stay = 30
      } else if (tool.kind === 'misconfig') {
        const nearest = [...frame.towers].sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y))[0]
        p.tower = nearest.id
        delete p.x
        delete p.y
      } else if (tool.kind === 'crowd_surge') {
        p.people = 60
      }
      await get().addProblem(p)
    },

    async addProblem(p) {
      const id = get().sessionId
      if (!id) return
      try {
        const r = await api.addProblem(id, p)
        if (BOX_KINDS.has(p.kind)) set({ movable: r.id }) // the arrow controls now move what was just placed
      } catch (e) {
        fail(e)
      }
    },

    async removeProblem(pid) {
      const id = get().sessionId
      if (id) await api.removeProblem(id, pid).catch(fail)
    },

    async sendAway(pid) {
      const id = get().sessionId
      if (id) await api.sendAway(id, pid).catch(fail)
    },

    async control(action, value) {
      const id = get().sessionId
      if (id) await api.control(id, action, value).catch(fail)
    },

    async answer(incident, decision) {
      const id = get().sessionId
      if (id) await api.answer(id, incident, decision).catch(fail)
    },

    notify(text, tone = 'info') {
      set({ toast: { text, tone } })
      setTimeout(() => { if (get().toast?.text === text) set({ toast: null }) }, 4500)
    },
  }
})

/** The incident the panel should show: the one the player picked, else whatever needs them, else the newest. */
export function useFocusedIncident() {
  return useGame((s) => {
    const incs = s.frame?.incidents ?? []
    if (s.selected) return incs.find((i) => i.id === s.selected) ?? null
    return incs.find((i) => i.waiting_for_you)
      ?? [...incs].reverse().find((i) => !['resolved', 'false_alarm'].includes(i.status))
      ?? incs[incs.length - 1]
      ?? null
  })
}
