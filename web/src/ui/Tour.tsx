import { useEffect, useState } from 'react'
import { useGame } from '../store'
import { Highlight, freshPausedGame, game, mainIncident, placeNear, sleep, stepUntil, useTargetRect } from './Spotlight'

/**
 * UI tour: what every part of the screen means. It sets up one example problem (a parked bus) in the background so
 * every card and number has something to show, then walks through them one at a time.
 */

interface Step { targets?: string[]; title: string; body: string }

const STEPS: Step[] = [
  {
    title: 'A tour of the screen',
    body: 'This tour explains what each part of the screen shows. We have paused the simulation and parked one bus at the '
      + 'bus stop as an example, so every panel has something in it. For the story of what the agent does, take the '
      + 'incident demo afterwards.',
  },
  {
    targets: ['status'],
    title: 'Status line',
    body: 'One sentence about what is happening right now: which users are affected and what the agent is doing about it. '
      + 'Green means all is well, red means a problem is open, amber means the agent needs you.',
  },
  {
    targets: ['controls'],
    title: 'Simulation controls',
    body: 'Pause and resume the simulation, step one second forward while paused, and change the speed (0.5× to 4×). '
      + 'The clock shows simulated time; one tick is one second, and the agent takes one turn every tick.',
  },
  {
    targets: ['policy'],
    title: 'Policy and knowledge base',
    body: 'Opens the gap analysis and the knowledge base behind it: what India’s laws, ITU-T standards, global examples '
      + '(EU, US, Singapore) and neighbouring countries (Sri Lanka, Bangladesh, Nepal) say about an AI agent running a '
      + '5G network, where they fall short, and every source passage. You can also search the knowledge base.',
  },
  {
    targets: ['mode'],
    title: 'Simple and Expert views',
    body: 'Simple (now) uses plain language and shows only the main problem. Expert shows everything: every agent step '
      + 'with its timing in milliseconds, each cause’s probability, the full twin ranking and the raw log.',
  },
  {
    targets: ['llm'],
    title: 'Language model status',
    body: 'Whether the AI planner and AI safety reviewer are switched on, and how many calls they have made. When on, they '
      + 'choose among safe fixes and explain why. When off, simple rules take the top-ranked safe fix. Either way, hard '
      + 'safety limits are enforced by plain code.',
  },
  {
    targets: ['map'],
    title: 'The 3D street',
    body: 'Station Road: buildings, three mobile towers and about 60 people using their phones. Drag to rotate, scroll to '
      + 'zoom. Glass buildings are see-through; materials matter because signals bounce off and through them differently.',
  },
  {
    targets: ['legend'],
    title: 'Dots and lines',
    body: 'Each dot is a phone. Green: good service (signal clarity of 13 dB or more). Amber: slow (0 to 13 dB). Red: no '
      + 'usable signal (below 0 dB). Each line joins a phone to the tower serving it. A red line ending in ✖ is a '
      + 'signal blocked by something on the street. A pulsing ring marks phones the agent is fixing.',
  },
  {
    targets: ['tower'],
    title: 'Tower labels',
    body: 'Each tower shows how busy it is (the share of its capacity in use; above 100% means overloaded). If the agent '
      + 'has changed a tower’s settings, the label turns amber and says “adjusted by agent”.',
  },
  {
    targets: ['hospital'],
    title: 'Protected hospital zone',
    body: 'The red area around the hospital is protected: its tower must always keep spare capacity for emergency '
      + 'traffic. The label shows how much is used against the limit. No fix may push it over, even if that would help '
      + 'other users.',
  },
  {
    targets: ['blocker'],
    title: 'Problems on the street',
    body: 'Things you place on the street appear in 3D: buses, trucks, crowds, boards. This bus is what is blocking '
      + 'the signal for the people at the bus stop.',
  },
  {
    targets: ['toolbar'],
    title: 'Create a problem',
    body: 'Pick a problem, then click on the street. Bus, truck, crowd and hoarding block signals; a stuck beam aims '
      + 'badly at nearby phones; bad tower settings and an illegal booster cause interference; a crowd surge overloads a '
      + 'tower. Each one tests a different kind of fix.',
  },
  {
    targets: ['scenarios'],
    title: 'Quick scenarios',
    body: 'One click places a ready-made problem in a spot where it has a clear effect, useful for a live demo.',
  },
  {
    targets: ['vehicle', 'toolbar'],
    title: 'Move what you placed',
    body: '◀◀ and ▶▶ move it 20 m along the road, ◀ and ▶ move it 5 m (or use the ← and → keys). “drive off” makes a '
      + 'vehicle leave; ✕ removes the problem. Moving a bus in and out of the signal path is the easiest way to show the '
      + 'agent reacting.',
  },
  {
    targets: ['cause'],
    title: 'The problem card',
    body: 'Which users lost service and where, the cause the AI diagnosis found and how sure it is, and the current state '
      + '(working on it, checking a fix, waiting for you, fixed). The diagnosis uses only the phones’ signal reports.',
  },
  {
    targets: ['steps'],
    title: 'What the agent is doing',
    body: 'The seven steps every problem goes through: detect, diagnose, test on the digital twin, safety check, your '
      + 'approval (only for large changes), apply, verify. The lit circle is the current step; the sentence below says '
      + 'what it means.',
  },
  {
    targets: ['twin', 'steps'],
    title: 'Tested on the digital twin',
    body: 'The digital twin is a virtual copy of the street. The agent tries possible fixes there first and ranks them by '
      + 'predicted improvement in dB. ✔ marks the fix it chose; ✕ marks fixes the safety check ruled out, with the reason.',
  },
  {
    targets: ['result', 'steps'],
    title: 'Did it work?',
    body: 'After each change the agent measures the real improvement and compares it with the twin’s prediction. If the '
      + 'fix fell well short it is undone automatically and the next one is tried. The AI planner’s reasoning appears here '
      + 'when the language model is on.',
  },
  {
    targets: ['approval', 'panel', 'steps'],
    title: 'Your approval',
    body: 'When a fix passes every safety rule but is larger than the agent may make alone (for example a big power '
      + 'increase), an amber card appears at the top of this panel with Approve and Reject. Even after you approve, the '
      + 'rules are checked once more before anything changes.',
  },
  {
    targets: ['stats-main'],
    title: 'Users with service, users affected',
    body: 'How many of the users currently have service, and how many are affected right now (their signal is clearly '
      + 'worse than their own normal level).',
  },
  {
    targets: ['compare'],
    title: 'With vs without the agent',
    body: 'A hidden copy of the street gets exactly the same problems at the same moments, but has no agent. This box '
      + 'shows how many users would be affected there. The difference is what the agent achieved.',
  },
  {
    targets: ['stats-right'],
    title: 'Agent activity',
    body: 'Users recovered by the agent’s fixes, fixes applied, fixes undone because they did not work well enough, and '
      + 'how many times it asked you.',
  },
  {
    title: 'That’s the whole screen',
    body: 'Next, the incident demo plays one bus incident step by step, with the numbers at each step. Or close this and '
      + 'explore freely.',
  },
]

async function setUpExample() {
  await freshPausedGame()
  await game().addProblem({ kind: 'bus', x: 211, y: 107.8 })
  const ev = (stages: string[]) => {
    const inc = mainIncident()
    return !!inc && game().events.some((e) => e.incident === inc.id && stages.includes(e.stage))
  }
  await stepUntil(() => ev(['verify', 'undo']) || ev(['escalate']), 8)
  const inc = mainIncident()
  if (inc) game().select(inc.id)
  await sleep(200)
}

async function cleanUp() {
  const g = game()
  for (const p of g.frame?.problems ?? []) await g.removeProblem(p.id)
  g.select(null)
  if (g.sessionId) await g.control('resume')
}

export default function Tour() {
  const n = useGame((s) => s.tour)
  const setTour = useGame((s) => s.setTour)
  const setDemo = useGame((s) => s.setDemo)
  const [ready, setReady] = useState(false)
  const step = n !== null ? STEPS[n] : null
  const rect = useTargetRect(step?.targets, [ready])

  useEffect(() => {
    if (n !== 0 || ready) return
    let live = true
    setUpExample().catch((e) => game().notify(String(e), 'error')).finally(() => { if (live) setReady(true) })
    return () => { live = false }
  }, [n, ready])
  useEffect(() => { if (n === null) setReady(false) }, [n])

  if (n === null || !step) return null
  const last = n === STEPS.length - 1
  const close = async () => { setTour(null); await cleanUp() }
  const W = 380
  return (
    <div className="pointer-events-none fixed inset-0 z-50">
      <Highlight rect={rect} />
      <div className="pointer-events-auto absolute rounded-2xl border border-sky-500/50 bg-slate-900 p-5 shadow-2xl"
        style={{ width: W, ...placeNear(rect, W, 260) }}>
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span className="font-semibold uppercase tracking-wider text-sky-300">UI tour · {n + 1} / {STEPS.length}</span>
          <button className="hover:text-slate-200" onClick={() => void close()}>Close ✕</button>
        </div>
        <div className="mt-1.5 h-1 rounded-full bg-slate-800">
          <div className="h-1 rounded-full bg-sky-400 transition-all" style={{ width: `${((n + 1) / STEPS.length) * 100}%` }} />
        </div>
        <h3 className="mt-3 text-lg font-semibold text-slate-50">{step.title}</h3>
        <p className="mt-2 text-[15px] leading-relaxed text-slate-300">{ready ? step.body : 'Setting up an example…'}</p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button className="btn bg-slate-800 text-slate-300 hover:bg-slate-700" disabled={n === 0}
            onClick={() => setTour(n - 1)}>Back</button>
          {last ? (
            <div className="flex gap-2">
              <button className="btn bg-slate-800 hover:bg-slate-700" onClick={() => void close()}>Close</button>
              <button className="btn bg-emerald-500 text-emerald-950 hover:bg-emerald-400"
                onClick={async () => { setTour(null); await cleanUp(); setDemo(true) }}>▶ Incident demo</button>
            </div>
          ) : (
            <button className="btn bg-sky-500 px-5 text-sky-950 hover:bg-sky-400" disabled={!ready}
              onClick={() => setTour(n + 1)}>Next</button>
          )}
        </div>
      </div>
    </div>
  )
}
