import { incidentHeadline } from '../plain'
import { useGame } from '../store'

/** One sentence under the top bar: what is happening on the street right now. */
export default function StatusLine() {
  const frame = useGame((s) => s.frame)
  if (!frame) return null
  const open = frame.incidents.filter((i) => !['resolved', 'false_alarm'].includes(i.status))
  const waiting = open.find((i) => i.waiting_for_you)
  const latest = waiting ?? open[open.length - 1]
  const recent = [...frame.incidents].reverse().find((i) => i.status === 'resolved' && i.closed != null
    && frame.tick - i.closed < 8 && (i.outcome === 'fixed' || i.outcome === 'withdrawn'))

  let tone = 'border-emerald-700/50 bg-emerald-950/40 text-emerald-100'
  let icon = '✓'
  let text = `All ${frame.phones.length} users are being watched. ${frame.score.good} have good service.`
  if (latest) {
    tone = waiting ? 'border-amber-500/60 bg-amber-950/50 text-amber-100' : 'border-red-600/50 bg-red-950/40 text-red-100'
    icon = waiting ? '🙋' : '⚠'
    text = incidentHeadline(latest) + (open.length > 1 ? ` (${open.length} problems open)` : '')
  } else if (recent) {
    const took = recent.closed! - recent.opened
    text = `Problem solved: service restored for ${recent.phones.length} users in ${took} s.`
    icon = '🎉'
  }
  return (
    <div className={`flex shrink-0 items-center gap-3 border-b px-4 py-2 text-[15px] ${tone}`}>
      <span className="text-lg">{icon}</span>
      <span className="font-medium">{text}</span>
    </div>
  )
}
