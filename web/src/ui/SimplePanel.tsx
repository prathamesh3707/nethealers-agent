import { useMemo, useState } from 'react'
import type { AgentEvent, Incident } from '../api'
import { CAUSE, PLAIN_STEPS, plainAction, plainEvent, plainStepOf } from '../plain'
import { useFocusedIncident, useGame } from '../store'
import IncidentActions from './IncidentActions'

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
          <IncidentActions incidentId={main.id} />
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

interface Ranked { action: string; gain_db: number; harmed: number; data_gain?: number; tried?: number | null; score?: number }
interface Verdict { action: string; status: string; reasons: string[] }

const ORDINAL = (n: number) => `${n}${n % 10 === 1 && n % 100 !== 11 ? 'st' : n % 10 === 2 && n % 100 !== 12 ? 'nd' : n % 10 === 3 && n % 100 !== 13 ? 'rd' : 'th'}`

/**
 * The whole digital-twin step, in the order it happened: candidate fixes for the diagnosed cause are tried on the
 * twin, ranked, then safety-checked from the top until enough pass, and one is picked. Every fix is listed with its
 * rank, the order it was tried, the twin's prediction, and what the safety check said (or that it wasn't needed).
 */
function TwinTest({ events }: { events: AgentEvent[] }) {
  const rounds = events.filter((e) => e.stage === 'rehearse' && e.agent === 'planner')
  const [pick, setPick] = useState<number | null>(null) // null = latest round
  const [order, setOrder] = useState<'rank' | 'tried'>('rank')
  const n = pick !== null && pick < rounds.length ? pick : rounds.length - 1
  const rehearse = rounds[n]
  if (!rehearse) return null
  const idx = events.indexOf(rehearse)
  const after = events.filter((e, i) => i > idx && e.tick === rehearse.tick)
  const ranked = ((rehearse.data.ranked as Ranked[] | undefined) ?? []).map((r, i) => ({ ...r, rank: i + 1 }))
  const summary = after.find((e) => e.stage === 'check' && Array.isArray(e.data.verdicts))
  const verdictList = (summary?.data.verdicts as Verdict[] | undefined) ?? []
  const checkedAt = new Map(verdictList.map((v, i) => [v.action, { ...v, at: i + 1 }]))
  const shortlist = new Set((summary?.data.shortlist as string[] | undefined) ?? [])
  const decided = after.find((e) => e.stage === 'act' || e.stage === 'plan' || (e.stage === 'escalate' && e.data.action))
  const chosen = String(decided?.data.action ?? '')
  const byAI = after.some((e) => e.stage === 'plan' && e.data.source && !String(e.data.source).startsWith('offline'))
  const waiting = decided?.stage === 'escalate'
  const tested = Number(rehearse.data.tested ?? ranked.length)
  const cause = CAUSE[String(rehearse.data.cause ?? '')]?.title
  const rows = order === 'rank' ? ranked : [...ranked].sort((a, b) => (a.tried ?? 99) - (b.tried ?? 99))

  const pipeline = [
    { n: tested, label: 'fixes generated', sub: cause ? `for “${cause}”` : 'for this cause' },
    { n: tested, label: 'tested on the twin', sub: 'predicted dB each' },
    { n: tested, label: 'ranked', sub: 'best first' },
    { n: verdictList.length, label: 'safety-checked', sub: `from the top, ${shortlist.size} passed` },
    { n: chosen ? 1 : 0, label: 'picked', sub: !chosen ? 'none: handed to you' : byAI ? 'by the AI planner' : 'top safe one' },
  ]

  return (
    <Box tour="twin">
      <div className="flex flex-wrap items-center justify-between gap-x-2">
        <Kicker>Digital twin: every fix it tried</Kicker>
        {rounds.length > 1 && (
          // A stepper rather than one button per round: it stays the same width however many rounds there are.
          <div className="mb-1.5 flex shrink-0 items-center gap-1">
            <button onClick={() => setPick(Math.max(0, n - 1))} disabled={n === 0} aria-label="Previous round"
              className="chip bg-slate-800 text-slate-300 hover:text-slate-100 disabled:cursor-default disabled:opacity-40">
              ◀
            </button>
            <span className="chip bg-sky-500 tabular-nums text-sky-950" title={`Round ${n + 1} at t = ${rehearse.tick} s`}>
              Round {n + 1} / {rounds.length}
            </span>
            <button onClick={() => setPick(n + 1 >= rounds.length - 1 ? null : n + 1)} disabled={n >= rounds.length - 1}
              aria-label="Next round"
              className="chip bg-slate-800 text-slate-300 hover:text-slate-100 disabled:cursor-default disabled:opacity-40">
              ▶
            </button>
            {pick !== null && (
              <button onClick={() => setPick(null)} className="chip bg-slate-800 text-sky-300 hover:text-sky-200">
                Latest
              </button>
            )}
          </div>
        )}
      </div>
      {rounds.length > 1 && (
        <p className="mb-2 text-xs text-slate-500">
          Round {n + 1} of {rounds.length}, at t = {rehearse.tick} s{n > 0 ? ', for the users still affected after the previous fix' : ''}.
        </p>
      )}

      {/* the pipeline, left to right */}
      <ol className="mb-3 grid grid-cols-5 gap-1 text-center">
        {pipeline.map((p, i) => (
          <li key={p.label} className="relative rounded-lg bg-slate-950/60 px-1 py-1.5">
            <div className="font-mono text-base text-slate-100">{p.n}</div>
            <div className="text-[10px] font-semibold leading-tight text-slate-300">{i + 1}. {p.label}</div>
            <div className="text-[9px] leading-tight text-slate-500">{p.sub}</div>
          </li>
        ))}
      </ol>
      <p className="mb-2 text-xs leading-relaxed text-slate-400">
        Each fix gets a score: predicted signal gain (dB) and data-rate gain for the affected users, minus 3 points for
        every other user made clearly worse, minus a penalty if everyone else’s average signal drops. Fixes are ranked by
        that score. The safety check then works down the ranking and stops once it has {byAI ? 'up to 4 safe options for the AI planner' : 'one safe option'}.
      </p>

      <div className="mb-1.5 flex items-center gap-1 text-[11px]">
        <span className="text-slate-500">Order:</span>
        {(['rank', 'tried'] as const).map((o) => (
          <button key={o} onClick={() => setOrder(o)}
            className={`chip ${order === o ? 'bg-slate-600 text-slate-50' : 'bg-slate-800 text-slate-400 hover:text-slate-200'}`}>
            {o === 'rank' ? 'by rank' : 'as tried on the twin'}
          </button>
        ))}
      </div>

      <ul className="space-y-1">
        {rows.map((r) => {
          const v = checkedAt.get(r.action)
          const picked = r.action === chosen
          let tone = 'muted'
          let verdict = 'Not safety-checked: enough safe options were found higher up'
          if (picked) {
            tone = 'picked'
            verdict = `Chosen${shortlist.size <= 1 ? ': the only option that passed' : byAI ? ` by the AI planner from ${shortlist.size} that passed` : ': the highest-ranked that passed'}${waiting ? ' · waiting for your approval' : ''}`
          } else if (v?.status === 'rejected') { tone = 'blocked'; verdict = `Blocked: ${shortReason(v.reasons[0] ?? '')}` }
          else if (shortlist.has(r.action)) { tone = 'ok'; verdict = 'Passed: safe alternative, not chosen' }
          else if (v) { tone = 'ok'; verdict = 'Passed' }
          return (
            <li key={r.action} className={`rounded-md px-2 py-1.5 text-[13px] ${tone === 'picked' ? 'bg-emerald-500/15 ring-1 ring-emerald-500/60'
              : tone === 'blocked' ? 'bg-slate-950/40' : tone === 'ok' ? 'bg-sky-950/40' : 'bg-slate-950/25'}`}>
              <div className="flex items-start justify-between gap-2">
                <span className="flex items-start gap-1.5">
                  <span className={`mt-px grid h-5 min-w-5 shrink-0 place-items-center rounded-full px-1 text-[10px] font-bold
                    ${tone === 'picked' ? 'bg-emerald-500 text-emerald-950' : 'bg-slate-700 text-slate-200'}`}>{r.rank}</span>
                  <span className={tone === 'picked' ? 'text-emerald-100' : tone === 'muted' ? 'text-slate-400' : tone === 'blocked' ? 'text-slate-400' : 'text-slate-200'}>
                    {plainAction(r.action)}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-xs text-slate-300">{r.gain_db >= 0 ? '+' : ''}{r.gain_db.toFixed(1)} dB</span>
              </div>
              <div className="mt-0.5 flex flex-wrap gap-x-2 pl-[26px] text-[11px] text-slate-500">
                {r.tried ? <span>tried {ORDINAL(r.tried)}</span> : null}
                <span>{r.harmed ? `${r.harmed} other user${r.harmed > 1 ? 's' : ''} worse` : 'no one else worse'}</span>
                {v && <span>checked {ORDINAL(v.at)}</span>}
                {typeof r.score === 'number' && <span className="text-slate-400">score {r.score.toFixed(1)}</span>}
              </div>
              <div className={`pl-[26px] text-[11px] ${tone === 'picked' ? 'text-emerald-300' : tone === 'blocked' ? 'text-amber-300/80' : tone === 'ok' ? 'text-sky-300' : 'text-slate-600'}`}>
                {tone === 'picked' ? '✔ ' : tone === 'blocked' ? '✕ ' : tone === 'ok' ? '✓ ' : ''}{verdict}
              </div>
            </li>
          )
        })}
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
