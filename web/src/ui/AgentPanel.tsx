import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type AgentEvent, type Incident } from '../api'
import { CAUSE_LABEL, STAGE_LABEL, STATUS_LABEL, STEPS, ms, stepOf } from '../stages'
import { useFocusedIncident, useGame } from '../store'
import IncidentActions from './IncidentActions'

const NONE: Incident[] = []

export default function AgentPanel() {
  const focus = useFocusedIncident()
  const [replay, setReplay] = useState<number | null>(null) // index into the incident's timeline, or live
  useEffect(() => setReplay(null), [focus?.id])
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <Approvals />
      <HandedOver />
      <IncidentTabs />
      {focus ? (
        <>
          <Loop incident={focus} replay={replay} />
          <IncidentActions incidentId={focus.id} />
          <IncidentCard incident={focus} />
          <Rehearsal incident={focus} />
          <Timeline incident={focus} replay={replay} setReplay={setReplay} />
        </>
      ) : (
        <Idle />
      )}
      <Feed />
    </div>
  )
}

function Card({ title, right, children, className = '' }: {
  title: string; right?: React.ReactNode; children: React.ReactNode; className?: string
}) {
  return (
    <section className={`rounded-lg border border-slate-800 bg-slate-900/70 ${className}`}>
      <header className="flex items-center justify-between border-b border-slate-800 px-3 py-1.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{title}</h3>
        {right}
      </header>
      <div className="p-3">{children}</div>
    </section>
  )
}

function Idle() {
  return (
    <Card title="Agent">
      <p className="text-sm text-slate-300">
        All quiet. The agent is watching every phone&apos;s signal once a second.
      </p>
      <p className="mt-2 text-sm text-slate-400">
        Pick a problem from the toolbar under the street and click on the map, or use a quick scenario.
      </p>
    </Card>
  )
}

// ---------------------------------------------------------------- the player's decisions

function Approvals() {
  const incidents = useGame((s) => s.frame?.incidents ?? NONE)
  const waiting = useMemo(() => incidents.filter((i) => i.waiting_for_you), [incidents])
  const answer = useGame((s) => s.answer)
  if (!waiting.length) return null
  return (
    <>
      {waiting.map((i) => (
        <section key={i.id} className="animate-pulse-slow rounded-lg border-2 border-amber-400 bg-amber-950/60 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-300">
            The agent needs your approval · {i.id}
          </div>
          <div className="mt-1 text-base font-semibold text-amber-50">{i.pending}</div>
          {i.pending_reasons.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-sm text-amber-200/90">
              {i.pending_reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          )}
          <div className="mt-3 flex gap-2">
            <button className="btn bg-emerald-500 text-emerald-950 hover:bg-emerald-400" onClick={() => answer(i.id, 'approve')}>
              ✓ Approve
            </button>
            <button className="btn bg-slate-700 hover:bg-slate-600" onClick={() => answer(i.id, 'reject')}>
              ✕ Reject
            </button>
          </div>
          <p className="mt-2 text-xs text-amber-200/70">Even after you approve, the rule-checker looks again before anything is sent.</p>
        </section>
      ))}
    </>
  )
}

/** Incidents the agent stopped working on because no safe fix was left: the operator decides what next. */
function HandedOver() {
  const incidents = useGame((s) => s.frame?.incidents ?? NONE)
  const events = useGame((s) => s.events)
  const problems = useGame((s) => s.frame?.problems)
  const sendAway = useGame((s) => s.sendAway)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const open = incidents.filter((i) => i.status === 'escalated' && !dismissed.has(i.id))
  if (!open.length) return null
  const vehicle = problems?.find((p) => ['bus', 'truck', 'car'].includes(p.kind))
  return (
    <>
      {open.slice(-2).map((i) => {
        const why = [...events].reverse().find((e) => e.incident === i.id && e.stage === 'escalate')
        return (
          <section key={i.id} className="rounded-lg border border-orange-500/60 bg-orange-950/40 p-3">
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-orange-300">
                Handed to you · {i.id} · {CAUSE_LABEL[i.cause] ?? i.cause}
              </div>
              <button className="text-xs text-slate-400 hover:text-slate-200"
                onClick={() => setDismissed(new Set(dismissed).add(i.id))}>dismiss</button>
            </div>
            <p className="mt-1 text-sm text-orange-50">{why?.text ?? 'No safe automatic fix is left.'}</p>
            <p className="mt-1 text-xs text-orange-200/70">
              The agent changes nothing it can&apos;t prove safe. It keeps watching and closes this when the phones recover.
            </p>
            {i.cause === 'blockage' && vehicle && (
              <button className="btn mt-2 bg-orange-500 text-orange-950 hover:bg-orange-400" onClick={() => sendAway(vehicle.id)}>
                Ask the {vehicle.kind} to move on
              </button>
            )}
          </section>
        )
      })}
    </>
  )
}

function IncidentTabs() {
  const incidents = useGame((s) => s.frame?.incidents ?? NONE)
  const selected = useGame((s) => s.selected)
  const select = useGame((s) => s.select)
  if (!incidents.length) return null
  const recent = incidents.slice(-8)
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <button onClick={() => select(null)}
        className={`chip ${selected === null ? 'bg-sky-500 text-sky-950' : 'bg-slate-800 text-slate-300'}`}>
        Follow live
      </button>
      {recent.map((i) => {
        const open = !['resolved', 'false_alarm'].includes(i.status)
        return (
          <button key={i.id} onClick={() => select(i.id)}
            className={`chip ${selected === i.id ? 'bg-sky-500 text-sky-950' : open ? 'bg-slate-700 text-slate-100' : 'bg-slate-800/60 text-slate-500'}`}>
            {open && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-red-400" />}
            {i.id}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------- the loop, lit up

function Loop({ incident, replay }: { incident: Incident; replay: number | null }) {
  const events = useGame((s) => s.events)
  const timeline = useMemo(() => events.filter((e) => e.incident === incident.id), [events, incident.id])
  const current = replay !== null && timeline[replay] ? timeline[replay] : null
  const activeKey = stepOf(current?.stage ?? incident.stage).key
  // time spent in each step on the incident's latest pass through the loop (its last busy tick)
  const lastTick = current?.tick ?? timeline[timeline.length - 1]?.tick
  const perStep = useMemo(() => {
    const out: Record<string, { ms: number; n: number }> = {}
    for (const e of timeline) {
      if (e.tick !== lastTick) continue
      const k = stepOf(e.stage).key
      out[k] = { ms: (out[k]?.ms ?? 0) + e.ms, n: (out[k]?.n ?? 0) + 1 }
    }
    return out
  }, [timeline, lastTick])
  const visited = useMemo(() => new Set(timeline.map((e) => stepOf(e.stage).key)), [timeline])

  return (
    <Card title={`Agent loop · ${incident.id}`}
      right={<span className="text-[11px] text-slate-500">{replay !== null ? 'replay' : 'live'} · tick {lastTick ?? '–'}</span>}>
      <div className="grid grid-cols-4 gap-1.5">
        {STEPS.map((s, i) => {
          const active = s.key === activeKey
          const t = perStep[s.key]
          return (
            <div key={s.key}
              className={`relative rounded-md border px-2 py-1.5 transition-all duration-300 ${active ? 'scale-[1.03] shadow-lg' : ''}`}
              style={{
                borderColor: active ? s.color : visited.has(s.key) ? `${s.color}55` : '#1e293b',
                background: active ? `${s.color}22` : '#0f172a',
                boxShadow: active ? `0 0 18px ${s.color}55` : undefined,
              }}>
              <div className="flex items-center gap-1 text-[10px] text-slate-500">
                <span>{i + 1}</span>
                {active && <span className="h-1.5 w-1.5 animate-ping rounded-full" style={{ background: s.color }} />}
              </div>
              <div className="text-[13px] font-semibold" style={{ color: active || visited.has(s.key) ? s.color : '#64748b' }}>
                {s.label}
              </div>
              <div className="truncate text-[10px] text-slate-500">{s.who}</div>
              <div className="mt-0.5 h-4 font-mono text-[11px] text-slate-300">{t ? ms(t.ms) : ''}</div>
            </div>
          )
        })}
      </div>
      {current && (
        <div className="mt-2 rounded border border-slate-700 bg-slate-950/60 p-2 text-sm text-slate-200">
          <span className="mr-1 font-mono text-xs text-slate-500">t={current.tick}s</span>{current.text}
        </div>
      )}
    </Card>
  )
}

function IncidentCard({ incident: i }: { incident: Incident }) {
  const probs = Object.entries(i.probs).sort((a, b) => b[1] - a[1])
  return (
    <Card title="Diagnosis" right={<span className="chip bg-slate-800 text-slate-300">{STATUS_LABEL[i.status] ?? i.status}</span>}>
      <div className="flex items-baseline justify-between">
        <div className="text-lg font-semibold text-slate-50">{CAUSE_LABEL[i.cause] ?? i.cause}</div>
        <div className="font-mono text-sm text-violet-300">{Math.round(i.confidence * 100)}% sure</div>
      </div>
      <div className="text-sm text-slate-400">{i.phones.length} phone(s) {i.place}</div>
      {probs.length > 0 && (
        <div className="mt-2 space-y-1">
          {probs.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 text-xs">
              <span className="w-24 text-slate-400">{CAUSE_LABEL[k] ?? k}</span>
              <div className="h-1.5 flex-1 rounded bg-slate-800">
                <div className="h-1.5 rounded bg-violet-400" style={{ width: `${Math.max(1, v * 100)}%` }} />
              </div>
              <span className="w-10 text-right font-mono text-slate-400">{(v * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}
      <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
        <Stat label="fixes tried" value={i.attempts} />
        <Stat label="kept" value={i.kept} />
        <Stat label="thinking time" value={ms(i.decision_ms)} />
      </div>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded bg-slate-950/60 px-1 py-1">
      <div className="font-mono text-sm text-slate-100">{value}</div>
      <div className="text-[10px] text-slate-500">{label}</div>
    </div>
  )
}

interface Ranked { action: string; gain_db: number; harmed: number; zone_loads: Record<string, number> }

function Rehearsal({ incident }: { incident: Incident }) {
  const events = useGame((s) => s.events)
  const mine = useMemo(() => events.filter((e) => e.incident === incident.id), [events, incident.id])
  const lastRehearse = [...mine].reverse().find((e) => e.stage === 'rehearse' && e.agent === 'planner')
  if (!lastRehearse) return null
  const after = mine.filter((e) => e.tick >= lastRehearse.tick)
  const ranked = (lastRehearse.data.ranked as Ranked[] | undefined) ?? []
  const rejected = new Map(after.filter((e) => e.stage === 'check' && e.text.startsWith('Rejected'))
    .map((e) => [String(e.data.action), (e.data.reasons as string[] | undefined)?.join('; ') ?? '']))
  const chosen = String(after.find((e) => e.stage === 'act' || e.stage === 'escalate')?.data.action ?? '')
  const result = after.find((e) => e.stage === 'verify' || e.stage === 'undo')
  return (
    <Card title="Digital twin rehearsal" right={<span className="text-[11px] text-slate-500">tick {lastRehearse.tick}</span>}>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[10px] uppercase text-slate-500">
            <th className="pb-1 font-medium">Fix tried on the twin</th>
            <th className="pb-1 text-right font-medium">gain</th>
            <th className="pb-1 text-right font-medium">harm</th>
          </tr>
        </thead>
        <tbody>
          {ranked.slice(0, 5).map((r) => {
            const why = rejected.get(r.action)
            const isChosen = r.action === chosen
            return (
              <tr key={r.action} title={why} className={isChosen ? 'text-emerald-300' : why ? 'text-slate-500' : 'text-slate-200'}>
                <td className="py-0.5 pr-2">
                  {isChosen ? '▶ ' : why ? '✕ ' : '· '}{r.action}
                  {why && <div className="truncate text-[10px] text-amber-400/80">safety: {why}</div>}
                </td>
                <td className="py-0.5 text-right font-mono">{r.gain_db >= 0 ? '+' : ''}{r.gain_db.toFixed(1)} dB</td>
                <td className="py-0.5 text-right font-mono">{r.harmed}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {result && typeof result.data.measured === 'number' && (
        <div className={`mt-2 rounded px-2 py-1.5 text-xs ${result.stage === 'verify' ? 'bg-emerald-950/60 text-emerald-200' : 'bg-rose-950/60 text-rose-200'}`}>
          <b>Reality check:</b> twin predicted {fmtDb(result.data.predicted)}, measured {fmtDb(result.data.measured)} →{' '}
          {result.stage === 'verify' ? 'kept' : 'undone'}
          {typeof result.data.twin_error === 'number' && <> · twin error now {(result.data.twin_error as number).toFixed(1)} dB</>}
        </div>
      )}
    </Card>
  )
}

const fmtDb = (v: unknown) => (typeof v === 'number' && isFinite(v) ? `${v >= 0 ? '+' : ''}${v.toFixed(1)} dB` : '–')

// ---------------------------------------------------------------- replay and live feed

function Timeline({ incident, replay, setReplay }: {
  incident: Incident; replay: number | null; setReplay: (i: number | null) => void
}) {
  const sessionId = useGame((s) => s.sessionId)
  const live = useGame((s) => s.events)
  const [full, setFull] = useState<AgentEvent[] | null>(null)
  // the live buffer is capped; fetch the full timeline when the player starts scrubbing
  useEffect(() => {
    if (replay === null || !sessionId) return
    api.incident(sessionId, incident.id).then((r) => setFull(r.events)).catch(() => {})
  }, [replay === null, sessionId, incident.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const timeline = full ?? live.filter((e) => e.incident === incident.id)
  if (timeline.length < 2) return null
  return (
    <Card title="Replay this incident" right={
      replay !== null
        ? <button className="chip bg-sky-500 text-sky-950" onClick={() => { setReplay(null); setFull(null) }}>Back to live</button>
        : <span className="text-[11px] text-slate-500">{timeline.length} steps</span>
    }>
      <input type="range" min={0} max={timeline.length - 1} value={replay ?? timeline.length - 1}
        onChange={(e) => setReplay(Number(e.target.value))} className="w-full accent-sky-400" />
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>t={timeline[0].tick}s detected</span><span>t={timeline[timeline.length - 1].tick}s</span>
      </div>
    </Card>
  )
}

function Feed() {
  const events = useGame((s) => s.events)
  const selected = useGame((s) => s.selected)
  const shown = useMemo(() => (selected ? events.filter((e) => e.incident === selected) : events).slice(-60).reverse(),
    [events, selected])
  const top = useRef<HTMLDivElement>(null)
  return (
    <Card title={selected ? `Log · ${selected}` : 'Live decision log'} className="min-h-48"
      right={<span className="text-[11px] text-slate-500">{events.length} steps</span>}>
      <div ref={top} className="space-y-1.5">
        {shown.length === 0 && <div className="text-sm text-slate-500">Nothing yet.</div>}
        {shown.map((e, i) => <FeedRow key={`${e.tick}-${i}-${e.stage}`} e={e} fresh={i < 3} />)}
      </div>
    </Card>
  )
}

function FeedRow({ e, fresh }: { e: AgentEvent; fresh: boolean }) {
  const step = stepOf(e.stage)
  const select = useGame((s) => s.select)
  return (
    <div className={`flex gap-2 text-[13px] leading-snug ${fresh ? 'animate-fade-in' : ''}`}>
      <span className="w-9 shrink-0 pt-0.5 text-right font-mono text-[11px] text-slate-500">{e.tick}s</span>
      <span className="mt-0.5 h-fit shrink-0 rounded px-1.5 py-px text-[10px] font-semibold uppercase"
        style={{ background: `${step.color}26`, color: step.color }}>
        {STAGE_LABEL[e.stage] ?? e.stage}
      </span>
      <span className="flex-1 text-slate-200">
        {e.text}
        {e.incident && (
          <button onClick={() => select(e.incident)} className="ml-1 text-[10px] text-sky-400 hover:underline">{e.incident}</button>
        )}
      </span>
      {e.ms >= 1 && <span className="shrink-0 pt-0.5 font-mono text-[10px] text-slate-500">{ms(e.ms)}</span>}
    </div>
  )
}
