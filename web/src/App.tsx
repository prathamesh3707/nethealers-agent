import { useEffect } from 'react'
import Street from './scene/Street'
import { useGame } from './store'
import AgentPanel from './ui/AgentPanel'
import StatsBar from './ui/StatsBar'
import Toolbar from './ui/Toolbar'
import TopBar from './ui/TopBar'

export default function App() {
  const resume = useGame((s) => s.resume)
  const setTool = useGame((s) => s.setTool)
  const toast = useGame((s) => s.toast)
  const error = useGame((s) => s.frame?.error)
  const control = useGame((s) => s.control)

  useEffect(() => { void resume() }, [resume])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setTool(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setTool])

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-200">
      <TopBar />
      {error && (
        <div className="flex items-center gap-3 border-b border-red-800 bg-red-950 px-4 py-2 text-sm text-red-200">
          <b>The simulation hit an error and paused:</b> <span className="font-mono text-xs">{error}</span>
          <button className="btn ml-auto bg-red-800 hover:bg-red-700" onClick={() => control('resume')}>Resume</button>
        </div>
      )}
      <main className="flex min-h-0 flex-1">
        <section className="relative min-w-0 flex-1">
          <Street />
          <Legend />
          <Toolbar />
        </section>
        <aside className="w-[440px] shrink-0 border-l border-slate-800 bg-slate-950">
          <AgentPanel />
        </aside>
      </main>
      <StatsBar />
      {toast && (
        <div className={`fixed left-1/2 top-16 z-30 -translate-x-1/2 rounded-lg px-4 py-2 text-sm shadow-xl
          ${toast.tone === 'error' ? 'bg-red-600 text-white' : 'bg-slate-800 text-slate-100'}`}>
          {toast.text}
        </div>
      )}
    </div>
  )
}

function Legend() {
  return (
    <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-[11px] text-slate-300 backdrop-blur">
      <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">Signal clarity</div>
      <div className="flex items-center gap-3">
        <span><i className="dot bg-emerald-500" /> good</span>
        <span><i className="dot bg-amber-500" /> fair</span>
        <span><i className="dot bg-red-500" /> poor</span>
        <span><i className="dot bg-transparent ring-2 ring-amber-400" /> being fixed</span>
      </div>
      <div className="mt-1 text-slate-500">Lines join each phone to its tower · drag to orbit, scroll to zoom</div>
    </div>
  )
}
