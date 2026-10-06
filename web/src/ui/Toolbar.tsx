import type { NewProblem } from '../api'
import { useGame, type Tool } from '../store'

interface ToolDef { tool: NonNullable<Tool>; icon: string; label: string; hint: string; cause: string }

const TOOLS: ToolDef[] = [
  { tool: { kind: 'bus', drive: true }, icon: '🚌', label: 'Bus', hint: 'Drives in, waits 30 s, leaves', cause: 'blockage' },
  { tool: { kind: 'truck', drive: true }, icon: '🚚', label: 'Truck', hint: 'Drives in, waits 30 s, leaves', cause: 'blockage' },
  { tool: { kind: 'crowd' }, icon: '👥', label: 'Crowd', hint: 'People standing in the signal path', cause: 'blockage' },
  { tool: { kind: 'hoarding' }, icon: '🪧', label: 'Hoarding', hint: 'A new advertising board', cause: 'blockage' },
  { tool: { kind: 'stuck_beam' }, icon: '🔦', label: 'Stuck beam', hint: 'Nearby phones get a badly aimed beam', cause: 'wrong beam' },
  { tool: { kind: 'misconfig' }, icon: '📡', label: 'Bad tower settings', hint: 'Click near a tower: too loud, tilted up', cause: 'interference' },
  { tool: { kind: 'booster' }, icon: '📶', label: 'Illegal booster', hint: 'Outside noise no setting can fix', cause: 'interference' },
  { tool: { kind: 'crowd_surge' }, icon: '🏟️', label: 'Crowd surge', hint: '60 people arrive and all want data', cause: 'congestion' },
]

const SCENARIOS: { label: string; problems: NewProblem[] }[] = [
  { label: 'Bus at the bus stop', problems: [{ kind: 'bus', x: 211, y: 107.8, drive: true, stay: 40 }] },
  { label: 'Stuck beams at the bus stop', problems: [{ kind: 'stuck_beam', x: 233, y: 115 }] },
  { label: 'Tower C misconfigured', problems: [{ kind: 'misconfig', tower: 2 }] },
  { label: 'Crowd surge on the street', problems: [{ kind: 'crowd_surge', x: 140, y: 100, people: 40 }] },
]

export default function Toolbar() {
  const tool = useGame((s) => s.tool)
  const setTool = useGame((s) => s.setTool)
  const addProblem = useGame((s) => s.addProblem)
  const problems = useGame((s) => s.frame?.problems)
  const removeProblem = useGame((s) => s.removeProblem)
  const sendAway = useGame((s) => s.sendAway)
  const active = TOOLS.find((t) => t.tool.kind === tool?.kind)

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-2 p-3">
      {problems && problems.length > 0 && (
        <div className="pointer-events-auto flex flex-wrap gap-1.5">
          {problems.map((p) => (
            <span key={p.id} className="chip gap-1.5 border border-slate-700 bg-slate-900/90 text-slate-200">
              {p.kind.replace('_', ' ')}{p.moving ? ' (moving)' : ''}
              {['bus', 'truck', 'car'].includes(p.kind) && (
                <button className="text-sky-300 hover:underline" onClick={() => sendAway(p.id)}>drive off</button>
              )}
              <button className="text-slate-400 hover:text-red-300" title="Remove" onClick={() => removeProblem(p.id)}>✕</button>
            </span>
          ))}
        </div>
      )}
      <div className="pointer-events-auto flex items-end gap-3 rounded-xl border border-slate-800 bg-slate-950/90 p-2 backdrop-blur">
        <div>
          <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Break something: pick, then click the street
          </div>
          <div className="flex gap-1">
            {TOOLS.map((t) => {
              const on = tool?.kind === t.tool.kind
              return (
                <button key={t.tool.kind} title={`${t.hint} (${t.cause})`}
                  onClick={() => setTool(on ? null : t.tool)}
                  className={`flex w-[72px] flex-col items-center rounded-lg border px-1 py-1.5 text-[11px] leading-tight transition
                    ${on ? 'border-amber-400 bg-amber-400/15 text-amber-200' : 'border-slate-800 bg-slate-900 text-slate-300 hover:border-slate-600'}`}>
                  <span className="text-xl">{t.icon}</span>
                  <span className="mt-0.5 text-center">{t.label}</span>
                </button>
              )
            })}
          </div>
        </div>
        <div className="ml-auto">
          <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Quick scenarios</div>
          <div className="grid grid-cols-2 gap-1">
            {SCENARIOS.map((s) => (
              <button key={s.label} onClick={() => s.problems.forEach((p) => void addProblem(p))}
                className="rounded-md border border-slate-800 bg-slate-900 px-2 py-1 text-left text-xs text-slate-300 hover:border-sky-500 hover:text-sky-200">
                ▶ {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {active && (
        <div className="pointer-events-none self-center rounded-full bg-amber-400 px-3 py-1 text-xs font-semibold text-amber-950 shadow">
          {active.icon} Click on the street to place: {active.hint.toLowerCase()} · Esc to cancel
        </div>
      )}
    </div>
  )
}
