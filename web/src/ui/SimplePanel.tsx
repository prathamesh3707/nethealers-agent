import { useMemo, useState } from 'react'
import type { AgentEvent, Incident } from '../api'
import { CAUSE, PLAIN_STEPS, plainAction, plainEvent, plainStepOf } from '../plain'
import { useFocusedIncident, useGame } from '../store'

const NONE: Incident[] = []
const OPEN = (i: Incident) => !['resolved', 'false_alarm'].includes(i.status)

export default function SimplePanel() {
  const main = useFocusedIncident()
  const events = useGame((s) => s.events)
  const incidents = useGame((s) => s.frame?.incidents ?? NONE)
  const mine = useMemo(() => (main ? events.filter((e) => e.incident === main.id) : []), [events, main])
  const minor = incidents.filter((i) => OPEN(i) && i.id !== main?.id && i.status !== 'false_alarm')
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <ApprovalCards />
      {main ? (
        <>
          <WhatHappened incident={main} />
          <StepTrack incident={main} events={mine} />
          <TwinTest events={mine} />
          <Result events={mine} />
          {minor.length > 0 && (
            <p className="px-1 text-xs text-slate-500">
              Also being handled: {minor.length} smaller issue{minor.length > 1 ? 's' : ''} nearby
              ({minor.reduce((a, i) => a + i.phones.length, 0)} users). Switch to Expert for details.
            </p>
          )}
          <Log events={mine} />
        </>
      ) : (
        <AllClear />
      )}
    </div>
  )
}

function Box({ children, className = '', tour }: { children: React.ReactNode; className?: string; tour?: string }) {
  return (
    <section data-tour={tour} className={`rounded-xl border border-slate-800 bg-slate-900/70 p-4 ${className}`}>
      {children}
    </section>
  )
}

function Kicker({ children }: { children: React.ReactNode }) {
  return <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{children}</div>
}

function AllClear() {
  const frame = useGame((s) => s.frame)
  const setTour = useGame((s) => s.setTour)
  const setDemo = useGame((s) => s.setDemo)
  return (
    <Box tour="panel">
      <Kicker>Network status</Kicker>
      <div className="text-xl font-semibold text-emerald-300">No problems right now</div>
      <p className="mt-2 text-[15px] leading-relaxed text-slate-300">
        {frame?.score.good ?? 0} of {frame?.phones.length ?? 0} users have good service. The agent checks every
        user’s signal once a second and steps in when something goes wrong.
      </p>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button className="btn bg-slate-800 py-2 hover:bg-slate-700" onClick={() => setTour(0)}>ⓘ UI tour</button>
        <button className="btn bg-emerald-500 py-2 text-emerald-950 hover:bg-emerald-400" onClick={() => setDemo(true)}>▶ Incident demo</button>
      </div>
      <p className="mt-2 text-center text-xs text-slate-500">or create a problem from the toolbar under the map</p>
    </Box>
  )
}

// ---------------------------------------------------------------- 1. what happened

const STATUS_LABEL: Record<string, [string, string]> = {
  new: ['Working on it', 'text-red-300'],
  verifying: ['Fix applied, checking it', 'text-sky-300'],
  waiting_human: ['Waiting for your approval', 'text-amber-300'],
  escalated: ['Handed to you: no safe fix', 'text-amber-300'],
  fixed: ['Fixed', 'text-emerald-300'],
  closing: ['Cause gone, undoing the fix', 'text-emerald-300'],
  resolved: ['Resolved', 'text-emerald-300'],
}

function WhatHappened({ incident: i }: { incident: Incident }) {
  const cause = CAUSE[i.cause] ?? CAUSE.unknown
  const n = i.phones.length
  const [label, tone] = STATUS_LABEL[i.status] ?? ['', 'text-slate-300']
  return (
    <Box tour="cause">
      <div className="flex items-center justify-between gap-2">
        <Kicker>The problem</Kicker>
        <span className={`text-xs font-semibold ${tone}`}>{label}</span>
      </div>
      <div className="text-lg font-semibold leading-snug text-slate-50">
        {n} user{n === 1 ? '' : 's'} {i.place} lost good service
      </div>
      {i.cause !== 'unknown' && i.cause !== 'none' && (
        <div className="mt-3 flex items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-violet-500/15 text-lg">🩺</div>
          <div>
            <div className="font-semibold text-violet-200">
              {cause.title} <span className="font-normal text-violet-300/80">· {Math.round(i.confidence * 100)}% sure</span>
            </div>
            <p className="text-sm leading-snug text-slate-300">{cause.explain}</p>
          </div>
        </div>
      )}
    </Box>
  )
}

// ---------------------------------------------------------------- 2. what the agent is doing

const STEP_BY_STATUS: Record<string, string> = {
  verifying: 'verify', waiting_human: 'human', escalated: 'human', fixed: 'verify', closing: 'act',
}

function StepTrack({ incident, events }: { incident: Incident; events: AgentEvent[] }) {
  const current = STEP_BY_STATUS[incident.status] ?? plainStepOf(incident.stage)
  const visited = new Set(events.map((e) => plainStepOf(e.stage)))
  const done = !OPEN(incident)
  const step = PLAIN_STEPS.find((s) => s.key === current) ?? PLAIN_STEPS[0]
  const sentence = done ? 'Done. The agent keeps watching in case the problem comes back.'
    : incident.status === 'escalated' ? 'No fix passed every safety check, so the agent changed nothing and asked you to look.'
      : incident.status === 'fixed' ? 'The fix is working. When the cause goes away, the agent will undo its temporary change.'
        : step.doing
  return (
    <Box tour="steps">
      <Kicker>What the agent is doing</Kicker>
      <ol className="flex items-start">
        {PLAIN_STEPS.map((s, n) => {
          const active = s.key === current && !done
          const seen = visited.has(s.key) || done
          return (
            <li key={s.key} className="flex flex-1 flex-col items-center text-center">
              <div className="flex w-full items-center">
                <div className={`h-0.5 flex-1 ${n === 0 ? 'invisible' : seen ? 'bg-sky-600' : 'bg-slate-800'}`} />
                <div className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 text-sm
                  ${active ? (s.key === 'human' ? 'border-amber-400 bg-amber-500/25' : 'border-sky-400 bg-sky-500/25')
                    : seen ? 'border-sky-800 bg-sky-950' : 'border-slate-800 bg-slate-950 opacity-40'}`}>
                  {s.icon}
                </div>
                <div className={`h-0.5 flex-1 ${n === PLAIN_STEPS.length - 1 ? 'invisible' : seen ? 'bg-sky-600' : 'bg-slate-800'}`} />
              </div>
              <div className={`mt-1 text-[10px] leading-tight ${active ? 'font-semibold text-sky-200' : seen ? 'text-slate-400' : 'text-slate-600'}`}>
                {s.label}
              </div>
            </li>
          )
        })}
      </ol>
      <p className="mt-3 text-[15px] leading-relaxed text-slate-200">{sentence}</p>
    </Box>
  )
}

// ---------------------------------------------------------------- 3. the digital-twin test

interface Ranked { action: string; gain_db: number; harmed: number; data_gain?: number }
interface Verdict { action: string; status: string; reasons: string[] }

/**
 * The digital-twin test in rank order. Every option keeps its true rank from the twin, and shows what happened to
 * it: chosen, a safe alternative, blocked by the safety check (and why), or not checked because enough safe
 * options were found higher up. The chosen fix is shown even when it ranked below the top three.
 */
function TwinTest({ events }: { events: AgentEvent[] }) {
  const rounds = events.filter((e) => e.stage === 'rehearse' && e.agent === 'planner')
  const [pick, setPick] = useState<number | null>(null) // null = latest round
  const n = pick !== null && pick < rounds.length ? pick : rounds.length - 1
  const rehearse = rounds[n]
  if (!rehearse) return null
  const after = events.filter((e) => e.tick === rehearse.tick && events.indexOf(e) > events.indexOf(rehearse))
  const ranked = (rehearse.data.ranked as Ranked[] | undefined) ?? []
  const summary = after.find((e) => e.stage === 'check' && Array.isArray(e.data.verdicts))
  const verdicts = new Map(((summary?.data.verdicts as Verdict[] | undefined) ?? []).map((v) => [v.action, v]))
  const shortlist = new Set((summary?.data.shortlist as string[] | undefined) ?? [])
  const decided = after.find((e) => e.stage === 'act' || e.stage === 'plan' || (e.stage === 'escalate' && e.data.action))
  const chosen = String(decided?.data.action ?? '')
  const byAI = after.some((e) => e.stage === 'plan' && e.data.source && !String(e.data.source).startsWith('offline'))
  const tested = Number(rehearse.data.tested ?? ranked.length)

  const top = ranked.slice(0, 3).map((r, i) => ({ r, rank: i + 1 }))
  const chosenRank = ranked.findIndex((r) => r.action === chosen)
  const extra = chosenRank >= 3 ? { r: ranked[chosenRank], rank: chosenRank + 1 } : null

  const status = (r: Ranked) => {
    const v = verdicts.get(r.action)
    if (r.action === chosen) {
      const how = shortlist.size <= 1 ? 'Chosen: the only option that passed the safety check'
        : byAI ? `Chosen: the AI planner picked it from ${shortlist.size} options that passed the safety check`
          : 'Chosen: the highest-ranked option that passed the safety check'
      const waiting = decided?.stage === 'escalate' ? ' (waiting for your approval)' : ''
      return { tone: 'picked', text: how + waiting }
    }
    if (shortlist.has(r.action)) return { tone: 'ok', text: 'Passed the safety check (safe alternative, not chosen)' }
    if (v?.status === 'rejected') return { tone: 'blocked', text: `Blocked by safety check: ${shortReason(v.reasons[0] ?? '')}` }
    if (v) return { tone: 'ok', text: 'Passed the safety check' }
    return { tone: 'muted', text: 'Not checked: enough safe options were found higher up' }
  }

  const row = ({ r, rank }: { r: Ranked; rank: number }) => {
    const st = status(r)
    const style = st.tone === 'picked' ? 'bg-emerald-500/15 text-emerald-100 ring-1 ring-emerald-500/60'
      : st.tone === 'blocked' ? 'bg-slate-950/50 text-slate-500' : 'bg-slate-950/50 text-slate-300'
    const note = st.tone === 'picked' ? 'text-emerald-300/90' : st.tone === 'blocked' ? 'text-amber-300/80' : 'text-slate-500'
    return (
      <li key={r.action} className={`rounded-lg px-3 py-2 text-sm ${style}`}>
        <div className="flex items-start justify-between gap-2">
          <span className="flex items-start gap-2">
            <span className={`mt-px grid h-5 min-w-5 shrink-0 place-items-center rounded-full px-1 text-[11px] font-bold
              ${st.tone === 'picked' ? 'bg-emerald-500 text-emerald-950' : 'bg-slate-700 text-slate-200'}`}>{rank}</span>
            <span>{st.tone === 'picked' ? '✔ ' : st.tone === 'blocked' ? '✕ ' : ''}{plainAction(r.action)}</span>
          </span>
          <span className="shrink-0 text-right text-xs">
            {r.gain_db >= 0 ? '+' : ''}{r.gain_db.toFixed(1)} dB
            <span className="block text-[10px] text-slate-500">{r.harmed ? `${r.harmed} other worse` : 'no one worse'}</span>
          </span>
        </div>
        <div className={`mt-0.5 pl-7 text-xs ${note}`}>{st.text}</div>
      </li>
    )
  }

  return (
    <Box tour="twin">
      <div className="flex items-center justify-between gap-2">
        <Kicker>Tested on the digital twin · ranked best first</Kicker>
        {rounds.length > 1 && (
          <div className="mb-1.5 flex gap-1">
            {rounds.map((r, i) => (
              <button key={i} onClick={() => setPick(i === rounds.length - 1 ? null : i)} title={`Round ${i + 1} at t = ${r.tick} s`}
                className={`chip ${i === n ? 'bg-sky-500 text-sky-950' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}>
                Round {i + 1}
              </button>
            ))}
          </div>
        )}
      </div>
      {rounds.length > 1 && (
        <p className="mb-1 text-xs text-slate-500">
          Round {n + 1} of {rounds.length}, at t = {rehearse.tick} s{n > 0 ? ' (after the previous fix, for the users still affected)' : ''}.
        </p>
      )}
      <p className="mb-3 text-sm text-slate-400">
        {tested} fixes were tried on a virtual copy of the street and ranked by overall benefit: predicted signal gain
        and data-rate gain for the affected users, minus a penalty for every other user made worse. The safety check
        then goes down this list.
      </p>
      <ul className="space-y-1.5">
        {top.map(row)}
        {extra && (
          <>
            {extra.rank > 4 && <li className="pl-3 text-xs text-slate-600">⋮ ranks 4–{extra.rank - 1} not shown</li>}
            {row(extra)}
          </>
        )}
      </ul>
    </Box>
  )
}

export function shortReason(r: string): string {
  if (r.includes('Hospital zone')) return 'would use up the hospital’s reserved capacity'
  if (r.includes('below the')) return 'predicted improvement too small'
  if (r.includes('would hurt')) return 'would make too many other users worse'
  if (r.includes('changed') && r.includes('ago')) return 'this setting was changed too recently'
  if (r.includes('out of date')) return 'signal reports are out of date'
  return r
}

// ---------------------------------------------------------------- 4. did it work

function Result({ events }: { events: AgentEvent[] }) {
  const result = [...events].reverse().find((e) => ['verify', 'undo', 'withdraw'].includes(e.stage))
  const plan = [...events].reverse().find((e) => e.stage === 'plan' && e.data.source && !String(e.data.source).startsWith('offline'))
  if (!result && !plan) return null
  let body: React.ReactNode = null
  if (result?.stage === 'withdraw') {
    body = <div className="text-[15px] text-emerald-200">↺ The cause went away, so the agent removed its temporary fix. The network is back to normal settings.</div>
  } else if (result) {
    const measured = Number(result.data.measured)
    const predicted = Number(result.data.predicted)
    const kept = result.stage === 'verify'
    body = (
      <>
        <div className={`text-[15px] font-semibold ${kept ? 'text-emerald-300' : 'text-amber-300'}`}>
          {kept ? '✔ It worked, so the fix was kept.' : '↶ It fell short, so the agent undid it and tried again.'}
        </div>
        {isFinite(measured) && isFinite(predicted) && (
          <p className="mt-1 text-sm text-slate-300">
            The twin predicted <b>{predicted >= 0 ? '+' : ''}{predicted.toFixed(1)} dB</b>; the real network gave{' '}
            <b>{measured >= 0 ? '+' : ''}{measured.toFixed(1)} dB</b>. Every fix is measured like this, because a twin is never perfect.
          </p>
        )}
      </>
    )
  }
  return (
    <Box tour="result">
      <Kicker>Did it work?</Kicker>
      {body}
      {plan && (
        <p className={`text-sm leading-relaxed text-slate-300 ${body ? 'mt-3 border-t border-slate-800 pt-3' : ''}`}>
          <span className="font-semibold text-indigo-200">AI planner’s reasoning: </span>
          {String(plan.text).replace(/^Planner picked: .*?\. /, '')}
        </p>
      )}
    </Box>
  )
}

function Log({ events }: { events: AgentEvent[] }) {
  const [open, setOpen] = useState(false)
  const lines = events.map((e) => ({ e, text: plainEvent(e) })).filter((l) => l.text)
  if (!lines.length) return null
  return (
    <div className="rounded-xl border border-slate-800">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-900">
        <span>Full timeline ({lines.length} steps)</span><span>{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <ol className="space-y-2 border-t border-slate-800 px-4 py-3">
          {lines.map(({ e, text }, n) => (
            <li key={`${e.tick}-${n}`} className="flex gap-2.5 text-sm leading-snug">
              <span className="w-9 shrink-0 text-right font-mono text-xs text-slate-500">{e.tick}s</span>
              <span className="text-slate-300">{text}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- the operator's decision

function ApprovalCards() {
  const incidents = useGame((s) => s.frame?.incidents ?? NONE)
  const answer = useGame((s) => s.answer)
  const waiting = incidents.filter((i) => i.waiting_for_you)
  if (!waiting.length) return null
  return (
    <>
      {waiting.map((i) => (
        <section key={i.id} data-tour="approval" className="animate-pulse-slow rounded-xl border-2 border-amber-400 bg-amber-950/60 p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">Your decision</div>
          <div className="mt-1 text-lg font-semibold text-amber-50">{plainAction(i.pending ?? '')}?</div>
          <p className="mt-1 text-sm text-amber-100/90">
            It should help {i.phones.length} affected user{i.phones.length === 1 ? '' : 's'}. The agent may not make a
            change this large on its own, so it is asking you.
          </p>
          <div className="mt-3 flex gap-2">
            <button className="btn flex-1 bg-emerald-500 py-2 text-emerald-950 hover:bg-emerald-400" onClick={() => answer(i.id, 'approve')}>Approve</button>
            <button className="btn flex-1 bg-slate-700 py-2 hover:bg-slate-600" onClick={() => answer(i.id, 'reject')}>Reject</button>
          </div>
        </section>
      ))}
    </>
  )
}
