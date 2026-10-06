import { incidentHeadline } from '../plain'
import { useFocusedIncident, useGame } from '../store'

/** One sentence under the top bar: what is happening on the street right now. */
export default function StatusLine() {
  const frame = useGame((s) => s.frame)
  const main = useFocusedIncident()
  if (!frame) return null
  const open = frame.incidents.filter((i) => !['resolved', 'false_alarm'].includes(i.status))
  const waiting = open.find((i) => i.waiting_for_you)
  const latest = waiting ?? (main && open.includes(main) ? main : open[open.length - 1])
  const recent = [...frame.incidents].reverse().find((i) => i.status === 'resolved' && i.closed != null
    && frame.tick - i.closed < 8 && (i.outcome === 'fixed' || i.outcome === 'withdrawn'))

  let tone = 'border-emerald-700/50 bg-emerald-950/40 text-emerald-100'
  let icon = '✓'
  let text = `All ${frame.phones.length} users are being watched. ${frame.score.good} have good service.`
  if (latest) {
    tone = waiting ? 'border-amber-500/60 bg-amber-950/50 text-amber-100' : 'border-red-600/50 bg-red-950/40 text-red-100'
    icon = waiting ? '🙋' : '⚠'
    text = incidentHeadline(latest)
  } else if (recent) {
    const took = recent.closed! - recent.opened
    text = `Problem solved: service restored for ${recent.phones.length} users in ${took} s.`
    icon = '🎉'
  } else if (frame.score.degraded_now > 0) {
    // No open problem, yet some users are below their usual level: say so, so the numbers below don't look wrong.
    const n = frame.score.degraded_now
    const without = frame.without_agent?.degraded_now
    tone = 'border-slate-600/60 bg-slate-900/60 text-slate-100'
    icon = '👁'
    text = `No open problems. ${n} user${n === 1 ? ' is' : 's are'} below ${n === 1 ? 'its' : 'their'} usual signal but `
      + `still ${n === 1 ? 'has' : 'have'} service; the agent counts this as normal variation and keeps watching`
      + (without != null && without > n ? ` (without the agent: ${without}).` : '.')
  }
  return (
    <div data-tour="status" className={`flex shrink-0 items-center gap-3 border-b px-4 py-2 text-[15px] ${tone}`}>
      <span className="text-lg">{icon}</span>
      <span className="font-medium">{text}</span>
    </div>
  )
}
