import { ms } from '../stages'
import { useGame, type HistoryPoint } from '../store'

export default function StatsBar() {
  const mode = useGame((s) => s.mode)
  return mode === 'simple' ? <SimpleStats /> : <ExpertStats />
}

/** Big, plain numbers, and the comparison that matters: the same street with and without the agent. */
function SimpleStats() {
  const frame = useGame((s) => s.frame)
  const history = useGame((s) => s.history)
  if (!frame) return null
  const total = frame.phones.length
  const ok = frame.score.good + frame.score.fair
  const hurt = frame.score.degraded_now
  const without = frame.without_agent
  const withoutHurt = without?.degraded_now ?? null
  const saved = withoutHurt !== null ? Math.max(0, withoutHurt - hurt) : null
  return (
    <footer data-tour="stats" className="flex h-[84px] shrink-0 items-center gap-4 overflow-hidden border-t border-slate-800 bg-slate-950 px-5 xl:gap-6">
      <div data-tour="stats-main" className="flex gap-6">
        <Big value={`${ok}/${total}`} label="users with service" tone="text-emerald-300" />
        <Big value={hurt} label="users affected now" tone={hurt ? 'text-red-300' : 'text-slate-100'} />
      </div>
      {withoutHurt !== null && (
        <div data-tour="compare" className="rounded-xl border border-slate-800 bg-slate-900/70 px-4 py-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Same street, same problems, without the agent</div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="font-mono text-xl text-red-300">{withoutHurt}</span>
            <span className="text-sm text-slate-400">users would be affected</span>
            {saved !== null && saved > 0 && (
              <span className="chip ml-2 bg-emerald-500/20 text-emerald-300">agent is helping {saved} more user{saved > 1 ? 's' : ''}</span>
            )}
          </div>
        </div>
      )}
      <div className="hidden 2xl:block"><Spark history={history} /></div>
      <div data-tour="stats-right" className="ml-auto flex gap-4 xl:gap-6">
        <Big value={frame.score.phones_rescued} label="users recovered" tone="text-emerald-300" small />
        <Big value={frame.score.fixes_applied} label="fixes applied" small />
        <Big value={frame.score.fixes_undone} label="undone (didn’t work)" small />
        <Big value={frame.score.asked_you} label="times it asked you" tone="text-amber-300" small />
      </div>
    </footer>
  )
}

function Big({ value, label, tone = 'text-slate-100', small = false }: {
  value: React.ReactNode; label: string; tone?: string; small?: boolean
}) {
  return (
    <div className="text-center">
      <div className={`font-mono tabular-nums ${small ? 'text-xl' : 'text-3xl'} ${tone}`}>{value}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
  )
}

function ExpertStats() {
  const frame = useGame((s) => s.frame)
  const history = useGame((s) => s.history)
  if (!frame) return null
  const sc = frame.score
  const total = Math.max(1, sc.good + sc.fair + sc.poor)
  return (
    <footer className="flex h-[72px] shrink-0 items-center gap-5 border-t border-slate-800 bg-slate-950 px-4">
      <div className="w-56">
        <div className="mb-1 flex justify-between text-[10px] uppercase tracking-wider text-slate-500">
          <span>Phones · {total}</span>
          <span><b className="text-emerald-400">{sc.good}</b> · <b className="text-amber-400">{sc.fair}</b> · <b className="text-red-400">{sc.poor}</b></span>
        </div>
        <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-800">
          <div className="bg-emerald-500 transition-all" style={{ width: `${(sc.good / total) * 100}%` }} />
          <div className="bg-amber-500 transition-all" style={{ width: `${(sc.fair / total) * 100}%` }} />
          <div className="bg-red-500 transition-all" style={{ width: `${(sc.poor / total) * 100}%` }} />
        </div>
        <div className="mt-1 text-[10px] text-slate-500">good ≥ 13 dB · fair 0–13 dB · poor &lt; 0 dB clarity</div>
      </div>
      <Spark history={history} />
      <Metric label="Hurt right now" value={sc.degraded_now} tone={sc.degraded_now ? 'text-red-300' : 'text-slate-100'} />
      <Metric label="Phones rescued" value={sc.phones_rescued} tone="text-emerald-300" />
      <Metric label="Fixes applied" value={sc.fixes_applied} />
      <Metric label="Fixes undone" value={sc.fixes_undone} />
      <Metric label="Asked you" value={sc.asked_you} tone="text-amber-300" />
      <div className="ml-auto flex gap-5">
        <Metric label="Agent turn" value={ms(frame.timing.agent_ms)} small />
        <Metric label="Whole tick" value={ms(frame.timing.tick_ms)} small />
        {frame.llm.live && <Metric label="LLM tokens" value={`${frame.llm.tokens_in ?? 0}/${frame.llm.tokens_out ?? 0}`} small />}
      </div>
    </footer>
  )
}

function Metric({ label, value, tone = 'text-slate-100', small = false }: {
  label: string; value: React.ReactNode; tone?: string; small?: boolean
}) {
  return (
    <div className="text-center">
      <div className={`font-mono tabular-nums ${small ? 'text-sm' : 'text-xl'} ${tone}`}>{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
    </div>
  )
}

/** Phones hurt over the last few minutes. */
function Spark({ history }: { history: HistoryPoint[] }) {
  const W = 180
  const H = 40
  if (history.length < 2) return <div style={{ width: W }} />
  const max = Math.max(4, ...history.map((h) => h.degraded))
  const pts = history.map((h, i) => `${(i / (history.length - 1)) * W},${H - (h.degraded / max) * (H - 4) - 2}`)
  return (
    <div>
      <svg width={W} height={H} className="block">
        <polygon points={`0,${H} ${pts.join(' ')} ${W},${H}`} fill="#ef444433" />
        <polyline points={pts.join(' ')} fill="none" stroke="#f87171" strokeWidth={1.5} />
      </svg>
      <div className="text-center text-[10px] uppercase tracking-wider text-slate-500">users affected · last {history.length}s</div>
    </div>
  )
}
