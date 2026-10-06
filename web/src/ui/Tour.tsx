import { useEffect, useState } from 'react'
import { api, type Incident } from '../api'
import { CAUSE, plainAction } from '../plain'
import { useGame } from '../store'

/**
 * Guided demo: one bus incident, end to end. The simulation is paused and moves forward only when the viewer
 * presses Next; each step highlights one part of the screen and explains it.
 */

type State = ReturnType<typeof useGame.getState>

interface Step {
  target?: string[] // data-tour anchors to highlight, first one on screen wins; none = centred card
  title: string
  body: (s: State) => string
  enter?: () => Promise<void> // runs when the step opens (drives the simulation)
  onNext?: (s: State) => Promise<void> // runs when leaving the step
  nextLabel?: (s: State) => string
}

const BUS = { kind: 'bus', x: 211, y: 107.8 }
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
let busTick = 0 // when the tour's bus was placed
let leaveTick = 0 // when it was sent away
const st = () => useGame.getState()

/** The tour's incident: the biggest one so far (the bus). */
function tourIncident(s: State = st()): Incident | null {
  const incs = (s.frame?.incidents ?? []).filter((i) => i.status !== 'false_alarm')
  return [...incs].sort((a, b) => b.phones.length - a.phones.length)[0] ?? null
}

function hasStage(stages: string[], s: State = st()): boolean {
  const inc = tourIncident(s)
  return !!inc && s.events.some((e) => e.incident === inc.id && stages.includes(e.stage))
}

/** Advance the paused simulation one second at a time until `done()` or `max` seconds. */
async function stepUntil(done: () => boolean, max: number) {
  for (let i = 0; i < max && !done(); i++) {
    const id = st().sessionId
    if (!id) return
    const before = st().frame?.tick ?? 0
    await api.control(id, 'step')
    for (let w = 0; w < 30 && (st().frame?.tick ?? 0) <= before; w++) await sleep(50) // wait for the live frame
  }
  const inc = tourIncident()
  if (inc && st().selected !== inc.id) st().select(inc.id)
}

const lastEvent = (stages: string[]) => {
  const inc = tourIncident()
  return inc ? [...st().events].reverse().find((e) => e.incident === inc.id && stages.includes(e.stage)) : undefined
}

const STEPS: Step[] = [
  {
    title: 'Guided demo: one incident, start to finish',
    body: () => 'We’ll walk through a single real incident on a simulated 5G street, about two minutes. '
      + 'The simulation is paused and only moves forward when you press Next, so you can read each step.',
    enter: async () => {
      st().setIntro(false)
      st().setMode('simple')
      st().setTool(null)
      await st().start({ start_paused: true })
      await sleep(400)
    },
    nextLabel: () => 'Start',
  },
  {
    target: ['map'],
    title: 'The street',
    body: (s) => `This is Station Road: offices, a market, a hospital and three mobile towers. Each dot is one of the `
      + `${s.frame?.phones.length ?? 60} people using their phone here. You can drag to rotate the view and scroll to zoom.`,
  },
  {
    target: ['legend'],
    title: 'How to read the map',
    body: () => 'Green dots have good service, amber is slow, red has no usable signal. The thin lines show which tower '
      + 'serves each phone. A red line ending in ✖ means something is blocking that signal.',
  },
  {
    target: ['stats'],
    title: 'The scoreboard',
    body: () => 'Live numbers for the whole street: how many users have service and how many are affected right now. '
      + 'The box in the middle runs a hidden copy of the same street with the same problems but no agent, so you can '
      + 'see what would happen without it.',
  },
  {
    target: ['map'],
    title: 'A bus parks at the bus stop',
    body: (s) => {
      const inc = tourIncident(s)
      return `The bus stands between Tower A and the people waiting at the stop. Watch the dots near it turn red and their `
        + `lines end in ✖: ${inc ? `${inc.phones.length} users` : 'several users'} just lost good service.`
    },
    enter: async () => {
      busTick = st().frame?.tick ?? 0
      await st().addProblem(BUS)
      await stepUntil(() => !!tourIncident(), 5)
    },
  },
  {
    target: ['status'],
    title: 'The agent notices',
    body: (s) => {
      const inc = tourIncident(s)
      const secs = inc ? Math.max(1, inc.opened - busTick) : null
      return 'Nobody reported anything. The agent watches every phone’s signal once a second and spotted the drop '
        + `${secs ? `${secs} second${secs > 1 ? 's' : ''} after the bus arrived` : 'within seconds'}. `
        + 'This line at the top always says what is happening right now.' 
    },
  },
  {
    target: ['cause'],
    title: 'Step 1: find the cause',
    body: (s) => {
      const inc = tourIncident(s)
      const c = CAUSE[inc?.cause ?? 'unknown'] ?? CAUSE.unknown
      return `The diagnosis model (a pretrained wireless AI model, LWM, plus a classifier) looked only at the phones’ `
        + `signal reports. It cannot see the street, yet it concluded “${c.title}”`
        + `${inc ? ` with ${Math.round(inc.confidence * 100)}% confidence` : ''}. The cause matters: each cause needs a different fix.`
    },
    enter: async () => { await stepUntil(() => hasStage(['diagnose']), 3) },
  },
  {
    target: ['steps'],
    title: 'The agent’s loop',
    body: () => 'Every problem goes through the same seven steps: detect, diagnose, test fixes on the digital twin, '
      + 'safety check, your approval if the change is large, apply, and verify. The lit circle shows where it is now.',
  },
  {
    target: ['twin'],
    title: 'Step 2: test fixes on the digital twin',
    body: () => {
      const reh = lastEvent(['rehearse'])
      const n = reh?.text.match(/Rehearsed (\d+)/)?.[1]
      return `Before touching the real network, the agent tried ${n ?? 'several'} possible fixes on a virtual copy of the `
        + 'street (the digital twin) and ranked them by how much they help and whom they might hurt. '
        + 'A ✕ means the safety check ruled that fix out, with the reason underneath.'
    },
    enter: async () => { await stepUntil(() => hasStage(['rehearse']), 3) },
  },
  {
    target: ['approval', 'twin', 'steps'],
    title: 'Step 3: safety check, then act',
    body: (s) => {
      const inc = tourIncident(s)
      if (inc?.waiting_for_you) {
        return `“${plainAction(inc.pending ?? '')}” passed every safety rule, but it is larger than the agent may make on `
          + 'its own, so it asks you, the network operator. Press Next to approve it (or use the buttons yourself).'
      }
      const act = lastEvent(['act'])
      const why = lastEvent(['escalate'])
      if (act) return `The best fix that passed every safety rule was applied: ${plainAction(String(act.data.action ?? ''))}. `
        + 'Hard limits (power, how often settings change, harm to other users, the hospital’s reserved capacity) are '
        + 'enforced by plain code, not by AI.'
      return why ? `No fix passed every safety rule, so the agent changed nothing and handed it to the operator. That is `
        + 'by design: it never takes a risk it can’t justify.' : 'The agent is choosing a fix.'
    },
    enter: async () => {
      await stepUntil(() => hasStage(['act', 'escalate']) || !!tourIncident()?.waiting_for_you, 4)
    },
    onNext: async (s) => {
      const inc = tourIncident(s)
      if (inc?.waiting_for_you) await s.answer(inc.id, 'approve')
    },
    nextLabel: (s) => (tourIncident(s)?.waiting_for_you ? 'Approve and continue' : 'Next'),
  },
  {
    target: ['result', 'steps'],
    title: 'Step 4: check that it really worked',
    body: () => {
      const undone = !!lastEvent(['undo'])
      const kept = lastEvent(['verify'])
      let t = 'Three seconds after each change, the agent measures the real result and compares it with the twin’s prediction. '
      if (undone) t += 'One attempt fell short, so it was undone automatically and the next-best fix was tried. '
      if (kept) t += `The kept fix improved signal by ${Number(kept.data.measured).toFixed(1)} dB `
        + `(the twin predicted ${Number(kept.data.predicted).toFixed(1)} dB).`
      else if (!undone) t += 'Here no fix could be kept within the safety limits, so the agent asked the operator instead.'
      return t
    },
    enter: async () => {
      await stepUntil(() => hasStage(['verify']) || (hasStage(['undo']) && hasStage(['escalate'])), 14)
    },
  },
  {
    target: ['compare'],
    title: 'With vs without the agent',
    body: (s) => {
      const w = s.frame?.without_agent?.degraded_now
      const a = s.frame?.score.degraded_now
      return w != null && a != null
        ? `Right now ${a} users are affected with the agent, against ${w} on the identical street without it. `
          + 'Same bus, same moment: the difference is the agent.'
        : 'This compares the street with the agent against an identical copy without it.'
    },
  },
  {
    target: ['vehicle', 'toolbar'],
    title: 'You control the bus',
    body: () => 'Every bus, truck, crowd or board you place can be moved along the road with ◀◀ ◀ ▶ ▶▶ (or the ← → keys), '
      + 'so you can drive it in and out of the signal path yourself. Press Next and the bus will drive off.',
  },
  {
    target: ['result', 'status'],
    title: 'The bus leaves',
    body: () => {
      const after = (stages: string[]) => {
        const inc = tourIncident()
        return st().events.filter((e) => e.incident === inc?.id && e.tick >= leaveTick && stages.includes(e.stage))
      }
      const parts: string[] = []
      if (after(['undo']).some((e) => e.text.includes('Hospital'))) {
        parts.push('While the bus pulled away, the hospital’s tower briefly went over its reserved limit, so the safety '
          + 'guard undid the handover at once. Protecting the hospital outranks everything else.')
      }
      if (after(['withdraw']).length) {
        parts.push('With the bus gone, the agent saw the original signal come back and removed its temporary fix, '
          + 'returning the network to its normal settings.')
      }
      if (after(['resolve']).length) parts.push('Users are healthy again and the problem is closed.')
      return parts.length ? parts.join(' ') : 'The bus has left and service is recovering. The agent closes the problem once users are healthy again.'
    },
    enter: async () => {
      const bus = st().frame?.problems.find((p) => p.kind === 'bus')
      leaveTick = st().frame?.tick ?? 0
      if (bus) await st().sendAway(bus.id)
      await stepUntil(() => hasStage(['withdraw', 'resolve']) && !st().frame?.problems.length, 16)
    },
  },
  {
    target: ['mode'],
    title: 'Simple and Expert views',
    body: () => 'You have been using the Simple view. Expert shows everything underneath: every agent step with its '
      + 'timing, each cause’s probability, the twin’s full ranking and the raw decision log.',
  },
  {
    target: ['toolbar'],
    title: 'Your turn',
    body: () => 'Create any problem from this toolbar (truck, crowd, a misaimed beam, a misconfigured tower, an illegal '
      + 'booster, a crowd surge) or use a quick scenario, and watch the agent handle it. Press Finish to restart the '
      + 'live simulation.',
    onNext: async () => { await st().control('resume') },
    nextLabel: () => 'Finish',
  },
]

export default function Tour() {
  const n = useGame((s) => s.tour)
  const setTour = useGame((s) => s.setTour)
  useGame((s) => s.frame) // re-render as the simulation moves
  const [busy, setBusy] = useState(false)
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [ranUpTo, setRanUpTo] = useState(-1) // steps whose simulation action already ran (Back must not repeat them)
  const step = n !== null ? STEPS[n] : null

  // run the step's simulation action when it opens
  useEffect(() => {
    if (n === null) { setRanUpTo(-1); return }
    if (n <= ranUpTo) return
    setRanUpTo(n)
    if (!STEPS[n].enter) return
    let live = true
    setBusy(true)
    STEPS[n].enter!().catch((e) => st().notify(String(e), 'error')).finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [n]) // eslint-disable-line react-hooks/exhaustive-deps

  // follow the highlighted element as the layout changes
  useEffect(() => {
    if (!step?.target) { setRect(null); return }
    const measure = () => {
      const el = step.target!.map((t) => document.querySelector(`[data-tour="${t}"]`)).find(Boolean)
      if (el) el.scrollIntoView({ block: 'nearest' })
      setRect(el ? el.getBoundingClientRect() : null)
    }
    measure()
    const t = setInterval(measure, 250)
    return () => clearInterval(t)
  }, [step, busy])

  if (n === null || !step) return null
  const s = st()
  const last = n === STEPS.length - 1
  const exit = () => { setTour(null); st().select(null) }
  const next = async () => {
    setBusy(true)
    try { await step.onNext?.(s) } finally { setBusy(false) }
    if (last) exit()
    else setTour(n + 1)
  }

  const W = 380
  const pad = 14
  let pos: React.CSSProperties = { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
  if (rect) {
    const vw = window.innerWidth
    const vh = window.innerHeight
    if (rect.width > vw * 0.45 && rect.height > vh * 0.4) pos = { left: rect.left + 24, top: rect.top + 110 }
    else if (rect.left > vw * 0.5) pos = { left: Math.max(pad, rect.left - W - pad), top: Math.min(Math.max(pad, rect.top), vh - 280) }
    else if (rect.top > vh * 0.55) pos = { left: Math.min(Math.max(pad, rect.left), vw - W - pad), top: Math.max(pad, rect.top - 250) }
    else pos = { left: Math.min(Math.max(pad, rect.left), vw - W - pad), top: Math.min(rect.bottom + pad, vh - 280) }
  }

  return (
    <div className="pointer-events-none fixed inset-0 z-50">
      {rect ? (
        <div className="absolute rounded-xl ring-2 ring-sky-400 transition-all duration-300"
          style={{ left: rect.left - 4, top: rect.top - 4, width: rect.width + 8, height: rect.height + 8,
            boxShadow: '0 0 0 9999px rgba(2, 6, 23, 0.62)' }} />
      ) : (
        <div className="absolute inset-0 bg-slate-950/70" />
      )}
      <div className="pointer-events-auto absolute rounded-2xl border border-sky-500/50 bg-slate-900 p-5 shadow-2xl"
        style={{ width: W, ...pos }}>
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-sky-300">Guided demo · {n + 1} / {STEPS.length}</span>
          <button className="hover:text-slate-200" onClick={exit}>Exit ✕</button>
        </div>
        <div className="mt-1.5 h-1 rounded-full bg-slate-800">
          <div className="h-1 rounded-full bg-sky-400 transition-all" style={{ width: `${((n + 1) / STEPS.length) * 100}%` }} />
        </div>
        <h3 className="mt-3 text-lg font-semibold text-slate-50">{step.title}</h3>
        <p className="mt-2 text-[15px] leading-relaxed text-slate-300">
          {busy ? 'Running the simulation…' : step.body(s)}
        </p>
        <div className="mt-4 flex items-center justify-between">
          <button className="btn bg-slate-800 text-slate-300 hover:bg-slate-700" disabled={busy || n === 0}
            onClick={() => setTour(Math.max(0, n - 1))}>
            Back
          </button>
          <button className="btn bg-sky-500 px-5 text-sky-950 hover:bg-sky-400" disabled={busy} onClick={() => void next()}>
            {busy ? '…' : step.nextLabel?.(s) ?? 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
