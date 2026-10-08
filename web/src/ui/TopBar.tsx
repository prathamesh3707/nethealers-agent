import { useState } from 'react'
import { clock } from '../stages'
import { useGame } from '../store'

const SPEEDS = [0.5, 1, 2, 4]

export default function TopBar() {
  const frame = useGame((s) => s.frame)
  const connected = useGame((s) => s.connected)
  const control = useGame((s) => s.control)
  const start = useGame((s) => s.start)
  const starting = useGame((s) => s.starting)
  const languageModel = useGame((s) => s.languageModel)
  const [menu, setMenu] = useState(false)
  const paused = frame?.paused ?? false
  const llm = frame?.llm

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-slate-800 bg-slate-950 px-4">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-gradient-to-br from-emerald-400 to-sky-500 text-sm font-black text-slate-950">N</span>
        <div className="leading-tight">
          <div className="text-sm font-bold text-slate-50">NetHealers</div>
          <div className="text-[10px] text-slate-500">Self-healing 5G agent · {useGame.getState().scene?.name ?? 'Station Road'}</div>
        </div>
      </div>

      <div data-tour="controls" className="ml-4 flex items-center gap-1.5">
        <button className="btn-icon" title={paused ? 'Resume' : 'Pause'} onClick={() => control(paused ? 'resume' : 'pause')}>
          {paused ? '▶' : '❚❚'}
        </button>
        <button className="btn-icon" title="One second forward (pause first)" disabled={!paused} onClick={() => control('step')}>
          ⏭
        </button>
        <div className="ml-1 flex overflow-hidden rounded-md border border-slate-700">
          {SPEEDS.map((v) => (
            <button key={v} onClick={() => control('speed', v)}
              className={`px-2 py-1 text-xs ${frame?.speed === v ? 'bg-sky-500 text-sky-950' : 'text-slate-300 hover:bg-slate-800'}`}>
              {v}×
            </button>
          ))}
        </div>
        <div className="ml-3 font-mono text-lg tabular-nums text-slate-100" title="Simulated time (1 tick = 1 second)">
          {clock(frame?.tick ?? 0)}
        </div>
        {paused && <span className="chip bg-amber-500/20 text-amber-300">paused</span>}
      </div>

      <div className="ml-auto flex items-center gap-2 text-xs">
        <button data-tour="policy" className="btn bg-amber-600/90 py-1 text-xs text-amber-50 hover:bg-amber-500"
          onClick={() => useGame.getState().setPolicyOpen(true)}>
          ⚖ Policy
        </button>
        <button className="btn bg-slate-800 py-1 text-xs hover:bg-slate-700" onClick={() => useGame.getState().setTour(0)}>
          ⓘ UI tour
        </button>
        <button className="btn bg-emerald-600/90 py-1 text-xs text-emerald-50 hover:bg-emerald-500" onClick={() => useGame.getState().setDemo(true)}>
          ▶ Incident demo
        </button>
        <ModeSwitch />
        <button className="btn-icon" title="What is this? (intro)" onClick={() => useGame.getState().setIntro(true)}>?</button>
        <span data-tour="llm" className={`chip ${llm?.live ? 'bg-indigo-500/20 text-indigo-300' : 'bg-slate-800 text-slate-400'}`}
          title={llm?.live ? `Providers: ${llm.providers?.join(', ')}` : 'No language-model key: the planner and safety adviser use plain rules'}>
          {llm?.live ? `🧠 LLM on · ${llm.calls ?? 0} calls` : '🧠 LLM off · plain rules'}
        </span>
        <span className={`chip ${connected ? 'bg-emerald-500/15 text-emerald-300' : 'bg-red-500/20 text-red-300'}`}>
          <span className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${connected ? 'bg-emerald-400' : 'bg-red-400'}`} />
          {connected ? 'live' : 'reconnecting'}
        </span>
        <div className="relative">
          <button className="btn bg-slate-800 hover:bg-slate-700" disabled={starting} onClick={() => setMenu(!menu)}>
            {starting ? 'Starting…' : 'New game ▾'}
          </button>
          {menu && (
            <div className="absolute right-0 top-10 z-20 w-64 rounded-lg border border-slate-700 bg-slate-900 p-2 shadow-xl">
              <MenuItem title="Agent with language model" sub="Planner + safety adviser (needs a key in .env)"
                onClick={() => { setMenu(false); void start({ language_model: true }) }} />
              <MenuItem title="Agent with plain rules" sub="No AI calls, fully offline"
                onClick={() => { setMenu(false); void start({ language_model: false }) }} />
              <MenuItem title="Auto-approve after 8 s" sub="For a hands-free demo"
                onClick={() => { setMenu(false); void start({ language_model: languageModel, auto_approve_after: 8 }) }} />
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

function MenuItem({ title, sub, onClick }: { title: string; sub: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="block w-full rounded-md px-2 py-1.5 text-left hover:bg-slate-800">
      <div className="text-sm text-slate-100">{title}</div>
      <div className="text-[11px] text-slate-500">{sub}</div>
    </button>
  )
}

function ModeSwitch() {
  const mode = useGame((s) => s.mode)
  const setMode = useGame((s) => s.setMode)
  return (
    <div data-tour="mode" className="flex overflow-hidden rounded-md border border-slate-700" title="Simple: plain language. Expert: every number and timing.">
      {(['simple', 'expert'] as const).map((m) => (
        <button key={m} onClick={() => setMode(m)}
          className={`px-2.5 py-1 text-xs capitalize ${mode === m ? 'bg-sky-500 text-sky-950' : 'text-slate-300 hover:bg-slate-800'}`}>
          {m}
        </button>
      ))}
    </div>
  )
}
