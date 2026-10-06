import { useEffect, useMemo, useState } from 'react'
import type { AgentEvent, Incident } from '../api'
import { CAUSE, plainAction } from '../plain'
import { useGame, type HistoryPoint } from '../store'
import { Highlight, freshPausedGame, game, sleep, stepOnce, useTargetRect } from './Spotlight'

/**
 * Incident demo: one bus incident told as a story. The simulation is paused; every Next advances it to the next thing
 * that happens and explains it with the numbers from this run (users affected, signal in dB, predictions vs results).
 */

const BUS = { kind: 'bus', x: 211, y: 107.8 }

interface Stat { label: string; value: string; tone?: string }
interface Moment {
  key: string
  tick: number
  icon: string
  title: string
  lines: string[]
  stats: Stat[]
  targets?: string[]
  approval?: boolean
}

const db = (v: unknown) => (typeof v === 'number' && isFinite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(1)} dB` : '–')
const dbAbs = (v: unknown) => (typeof v === 'number' && isFinite(v) ? `${v.toFixed(0)} dB` : '–')
const at = (h: HistoryPoint[], t: number) => h.find((p) => p.tick === t) ?? [...h].reverse().find((p) => p.tick <= t)

function affectedStats(h: HistoryPoint[], t: number): Stat[] {
  const p = at(h, t)
  if (!p) return []
  const out: Stat[] = [{ label: 'affected now', value: String(p.degraded), tone: p.degraded ? 'text-red-300' : 'text-emerald-300' }]
  if (p.without !== null) out.push({ label: 'without the agent', value: String(p.without), tone: 'text-slate-300' })
  return out
}

/** Turn the incident's events into story moments. */
function buildMoments(inc: Incident | null, events: AgentEvent[], history: HistoryPoint[], busTick: number,
  leaveTick: number | null): Moment[] {
  const out: Moment[] = []
  const before = at(history, busTick)
  const total = game().frame?.phones.length ?? 60
  out.push({
    key: 'arrive', tick: busTick + 0.1, icon: '🚌', title: 'A bus arrives at the bus stop',
    lines: [
      'A bus parks on Station Road, right between Tower A and the people waiting at the bus stop.',
      '5G at these frequencies travels in narrow beams that a bus body can block almost completely.',
    ],
    stats: [
      { label: 'users before', value: `${total - (before?.degraded ?? 0)}/${total} OK`, tone: 'text-emerald-300' },
      { label: 'a bus blocks about', value: '25 dB' },
    ],
    targets: ['blocker'],
  })
  if (inc) {
    const mine = events.filter((e) => e.incident === inc.id)
    let action = 0
    let pending: string[] = []
    let twin: Moment | null = null
    let lastAct: Moment | null = null
    let first = true
    let lastEsc = -100
    for (const e of mine) {
      const d = e.data as Record<string, unknown>
      // After the bus has gone, only the clean-up matters: skip side checks for stragglers.
      if (leaveTick !== null && e.tick > leaveTick && !['act', 'verify', 'undo', 'withdraw', 'resolve'].includes(e.stage)) continue
      switch (e.stage) {
        case 'detect': {
          if (first) {
            first = false
            const n = (d.phones as number[] | undefined)?.length ?? inc.phones.length
            out.push({
              key: `detect-${e.tick}`, tick: e.tick, icon: '⚠', title: 'Users lose service, and the agent notices',
              lines: [
                `${n} users ${inc.place} lost good service. Their median signal clarity fell from `
                  + `${dbAbs(d.sinr_before)} to ${dbAbs(d.sinr_now)}${typeof d.sinr_now === 'number' && d.sinr_now < 0 ? ', below the 0 dB level where a connection is unusable' : ''}.`,
                `Nobody reported it: the agent watches every phone’s signal reports once a second and flagged the drop `
                  + `${Math.max(1, e.tick - Math.floor(busTick))} s after the bus arrived.`,
              ],
              stats: [
                { label: 'users hit', value: String(n), tone: 'text-red-300' },
                { label: 'signal before', value: dbAbs(d.sinr_before), tone: 'text-emerald-300' },
                { label: 'signal now', value: dbAbs(d.sinr_now), tone: 'text-red-300' },
                { label: 'detected after', value: `${Math.max(1, e.tick - Math.floor(busTick))} s` },
              ],
              targets: ['status'],
            })
          } else {
            pending.push(`${(d.phones as number[] | undefined)?.length ?? 'More'} more users nearby lost service and joined this problem.`)
          }
          break
        }
        case 'diagnose': {
          if (!d.cause) break
          const c = CAUSE[String(d.cause)] ?? CAUSE.unknown
          const probs = Object.entries((d.probs as Record<string, number>) ?? {}).sort((a, b) => b[1] - a[1])
          const evidence = e.text.split(/sure\)\.\s*/)[1] ?? ''
          out.push({
            key: `diag-${e.tick}`, tick: e.tick, icon: '🩺', title: `Diagnosis: ${c.title}`,
            lines: [
              ...pending.splice(0),
              `${c.explain}`,
              evidence ? `Evidence: ${evidence}` : '',
              'The diagnosis model (the pretrained wireless model LWM plus a classifier) only sees the phones’ signal '
                + 'reports; it cannot see the bus. The cause matters because each cause needs a different fix.',
            ].filter(Boolean),
            stats: [
              { label: 'confidence', value: `${Math.round(Number(d.confidence) * 100)}%`, tone: 'text-violet-300' },
              ...(probs[1] ? [{ label: `next guess: ${CAUSE[probs[1][0]]?.title ?? probs[1][0]}`, value: `${Math.round(probs[1][1] * 100)}%` }] : []),
            ],
            targets: ['cause'],
          })
          break
        }
        case 'rehearse': {
          if (e.agent === 'twin') {
            const m = e.text.match(/extra loss on (\d+) tower-phone link/)
            if (m) pending.push(`From the drop pattern alone, the twin inferred an obstacle on ${m[1]} signal paths.`)
            break
          }
          const ranked = (d.ranked as { action: string; gain_db: number; harmed: number }[] | undefined) ?? []
          const n = e.text.match(/Rehearsed (\d+)/)?.[1] ?? String(ranked.length)
          twin = {
            key: `twin-${e.tick}`, tick: e.tick, icon: '🧪', title: 'Testing fixes on the digital twin',
            lines: [
              ...pending.splice(0),
              `Before changing anything real, the agent tried ${n} possible fixes on a virtual copy of the street and `
                + 'ranked them by predicted improvement for the affected users and harm to everyone else. Best:',
              ...ranked.slice(0, 3).map((r, i) => `${i + 1}. ${plainAction(r.action)}: ${db(r.gain_db)}`
                + `${r.harmed ? `, ${r.harmed} other user${r.harmed > 1 ? 's' : ''} worse` : ', nobody else worse'}`),
            ],
            stats: [
              { label: 'fixes tested', value: n },
              { label: 'best predicted', value: db(ranked[0]?.gain_db), tone: 'text-sky-300' },
            ],
            targets: ['twin'],
          }
          out.push(twin)
          break
        }
        case 'check': {
          if (e.text.startsWith('Rejected') && twin && e.tick === twin.tick) {
            const reason = ((d.reasons as string[] | undefined) ?? [])[0] ?? ''
            twin.lines.push(`Ruled out by the safety check: ${plainAction(String(d.action))}, because ${reason}.`)
          }
          if (e.text.startsWith('Re-checked')) pending.push(e.text)
          break
        }
        case 'plan':
          if (d.source && !String(d.source).startsWith('offline')) {
            pending.push(`AI planner: ${e.text.replace(/^Planner picked: .*?\. /, '')}`)
          }
          break
        case 'review':
          if (d.source && !String(d.source).startsWith('offline')) {
            pending.push(e.text.replace('Safety adviser agrees:', 'AI safety review agrees:').replace('Safety adviser objects:', 'AI safety review objects:'))
          }
          break
        case 'escalate': {
          if (e.text.startsWith('Asking a person to approve')) {
            out.push({
              key: `ask-${e.tick}`, tick: e.tick, icon: '🙋', title: 'The agent asks you to approve a change',
              lines: [
                ...pending.splice(0),
                `${plainAction(String(d.action ?? ''))} passed every safety rule, but it is larger than the agent may make `
                  + `alone (${((d.reasons as string[] | undefined) ?? []).join('; ')}). Press Next to approve it.`,
              ],
              stats: affectedStats(history, e.tick), targets: ['approval'], approval: true,
            })
          } else {
            if (e.tick - lastEsc < 5) break // the same hand-over repeated for a few more users
            lastEsc = e.tick
            out.push({
              key: `esc-${e.tick}-${out.length}`, tick: e.tick, icon: '🛡', title: 'No further safe fix: handed to the operator',
              lines: [...pending.splice(0), e.text.replace(/Asking the operator to take over\.?/, 'The agent asks the operator to take over.'),
                'This is deliberate: when no remaining fix passes every safety rule (here, protecting the hospital’s reserved '
                  + 'capacity), the agent changes nothing rather than take a risk.'],
              stats: affectedStats(history, e.tick), targets: ['steps'],
            })
          }
          break
        }
        case 'approve':
          pending.push(e.text.replace('Operator approved', 'You approved').replace('Operator declined', 'You declined') )
          break
        case 'act': {
          action += 1
          lastAct = {
            key: `act-${e.tick}-${action}`, tick: e.tick, icon: '🔧', title: `Action ${action}: ${plainAction(String(d.action ?? ''))}`,
            lines: [
              ...pending.splice(0),
              `It passed every safety check (power and tilt limits, cooldowns, harm to other users, the hospital’s reserve) `
                + `and was applied to the network. The twin predicted ${db(d.predicted)} for the affected users.`,
            ],
            stats: [{ label: 'twin predicted', value: db(d.predicted), tone: 'text-sky-300' }, ...affectedStats(history, e.tick)],
            targets: ['steps'],
          }
          out.push(lastAct)
          break
        }
        case 'verify':
        case 'undo': {
          if (e.stage === 'undo' && e.agent === 'safety') { // the protected-zone guard, not a measurement
            const m = e.text.match(/over its limit \(([\d.]+) > ([\d.]+)\)/)
            out.push({
              key: `guard-${e.tick}`, tick: e.tick, icon: '🛡', title: 'Safety guard: hospital tower over its limit, fix undone at once',
              lines: [
                ...pending.splice(0),
                leaveTick !== null && e.tick > leaveTick
                  ? 'With the bus gone, Tower A’s signal reaches the moved users again and interferes with Tower B, so those '
                    + 'users needed more of Tower B’s capacity than before.'
                  : 'The users moved to Tower B needed more of its capacity than the twin expected.',
                `The hospital’s tower went over its reserved limit${m ? ` (${Math.round(Number(m[1]) * 100)}% used, limit ${Math.round(Number(m[2]) * 100)}%)` : ''}, `
                  + 'so the agent undid the handover immediately, without waiting for its usual 3-second check. Protecting the '
                  + 'hospital outranks everything else.',
              ],
              stats: [
                ...(m ? [{ label: 'hospital tower load', value: `${Math.round(Number(m[1]) * 100)}%`, tone: 'text-red-300' },
                  { label: 'limit', value: `${Math.round(Number(m[2]) * 100)}%` }] : []),
                ...affectedStats(history, e.tick),
              ],
              targets: ['hospital', 'result'],
            })
            break
          }
          const kept = e.stage === 'verify'
          const n = action
          const before = lastAct ? at(history, lastAct.tick)?.degraded : undefined
          const now = at(history, e.tick)?.degraded
          const still = e.text.match(/(\d+) phone\(s\) still poor/)?.[1]
          const why = e.text.match(/Undone, because (.*?)\./)?.[1]
          out.push({
            key: `res-${e.tick}-${n}`, tick: e.tick, icon: kept ? '✅' : '↶',
            title: `Result of action ${n}: ${kept ? 'it worked, kept' : 'fell short, undone'}`,
            lines: [
              ...pending.splice(0),
              `Three seconds later the agent measured the real effect: ${db(d.measured)} against the twin’s ${db(d.predicted)}.`,
              kept ? (still ? `${still} users are still poor, so it looks for another fix for them.` : 'The affected users are healthy again.')
                : `So it was undone automatically (${why ?? 'not enough improvement'}), and the next-best fix is tried.`,
              typeof d.twin_error === 'number' ? `It also updated how far it trusts the twin around this tower (average error now ${(d.twin_error as number).toFixed(1)} dB).` : '',
            ].filter(Boolean),
            stats: [
              { label: 'predicted', value: db(d.predicted), tone: 'text-sky-300' },
              { label: 'measured', value: db(d.measured), tone: kept ? 'text-emerald-300' : 'text-amber-300' },
              ...(before !== undefined && now !== undefined ? [{ label: 'affected', value: `${before} → ${now}`, tone: now < before ? 'text-emerald-300' : 'text-slate-200' }] : []),
              ...affectedStats(history, e.tick).slice(1),
            ],
            targets: ['result'],
          })
          break
        }
        case 'withdraw':
          out.push({
            key: `wd-${e.tick}`, tick: e.tick, icon: '↺', title: 'Cause gone: the temporary fix is removed',
            lines: [...pending.splice(0), 'The original signal from Tower A came back, so the agent returned the network '
              + 'to its normal settings. It does not leave temporary changes in place once they are no longer needed.'],
            stats: affectedStats(history, e.tick), targets: ['result'],
          })
          break
        case 'resolve':
          out.push({
            key: `rs-${e.tick}`, tick: e.tick, icon: '✓', title: 'Problem closed',
            lines: [...pending.splice(0), e.text], stats: affectedStats(history, e.tick), targets: ['stats-main'],
          })
          break
      }
    }
    if (pending.length && out.length) out[out.length - 1].lines.push(...pending)
  }
  if (leaveTick !== null) {
    out.push({
      key: 'leave', tick: leaveTick + 0.5, icon: '🚌', title: 'The bus drives away',
      lines: [`The bus stood at the stop for ${leaveTick - Math.floor(busTick)} s. Throughout, the agent kept the affected `
        + 'users lower than on the street without it. Now the bus leaves: watch what the agent does with the changes it made.'],
      stats: affectedStats(history, leaveTick), targets: ['blocker', 'map'],
    })
  }
  return out.sort((a, b) => a.tick - b.tick)
}

function summary(history: HistoryPoint[], events: AgentEvent[], inc: Incident | null, busTick: number,
  leaveTick: number | null): Moment {
  // the incident itself: from the bus arriving until a few seconds after it left
  const end = leaveTick !== null ? leaveTick + 5 : Infinity
  const span = history.filter((h) => h.tick > busTick && h.tick <= end)
  const withA = span.reduce((a, h) => a + h.degraded, 0)
  const without = span.reduce((a, h) => a + (h.without ?? 0), 0)
  const peak = Math.max(0, ...span.map((h) => h.degraded))
  const mine = events.filter((e) => e.incident === inc?.id)
  const acts = mine.filter((e) => e.stage === 'act').length
  const undone = mine.filter((e) => e.stage === 'undo').length
  const best = Math.max(...mine.filter((e) => e.stage === 'verify').map((e) => Number(e.data.measured)), -Infinity)
  const saved = without > 0 ? Math.round((1 - withA / without) * 100) : 0
  return {
    key: 'summary', tick: Infinity, icon: '📊', title: 'Summary of this incident',
    lines: [
      `Over ${span.length} seconds, users were affected for ${withA} user-seconds with the agent, against ${without} on `
        + `the identical street without it${saved > 0 ? `: ${saved}% less disruption` : ''}.`,
      `${acts} fix${acts === 1 ? '' : 'es'} applied, ${undone} undone automatically. Every change was tested on the twin `
        + 'first, checked against hard safety limits, and measured afterwards.',
      'Now try it yourself: place a bus, truck or crowd anywhere and move it with ◀ ▶, or open the UI tour.',
    ],
    stats: [
      { label: 'peak affected', value: String(peak), tone: 'text-red-300' },
      { label: 'user-seconds: agent', value: String(withA), tone: 'text-emerald-300' },
      { label: 'without agent', value: String(without), tone: 'text-red-300' },
      ...(isFinite(best) ? [{ label: 'best fix measured', value: db(best), tone: 'text-emerald-300' }] : []),
    ],
    targets: ['compare'],
  }
}

export default function Demo() {
  const on = useGame((s) => s.demo)
  const setDemo = useGame((s) => s.setDemo)
  const events = useGame((s) => s.events)
  const history = useGame((s) => s.history)
  const frame = useGame((s) => s.frame)
  const [busTick, setBusTick] = useState<number | null>(null)
  const [leaveTick, setLeaveTick] = useState<number | null>(null)
  const [incId, setIncId] = useState<string | null>(null)
  const [shown, setShown] = useState(0)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  // the bus incident: the biggest problem that opened after the bus arrived
  const inc = useMemo(() => {
    const incs = frame?.incidents ?? []
    if (incId) return incs.find((i) => i.id === incId) ?? null
    return null
  }, [frame, incId])

  const moments = useMemo(() => {
    if (busTick === null) return []
    const m = buildMoments(inc, events, history, busTick, leaveTick)
    return done ? [...m, summary(history, events, inc, busTick, leaveTick)] : m
  }, [inc, events, history, busTick, leaveTick, done])

  // start: fresh paused game, bus parked
  useEffect(() => {
    if (!on) { setBusTick(null); setLeaveTick(null); setIncId(null); setShown(0); setDone(false); return }
    let live = true
    setBusy(true)
    ;(async () => {
      await freshPausedGame()
      const t = game().frame?.tick ?? 0
      await game().addProblem(BUS)
      await sleep(150)
      if (live) setBusTick(t)
    })().catch((e) => game().notify(String(e), 'error')).finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [on])

  const current = moments[Math.min(shown, moments.length - 1)]
  const rect = useTargetRect(current?.targets, [shown, moments.length])
  if (!on) return null

  const pickIncident = () => {
    if (incId || busTick === null) return
    const big = (game().frame?.incidents ?? []).filter((i) => i.opened > busTick && i.status !== 'false_alarm')
      .sort((a, b) => b.phones.length - a.phones.length)[0]
    if (big) { setIncId(big.id); game().select(big.id) }
  }

  /** Step the simulation until at least one new moment appears. */
  const advance = async () => {
    const count = () => {
      const incs = game().frame?.incidents ?? []
      const i = incId ? incs.find((x) => x.id === incId) ?? null
        : incs.filter((x) => x.opened > (busTick ?? 0) && x.status !== 'false_alarm').sort((a, b) => b.phones.length - a.phones.length)[0] ?? null
      return buildMoments(i, game().events, game().history, busTick ?? 0, leaveTick).length
    }
    const start = count()
    for (let k = 0; k < 12 && count() <= start; k++) {
      await stepOnce()
      pickIncident()
    }
    return count() > start
  }

  const stable = !!inc && ['fixed', 'escalated', 'resolved'].includes(inc.status)
  const busOnStreet = !!frame?.problems.some((p) => p.kind === 'bus')
  const atEnd = shown >= moments.length - 1

  let label = 'Next'
  if (current?.approval && atEnd) label = 'Approve and continue'
  else if (atEnd && done) label = 'Finish'
  else if (atEnd && stable && busOnStreet && leaveTick === null) label = 'Next: the bus leaves'
  else if (atEnd && leaveTick !== null && !busOnStreet && inc?.status === 'resolved') label = 'Show summary'

  const next = async () => {
    if (!atEnd) { setShown(shown + 1); return }
    setBusy(true)
    try {
      if (done) { setDemo(false); await game().control('resume'); return }
      if (current?.approval && inc?.waiting_for_you) {
        await game().answer(inc.id, 'approve')
        await sleep(100)
      }
      if (label === 'Next: the bus leaves') {
        for (let k = 0; k < 8; k++) await stepOnce() // let the steady state show before the bus leaves
        const bus = game().frame?.problems.find((p) => p.kind === 'bus')
        setLeaveTick(game().frame?.tick ?? 0)
        if (bus) await game().sendAway(bus.id)
        await sleep(100)
        setShown(shown + 1)
        return
      }
      if (label === 'Show summary') { setDone(true); setShown(shown + 1); return }
      const grew = await advance()
      if (grew) setShown(shown + 1)
      else if (leaveTick !== null) { setDone(true); setShown(shown + 1) }
    } finally {
      setBusy(false)
    }
  }

  const W = 430
  return (
    <div className="pointer-events-none fixed inset-0 z-50">
      <Highlight rect={rect} dim={false} />
      <div className="pointer-events-auto absolute left-3 top-[104px] flex max-h-[calc(100vh-220px)] flex-col rounded-2xl border border-emerald-500/40 bg-slate-900/95 shadow-2xl backdrop-blur"
        style={{ width: W }}>
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2 text-[11px]">
          <span className="font-semibold uppercase tracking-wider text-emerald-300">Incident demo · simulation paused</span>
          <button className="text-slate-400 hover:text-slate-200" onClick={async () => { setDemo(false); await game().control('resume') }}>Exit ✕</button>
        </div>
        {/* timeline of moments so far */}
        <ol className="flex flex-wrap gap-1 border-b border-slate-800 px-4 py-2">
          {moments.map((m, i) => (
            <li key={m.key}>
              <button onClick={() => setShown(i)} title={m.title}
                className={`grid h-7 w-7 place-items-center rounded-full text-xs ${i === shown ? 'bg-emerald-500 text-emerald-950'
                  : i < shown ? 'bg-slate-700 text-slate-200' : 'bg-slate-800 text-slate-500'}`}>
                {m.icon}
              </button>
            </li>
          ))}
        </ol>
        <div className="min-h-0 overflow-y-auto px-4 py-3">
          {!current || busTick === null ? (
            <p className="text-sm text-slate-300">Setting up the street…</p>
          ) : (
            <>
              <div className="text-[11px] text-slate-500">
                {isFinite(current.tick) ? `t = ${Math.floor(current.tick)} s` : 'end'} · step {Math.min(shown, moments.length - 1) + 1}
              </div>
              <h3 className="mt-0.5 text-lg font-semibold leading-snug text-slate-50">{current.icon} {current.title}</h3>
              {current.stats.length > 0 && (
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {current.stats.map((s) => (
                    <div key={s.label} className="rounded-lg bg-slate-950/70 px-3 py-2">
                      <div className={`font-mono text-lg ${s.tone ?? 'text-slate-100'}`}>{s.value}</div>
                      <div className="text-[11px] leading-tight text-slate-400">{s.label}</div>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-3 space-y-2">
                {current.lines.map((l, i) => <p key={i} className="text-[14px] leading-relaxed text-slate-300">{l}</p>)}
              </div>
            </>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-slate-800 px-4 py-3">
          <button className="btn bg-slate-800 text-slate-300 hover:bg-slate-700" disabled={busy || shown === 0}
            onClick={() => setShown(Math.max(0, shown - 1))}>Back</button>
          <button className="btn bg-emerald-500 px-5 text-emerald-950 hover:bg-emerald-400" disabled={busy || busTick === null}
            onClick={() => void next()}>
            {busy ? 'Simulating…' : label}
          </button>
        </div>
      </div>
    </div>
  )
}
