import { useMemo, useState } from 'react'
import type { AgentEvent, Incident } from '../api'
import { CAUSE, PLAIN_STEPS, incidentHeadline, plainAction, plainEvent, plainStepOf } from '../plain'
import { ms } from '../stages'
import { useFocusedIncident, useGame } from '../store'

const NONE: Incident[] = []
const OPEN = (i: Incident) => !['resolved', 'false_alarm'].includes(i.status)

/** The side panel for first-time viewers: what is wrong, what the agent is doing, and what it needs from you. */
export default function SimplePanel() {
  const focus = useFocusedIncident()
  const events = useGame((s) => s.events)
  const mine = useMemo(() => (focus ? events.filter((e) => e.incident === focus.id) : []), [events, focus])
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <ApprovalCards />
      <IncidentPicker />
      {focus ? (
        <>
          <Situation incident={focus} />
          <StepTrack incident={focus} events={mine} />
          <Practice incident={focus} events={mine} />
          <Outcome incident={focus} events={mine} />
          <Story events={mine} />
        </>
      ) : (
        <AllClear />
      )}
    </div>
  )
}

function Box({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-slate-800 bg-slate-900/70 p-4 ${className}`}>{children}</section>
}

function Kicker({ children }: { children: React.ReactNode }) {
  return <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{children}</div>
}

function AllClear() {
  const frame = useGame((s) => s.frame)
  const total = frame?.phones.length ?? 0
  const good = frame?.score.good ?? 0
  return (
    <Box>
      <Kicker>Network status</Kicker>
      <div className="text-xl font-semibold text-emerald-300">All users are being watched</div>
      <p className="mt-2 text-[15px] leading-relaxed text-slate-300">
        {good} of {total} users have good service. Every second the agent checks each user’s signal, ready to
        diagnose and fix a problem on its own, within safety limits.
      </p>
      <p className="mt-3 text-sm text-slate-400">
        To see it in action, choose a <b className="text-slate-200">ready-made scenario</b> under the map, or pick a
        problem (bus, truck, crowd…) and click on the street.
      </p>
    </Box>
  )
}

function IncidentPicker() {
  const incidents = useGame((s) => s.frame?.incidents ?? NONE)
  const selected = useGame((s) => s.selected)
  const select = useGame((s) => s.select)
  const shown = incidents.filter((i) => i.status !== 'false_alarm').slice(-6)
  if (shown.length < 2) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-slate-500">Problems:</span>
      <button onClick={() => select(null)}
        className={`chip ${selected === null ? 'bg-sky-500 text-sky-950' : 'bg-slate-800 text-slate-300'}`}>latest</button>
      {shown.map((i) => (
        <button key={i.id} onClick={() => select(i.id)}
          className={`chip ${selected === i.id ? 'bg-sky-500 text-sky-950' : OPEN(i) ? 'bg-slate-700 text-slate-100' : 'bg-slate-800/60 text-slate-500'}`}>
          {OPEN(i) ? '● ' : '✓ '}#{Number(i.id.replace('INC-', ''))} {CAUSE[i.cause]?.title.split(' ')[0] ?? i.cause}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- what is wrong

function Situation({ incident: i }: { incident: Incident }) {
  const cause = CAUSE[i.cause] ?? CAUSE.unknown
  const open = OPEN(i)
  const conf = Math.round(i.confidence * 100)
  return (
    <Box className={open ? 'border-red-500/40' : 'border-emerald-600/40'}>
      <Kicker>{open ? 'What went wrong' : 'What happened'}</Kicker>
      <div className="text-[17px] font-semibold leading-snug text-slate-50">{incidentHeadline(i)}</div>
      {i.cause !== 'unknown' && i.cause !== 'none' && (
        <div className="mt-3 rounded-lg bg-slate-950/60 p-3">
          <div className="flex items-baseline justify-between gap-2">
            <div className="font-semibold text-violet-200">Cause: {cause.title}</div>
            <div className="text-xs text-violet-300">{conf}% confidence</div>
          </div>
          <div className="mt-1.5 h-1.5 rounded-full bg-slate-800">
            <div className="h-1.5 rounded-full bg-violet-400" style={{ width: `${conf}%` }} />
          </div>
          <p className="mt-2 text-sm text-slate-300">{cause.explain}</p>
          <p className="mt-1 text-xs text-slate-500">Diagnosed by the AI model from the users’ signal reports alone; it can’t see the street.</p>
        </div>
      )}
    </Box>
  )
}

// ---------------------------------------------------------------- what the agent is doing

function StepTrack({ incident, events }: { incident: Incident; events: AgentEvent[] }) {
  // Follow the incident's state; its latest event can be an unrelated "more users joined" note.
  const byStatus: Record<string, string> = { verifying: 'verify', waiting_human: 'human', escalated: 'human',
    fixed: 'verify', closing: 'act' }
  const current = byStatus[incident.status] ?? plainStepOf(incident.stage)
  const visited = new Set(events.map((e) => plainStepOf(e.stage)))
  const needsYou = incident.status === 'waiting_human'
  const done = !OPEN(incident)
  const step = PLAIN_STEPS.find((s) => s.key === current) ?? PLAIN_STEPS[0]
  const lastTick = events[events.length - 1]?.tick
  const spent = events.filter((e) => e.tick === lastTick).reduce((a, e) => a + e.ms, 0)
  return (
    <Box>
      <Kicker>What the agent is doing</Kicker>
      <ol className="flex items-start justify-between">
        {PLAIN_STEPS.map((s, n) => {
          const active = s.key === current && !done
          const seen = visited.has(s.key)
          const skipped = s.key === 'human' && !seen
          return (
            <li key={s.key} className="flex flex-1 flex-col items-center text-center">
              <div className="flex w-full items-center">
                <div className={`h-0.5 flex-1 ${n === 0 ? 'invisible' : seen ? 'bg-sky-500/60' : 'bg-slate-800'}`} />
                <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border-2 text-base transition-all
                  ${active ? 'scale-110 border-sky-400 bg-sky-500/25 shadow-[0_0_16px_rgba(56,189,248,0.6)]'
                    : seen ? 'border-sky-700 bg-sky-950' : 'border-slate-800 bg-slate-950 opacity-50'}
                  ${active && s.key === 'human' ? 'animate-pulse border-amber-400 bg-amber-500/25' : ''}`}>
                  {s.icon}
                </div>
                <div className={`h-0.5 flex-1 ${n === PLAIN_STEPS.length - 1 ? 'invisible' : seen ? 'bg-sky-500/60' : 'bg-slate-800'}`} />
              </div>
              <div className={`mt-1 text-[10px] leading-tight ${active ? 'font-semibold text-sky-200' : seen ? 'text-slate-300' : 'text-slate-600'}`}>
                {s.label}{skipped ? '' : ''}
              </div>
            </li>
          )
        })}
      </ol>
      <div className={`mt-3 rounded-lg p-3 text-[15px] leading-relaxed ${needsYou ? 'bg-amber-950/50 text-amber-100' : 'bg-slate-950/60 text-slate-200'}`}>
        {done ? '✓ Finished. The agent keeps watching in case the problem returns.'
          : incident.status === 'escalated' ? 'No fix passed every safety check, so the agent changed nothing and handed this to you. It keeps watching and closes the problem when users recover.'
          : incident.status === 'fixed' ? 'The fix worked and is in place. If the cause goes away (the bus leaves), the agent will undo its temporary change.'
          : step.doing}
      </div>
      {spent > 0 && (
        <div className="mt-2 text-xs text-slate-500">
          Its latest round of thinking took <b className="text-slate-300">{ms(spent)}</b>
          {incident.decision_ms > 0 && <> · total for this problem {ms(incident.decision_ms)}</>}
        </div>
      )}
    </Box>
  )
}

interface Ranked { action: string; gain_db: number; harmed: number }

/** The digital-twin rehearsal as a few readable cards: what was tried, what was picked, what was ruled out. */
function Practice({ events }: { incident: Incident; events: AgentEvent[] }) {
  const rehearse = [...events].reverse().find((e) => e.stage === 'rehearse' && e.agent === 'planner')
  if (!rehearse) return null
  const after = events.filter((e) => e.tick >= rehearse.tick)
  const ranked = ((rehearse.data.ranked as Ranked[] | undefined) ?? []).slice(0, 4)
  const rejected = new Map(after.filter((e) => e.stage === 'check' && e.text.startsWith('Rejected'))
    .map((e) => [String(e.data.action), ((e.data.reasons as string[] | undefined) ?? [])[0] ?? '']))
  const chosen = String(after.find((e) => e.stage === 'act' || e.stage === 'escalate' || e.stage === 'plan')?.data.action ?? '')
  const best = Math.max(1, ...ranked.map((r) => r.gain_db))
  return (
    <Box>
      <Kicker>Tested on the digital twin first</Kicker>
      <p className="mb-3 text-sm text-slate-400">
        Before changing anything real, the agent tried {String(rehearse.text.match(/Rehearsed (\d+)/)?.[1] ?? 'several')} possible
        fixes on a virtual copy of the street. The best ones:
      </p>
      <div className="space-y-2">
        {ranked.map((r) => {
          const why = rejected.get(r.action)
          const picked = r.action === chosen
          return (
            <div key={r.action} className={`rounded-lg border p-2.5 ${picked ? 'border-emerald-500/70 bg-emerald-950/40'
              : why ? 'border-slate-800 bg-slate-950/40 opacity-70' : 'border-slate-800 bg-slate-950/40'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className={`text-sm font-medium ${picked ? 'text-emerald-200' : 'text-slate-200'}`}>
                  {picked ? '✔ ' : why ? '✕ ' : ''}{plainAction(r.action)}
                </div>
                {picked && <span className="chip bg-emerald-500 text-emerald-950">chosen</span>}
              </div>
              <div className="mt-1.5 flex items-center gap-2 text-xs text-slate-400">
                <span className="w-20 shrink-0">predicted help</span>
                <div className="h-1.5 flex-1 rounded-full bg-slate-800">
                  <div className="h-1.5 rounded-full bg-sky-400" style={{ width: `${Math.max(3, (Math.max(0, r.gain_db) / best) * 100)}%` }} />
                </div>
                <span className="w-24 text-right">{r.harmed ? `${r.harmed} other user${r.harmed > 1 ? 's' : ''} worse` : 'no one worse'}</span>
              </div>
              {why && <div className="mt-1 text-xs text-amber-300/90">Ruled out by safety check: {why}</div>}
            </div>
          )
        })}
      </div>
    </Box>
  )
}

/** The latest result: predicted vs real, kept or undone, and the AI's explanation if it gave one. */
function Outcome({ events }: { incident: Incident; events: AgentEvent[] }) {
  const result = [...events].reverse().find((e) => e.stage === 'verify' || e.stage === 'undo' || e.stage === 'withdraw')
  const plan = [...events].reverse().find((e) => e.stage === 'plan' && e.data.source && !String(e.data.source).startsWith('offline'))
  const review = [...events].reverse().find((e) => e.stage === 'review' && e.data.source && !String(e.data.source).startsWith('offline'))
  if (!result && !plan) return null
  return (
    <Box>
      {result && <ResultLine e={result} />}
      {plan && (
        <div className={result ? 'mt-3 border-t border-slate-800 pt-3' : ''}>
          <Kicker>Why this fix (AI planner)</Kicker>
          <p className="text-sm leading-relaxed text-slate-200">{String(plan.text).replace(/^Planner picked: .*?\. /, '')}</p>
          {review && (
            <p className="mt-2 text-sm leading-relaxed text-slate-300">
              <span className="font-semibold text-slate-200">AI safety review: </span>
              {review.text.replace(/^Safety adviser (agrees|objects): /, '')}
            </p>
          )}
        </div>
      )}
    </Box>
  )
}

function ResultLine({ e }: { e: AgentEvent }) {
  if (e.stage === 'withdraw') {
    return (
      <>
        <Kicker>Result</Kicker>
        <div className="text-[15px] text-emerald-200">↺ The cause went away, so the temporary fix was removed and the network is back to its normal settings.</div>
      </>
    )
  }
  const measured = Number(e.data.measured)
  const predicted = Number(e.data.predicted)
  const kept = e.stage === 'verify'
  const scale = Math.max(1, Math.abs(measured), Math.abs(predicted))
  return (
    <>
      <Kicker>Reality check</Kicker>
      <div className={`text-[15px] font-semibold ${kept ? 'text-emerald-300' : 'text-amber-300'}`}>
        {kept ? '✔ The fix worked and was kept.' : '↶ The fix fell short, so the agent undid it automatically.'}
      </div>
      {isFinite(measured) && isFinite(predicted) && (
        <div className="mt-2 space-y-1.5 text-xs">
          <Bar label="Twin predicted" v={predicted} scale={scale} color="bg-sky-400" />
          <Bar label="Real result" v={measured} scale={scale} color={kept ? 'bg-emerald-400' : 'bg-amber-400'} />
          <p className="pt-1 text-slate-500">Signal improvement in dB for the affected users. A twin is never perfect, which is why every fix is measured afterwards.</p>
        </div>
      )}
    </>
  )
}

function Bar({ label, v, scale, color }: { label: string; v: number; scale: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-24 text-slate-400">{label}</span>
      <div className="h-2 flex-1 rounded-full bg-slate-800">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${Math.max(2, (Math.max(0, v) / scale) * 100)}%` }} />
      </div>
      <span className="w-14 text-right font-mono text-slate-300">{v >= 0 ? '+' : ''}{v.toFixed(1)} dB</span>
    </div>
  )
}

function Story({ events }: { events: AgentEvent[] }) {
  const [all, setAll] = useState(false)
  const lines = events.map((e) => ({ e, text: plainEvent(e) })).filter((l) => l.text)
  const shown = all ? lines : lines.slice(-7)
  if (!lines.length) return null
  return (
    <Box>
      <div className="flex items-center justify-between">
        <Kicker>Step by step</Kicker>
        {lines.length > 7 && (
          <button className="text-xs text-sky-400 hover:underline" onClick={() => setAll(!all)}>
            {all ? 'show latest' : `show all ${lines.length}`}
          </button>
        )}
      </div>
      <ol className="mt-1 space-y-2">
        {shown.map(({ e, text }, n) => (
          <li key={`${e.tick}-${n}`} className="flex gap-2.5 text-sm leading-snug">
            <span className="w-9 shrink-0 pt-px text-right font-mono text-xs text-slate-500">{e.tick}s</span>
            <span className="text-slate-200">{text}</span>
          </li>
        ))}
      </ol>
    </Box>
  )
}

// ---------------------------------------------------------------- what it needs from you

function ApprovalCards() {
  const incidents = useGame((s) => s.frame?.incidents ?? NONE)
  const events = useGame((s) => s.events)
  const answer = useGame((s) => s.answer)
  const waiting = incidents.filter((i) => i.waiting_for_you)
  if (!waiting.length) return null
  return (
    <>
      {waiting.map((i) => {
        const rehearse = [...events].reverse().find((e) => e.incident === i.id && e.stage === 'rehearse' && e.agent === 'planner')
        const ranked = (rehearse?.data.ranked as Ranked[] | undefined) ?? []
        const option = ranked.find((r) => r.action === i.pending)
        return (
          <section key={i.id} className="animate-pulse-slow rounded-xl border-2 border-amber-400 bg-amber-950/60 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">Your decision is needed</div>
            <div className="mt-1 text-lg font-semibold text-amber-50">{plainAction(i.pending ?? '')}?</div>
            <p className="mt-2 text-sm text-amber-100/90">
              This would help {i.phones.length} affected user{i.phones.length === 1 ? '' : 's'}
              {option ? ` (twin predicts ${option.gain_db >= 0 ? '+' : ''}${option.gain_db.toFixed(1)} dB, ${option.harmed ? `${option.harmed} other user${option.harmed > 1 ? 's' : ''} slightly worse` : 'nobody else worse'})` : ''}.
            </p>
            <p className="mt-1 text-sm text-amber-100/80">
              Why you are asked: {i.pending_reasons.length ? i.pending_reasons.join('; ') : 'changes of this size need a person'}.
            </p>
            <div className="mt-3 flex gap-2">
              <button className="btn flex-1 bg-emerald-500 py-2 text-emerald-950 hover:bg-emerald-400" onClick={() => answer(i.id, 'approve')}>
                Approve
              </button>
              <button className="btn flex-1 bg-slate-700 py-2 hover:bg-slate-600" onClick={() => answer(i.id, 'reject')}>
                Reject
              </button>
            </div>
            <p className="mt-2 text-xs text-amber-200/70">After you approve, the safety rules are checked once more before anything changes.</p>
          </section>
        )
      })}
    </>
  )
}
