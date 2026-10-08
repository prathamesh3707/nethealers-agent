import { useEffect } from 'react'
import Street from './scene/Street'
import { useGame } from './store'
import AgentPanel from './ui/AgentPanel'
import Intro from './ui/Intro'
import SimplePanel from './ui/SimplePanel'
import StatusLine from './ui/StatusLine'
import StatsBar from './ui/StatsBar'
import Toolbar from './ui/Toolbar'
import Demo from './ui/Demo'
import PolicyPanel from './ui/PolicyPanel'
import Coordination from './ui/Coordination'
import Tour from './ui/Tour'
import TopBar from './ui/TopBar'

export default function App() {
  const resume = useGame((s) => s.resume)
  const setTool = useGame((s) => s.setTool)
  const toast = useGame((s) => s.toast)
  const error = useGame((s) => s.frame?.error)
  const control = useGame((s) => s.control)
  const mode = useGame((s) => s.mode)

  useEffect(() => { void resume() }, [resume])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return
      if (e.key === 'Escape') setTool(null)
      // move the selected bus, truck or blocker along the road
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault()
        void useGame.getState().nudge((e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 20 : 5))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setTool])

  return (
    <div className="flex h-screen min-w-[900px] flex-col overflow-hidden bg-slate-950 text-slate-200">
      <TopBar />
      <StatusLine />
      {error && (
        <div className="flex items-center gap-3 border-b border-red-800 bg-red-950 px-4 py-2 text-sm text-red-200">
          <b>The simulation hit an error and paused:</b> <span className="font-mono text-xs">{error}</span>
          <button className="btn ml-auto bg-red-800 hover:bg-red-700" onClick={() => control('resume')}>Resume</button>
        </div>
      )}
      <main className="flex min-h-0 flex-1">
        <section data-tour="map" className="relative min-w-0 flex-1">
          <Street />
          <Legend />
          <Toolbar />
        </section>
        <aside className="w-[340px] shrink-0 border-l border-slate-800 bg-slate-950 lg:w-[400px] 2xl:w-[460px]">
          {mode === 'simple' ? <SimplePanel /> : <AgentPanel />}
        </aside>
      </main>
      <StatsBar />
      <Intro />
      <Tour />
      <Demo />
      <PolicyPanel />
      <Coordination />
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
    <div data-tour="legend" className="pointer-events-none absolute left-3 top-3 z-10 hidden rounded-lg md:block border border-slate-800 bg-slate-950/80 px-3 py-2 text-[11px] text-slate-300 backdrop-blur">
      <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">Each dot is a user’s phone</div>
      <div className="flex items-center gap-3">
        <span><i className="dot bg-emerald-500" /> good service</span>
        <span><i className="dot bg-amber-500" /> slow</span>
        <span><i className="dot bg-red-500" /> no service</span>
        <span><i className="dot bg-transparent ring-2 ring-amber-400" /> being fixed</span>
      </div>
      <div className="mt-1 text-slate-400">Lines show which tower serves each phone · <span className="text-red-400">red line ✖ = signal blocked</span></div>
      <div className="text-slate-500">Drag to rotate · scroll to zoom · ← → keys move the selected vehicle</div>
    </div>
  )
}
