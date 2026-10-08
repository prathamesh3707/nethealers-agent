import { useEffect, useState } from 'react'
import { api, type Coordination as Coord, type RoleId } from '../api'
import { useGame } from '../store'

/**
 * Who knew what, when: one incident as three institutional roles and a person, each with its own mandate and
 * its own information. Messages appear in the column of the role that produced them, in time order, so the
 * hand-overs between roles (and the information each one received) can be followed and audited.
 */

const TONE: Record<RoleId, { head: string; card: string }> = {
  noc: { head: 'border-sky-500/60 text-sky-300', card: 'border-sky-800/70 bg-sky-950/40' },
  planner: { head: 'border-teal-500/60 text-teal-300', card: 'border-teal-800/70 bg-teal-950/40' },
  regulator: { head: 'border-amber-500/60 text-amber-300', card: 'border-amber-800/70 bg-amber-950/30' },
  person: { head: 'border-fuchsia-500/60 text-fuchsia-300', card: 'border-fuchsia-800/70 bg-fuchsia-950/30' },
}

export default function Coordination() {
  const iid = useGame((s) => s.rolesOf)
  const sessionId = useGame((s) => s.sessionId)
  const [data, setData] = useState<Coord | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!iid || !sessionId) return
    let live = true
    const load = () => api.roles(sessionId, iid).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message ?? e)))
    void load()
    const t = setInterval(load, 2000) // the incident may still be running
    return () => { live = false; clearInterval(t) }
  }, [iid, sessionId])
  if (!iid) return null
  const close = () => { useGame.setState({ rolesOf: null }); setData(null) }
  const names = Object.fromEntries((data?.roles ?? []).map((r) => [r.id, r.name])) as Record<RoleId, string>
  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-slate-950/97 backdrop-blur">
      <header className="flex items-center gap-4 border-b border-slate-800 px-5 py-3">
        <div>
          <div className="text-base font-bold text-slate-50">👥 Who knew what, when · {iid}</div>
          <div className="text-xs text-slate-400">Each role has its own mandate and sees only its own information; it starts only when the one before it hands over</div>
        </div>
        <button className="btn ml-auto bg-slate-800 hover:bg-slate-700" onClick={close}>Close ✕</button>
      </header>
      {error && <p className="p-6 text-sm text-red-300">{error}</p>}
      {data && (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6">
          <div className="sticky top-0 z-10 grid grid-cols-[64px_repeat(4,minmax(0,1fr))] gap-3 bg-slate-950/95 pb-3 pt-4">
            <div />
            {data.roles.map((r) => (
              <div key={r.id} className={`rounded-lg border-t-2 bg-slate-900/80 p-3 ${TONE[r.id].head}`}>
                <div className="text-sm font-bold">{r.name}</div>
                <p className="mt-1 text-[11px] leading-snug text-slate-300">{r.mandate}</p>
                <p className="mt-1.5 text-[11px] leading-snug text-slate-400"><b className="text-slate-300">Sees:</b> {r.sees}</p>
                <p className="text-[11px] leading-snug text-slate-400"><b className="text-slate-300">Cannot:</b> {r.cannot}</p>
                <p className="mt-1.5 text-[10px] text-slate-500">
                  {data.first_heard[r.id] !== undefined ? `first involved at T+${data.first_heard[r.id]} s` : 'not involved in this incident'}
                </p>
              </div>
            ))}
          </div>
          <div className="space-y-1.5">
            {data.messages.map((m, i) => {
              const prev = data.messages[i - 1]
              const handed = prev && prev.role !== m.role
              const col = data.roles.findIndex((r) => r.id === m.role)
              return (
                <div key={i} className="grid grid-cols-[64px_repeat(4,minmax(0,1fr))] gap-3">
                  <div className="pt-2 text-right font-mono text-[11px] text-slate-500">{!prev || prev.t !== m.t ? `T+${m.t} s` : ''}</div>
                  <div style={{ gridColumnStart: col + 2 }} className={`rounded-md border px-2.5 py-1.5 text-xs leading-relaxed text-slate-200 ${TONE[m.role].card}`}>
                    {handed && <div className="mb-0.5 text-[10px] text-slate-400">← from {names[prev.role]}</div>}
                    {m.text}
                  </div>
                </div>
              )
            })}
            {data.messages.length === 0 && <p className="text-sm text-slate-500">Nothing logged for this incident yet.</p>}
          </div>
        </div>
      )}
    </div>
  )
}
