import { useGame } from '../store'

/** Under an incident: download everything about it for audit, or ask the policy adviser about it. */
export default function IncidentActions({ incidentId }: { incidentId: string }) {
  const sessionId = useGame((s) => s.sessionId)
  const openPolicy = useGame((s) => s.openPolicy)
  if (!sessionId) return null
  return (
    <div className="flex flex-wrap gap-2">
      <a href={`/sessions/${sessionId}/incidents/${incidentId}/report`} download
        title="Diagnosis, every fix with predicted and measured result, approvals, adviser questions, full timeline and version stamps"
        className="btn bg-slate-800 text-xs text-slate-200 hover:bg-slate-700">⬇ Download {incidentId} report</a>
      <button onClick={() => useGame.setState({ rolesOf: incidentId })}
        className="btn bg-slate-800 text-xs text-slate-200 hover:bg-slate-700">👥 Who knew what, when</button>
      <button onClick={() => openPolicy('ask', incidentId)}
        className="btn bg-slate-800 text-xs text-slate-200 hover:bg-slate-700">⚖ Ask the policy adviser about it</button>
    </div>
  )
}
