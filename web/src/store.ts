import { useMemo } from 'react'
import { create } from 'zustand'
import { api, ApiError, liveUrl, type AgentEvent, type Frame, type Incident, type NewGame, type NewProblem, type Scene } from './api'
import { laneY } from './scene/vehicleGeometry'

export type PolicyTab = 'ask' | 'gaps' | 'kb' | 'itu'

export type Tool =
  | { kind: 'bus' | 'truck' | 'car'; drive: boolean }
  | { kind: 'crowd' | 'kiosk' | 'hoarding' | 'stuck_beam' | 'booster' | 'crowd_surge' | 'misconfig' }
  | null

export interface HistoryPoint { tick: number; good: number; fair: number; poor: number; degraded: number; without: number | null }

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
  tour: number | null // UI tour step, or null when not touring
  setTour: (n: number | null) => void
  demo: boolean // the incident demo is running
  setDemo: (on: boolean) => void
  policyOpen: boolean // the policy & knowledge base screen
  setPolicyOpen: (open: boolean) => void
  policyTab: PolicyTab
  adviserIncident: string | null // the incident the adviser is asked about, if any
  openPolicy: (tab: PolicyTab, incident?: string | null) => void
  rolesOf: string | null // the incident shown in "who knew what, when"

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
let startGen = 0 // only the latest start() may take over the screen

export const useGame = create<Store>((set, get) => {
  const fail = (e: unknown) => get().notify(e instanceof Error ? e.message : String(e), 'error')

  function ingest(f: Frame) {
    const s = get()
    const last = s.frame?.tick ?? -1
    const fresh = f.tick > last
    const events = fresh && f.events.length ? [...s.events, ...f.events].slice(-MAX_EVENTS) : s.events
    const history = fresh
      ? [...s.history, { tick: f.tick, good: f.score.good, fair: f.score.fair, poor: f.score.poor,
          degraded: f.score.degraded_now, without: f.without_agent?.degraded_now ?? null }].slice(-MAX_HISTORY)
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
    tour: null,
    setTour: (tour) => set({ tour, demo: false }),
    demo: false,
    setDemo: (demo) => set({ demo, tour: null }),
    policyOpen: false,
    setPolicyOpen: (policyOpen) => set({ policyOpen }),
    policyTab: 'ask',
    adviserIncident: null,
    openPolicy: (policyTab, incident) => set({ policyOpen: true, policyTab, adviserIncident: incident ?? null }),
    rolesOf: null,

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
        // Detach from the old game's stream first: when the server closes it, that must not look like
        // "the server lost our game" (which would start yet another game).
        const oldSocket = socket
        socket = null
        if (retry) clearTimeout(retry)
        oldSocket?.close()
        set({ connected: false })
        const old = get().sessionId
        if (old) api.stop(old).catch(() => {})
        const gen = ++startGen
        const g = await api.newGame({ language_model: true, speed: 1, ...opts })
        if (gen !== startGen) { api.stop(g.id).catch(() => {}); return } // a newer start() won: drop this game
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
          if (get().sessionId && get().sessionId !== saved) return // a new game was started meanwhile
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
        p.y = laneY(y)
        p.drive = false // vehicles park where you click; move them with the arrow buttons
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
        if (r.x != null && p.x != null && Math.abs(r.x - p.x) > 0.5) {
          get().notify(`That spot was taken, so the ${p.kind} parked ${Math.abs(r.x - p.x).toFixed(0)} m along the lane.`)
        }
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

/**
 * The incident the panels and the map focus on: the one the player picked, else whatever needs them, else the
 * biggest open problem, else the biggest recent one. One- or two-user side effects don't take over.
 */
export function pickMain(incidents: Incident[], selected: string | null = null): Incident | null {
  if (selected) return incidents.find((i) => i.id === selected) ?? null
  const real = incidents.filter((i) => i.status !== 'false_alarm')
  const waiting = real.find((i) => i.waiting_for_you)
  if (waiting) return waiting
  const bySize = (a: Incident, b: Incident) => b.phones.length - a.phones.length || b.opened - a.opened
  const open = real.filter((i) => i.status !== 'resolved').sort(bySize)
  if (open.length && open[0].phones.length > 2) return open[0]
  const recent = [...real].sort((a, b) => b.opened - a.opened).slice(0, 4).sort(bySize)
  return open[0] ?? recent[0] ?? null
}

const NO_INCIDENTS: Incident[] = []

export function useFocusedIncident() {
  const incidents = useGame((s) => s.frame?.incidents ?? NO_INCIDENTS)
  const selected = useGame((s) => s.selected)
  return useMemo(() => pickMain(incidents, selected), [incidents, selected])
}
