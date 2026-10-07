import type { NewProblem, Problem } from '../api'
import { BOX_KINDS, useGame, type Tool } from '../store'

const KIND_ICON: Record<string, string> = {
  bus: '🚌', truck: '🚚', car: '🚗', crowd: '👥', kiosk: '🏪', hoarding: '🪧', stuck_beam: '🔦',
  neighbour_misconfig: '📡', external_interferer: '📶', crowd_surge: '🏟️',
}
const KIND_NAME: Record<string, string> = {
  stuck_beam: 'Misaimed beams', neighbour_misconfig: 'Bad tower settings', external_interferer: 'Illegal booster',
  crowd_surge: 'Crowd surge',
}

/** One problem on the street, with controls: move blockers along the road, send vehicles away, remove. */
function ProblemChip({ p }: { p: Problem }) {
  const movable = useGame((s) => s.movable)
  const setMovable = useGame((s) => s.setMovable)
  const nudge = useGame((s) => s.nudge)
  const removeProblem = useGame((s) => s.removeProblem)
  const sendAway = useGame((s) => s.sendAway)
  const canMove = BOX_KINDS.has(p.kind) && p.x != null
  const selected = canMove && movable === p.id
  const move = (dx: number) => { setMovable(p.id); void nudge(dx) }
  const name = KIND_NAME[p.kind] ?? p.kind[0].toUpperCase() + p.kind.slice(1)
  return (
    <div data-tour={canMove ? 'vehicle' : undefined} onClick={() => canMove && setMovable(p.id)}
      className={`flex items-center gap-1 rounded-lg border px-2 py-1 text-xs backdrop-blur
        ${selected ? 'border-amber-400 bg-amber-950/80 text-amber-100' : 'border-slate-700 bg-slate-900/90 text-slate-200'}`}>
      <span className="text-sm">{KIND_ICON[p.kind] ?? '⚠'}</span>
      <span className="mr-1 font-medium">{name}{p.moving ? ' · driving' : ''}</span>
      {canMove && (
        <>
          <MoveBtn label="◀◀" title="Back 20 m" onClick={() => move(-20)} />
          <MoveBtn label="◀" title="Back 5 m (← key)" onClick={() => move(-5)} />
          <MoveBtn label="▶" title="Forward 5 m (→ key)" onClick={() => move(5)} />
          <MoveBtn label="▶▶" title="Forward 20 m" onClick={() => move(20)} />
        </>
      )}
      {['bus', 'truck', 'car'].includes(p.kind) && (
        <button className="ml-1 rounded px-1.5 py-0.5 text-sky-300 hover:bg-slate-800" onClick={(e) => { e.stopPropagation(); void sendAway(p.id) }}>
          drive off
        </button>
      )}
      <button className="rounded px-1 text-slate-400 hover:bg-slate-800 hover:text-red-300" title="Remove"
        onClick={(e) => { e.stopPropagation(); void removeProblem(p.id) }}>✕</button>
    </div>
  )
}

function MoveBtn({ label, title, onClick }: { label: string; title: string; onClick: () => void }) {
  return (
    <button title={title} onClick={(e) => { e.stopPropagation(); onClick() }}
      className="grid h-6 min-w-6 place-items-center rounded bg-slate-800 px-1 font-mono text-[11px] hover:bg-slate-700 active:bg-sky-600">
      {label}
    </button>
  )
}

interface ToolDef { tool: NonNullable<Tool>; icon: string; label: string; hint: string; cause: string }

const TOOLS: ToolDef[] = [
  { tool: { kind: 'bus', drive: true }, icon: '🚌', label: 'Bus', hint: 'Parks where you click; move it with ◀ ▶', cause: 'blockage' },
  { tool: { kind: 'truck', drive: true }, icon: '🚚', label: 'Truck', hint: 'Parks where you click; move it with ◀ ▶', cause: 'blockage' },
  { tool: { kind: 'car', drive: true }, icon: '🚗', label: 'Car', hint: 'Small and low: blocks only phones right behind it', cause: 'blockage' },
  { tool: { kind: 'crowd' }, icon: '👥', label: 'Crowd', hint: 'People standing in the signal path', cause: 'blockage' },
  { tool: { kind: 'hoarding' }, icon: '🪧', label: 'Hoarding', hint: 'A new advertising board', cause: 'blockage' },
  { tool: { kind: 'stuck_beam' }, icon: '🔦', label: 'Stuck beam', hint: 'Nearby phones get a badly aimed beam', cause: 'wrong beam' },
  { tool: { kind: 'misconfig' }, icon: '📡', label: 'Bad tower settings', hint: 'Click near a tower: too loud, tilted up', cause: 'interference' },
  { tool: { kind: 'booster' }, icon: '📶', label: 'Illegal booster', hint: 'Outside noise no setting can fix', cause: 'interference' },
  { tool: { kind: 'crowd_surge' }, icon: '🏟️', label: 'Crowd surge', hint: '60 people arrive and all want data', cause: 'congestion' },
]

const SCENARIOS: { label: string; problems: NewProblem[] }[] = [
  { label: 'Bus at the bus stop', problems: [{ kind: 'bus', x: 211, y: 107.8 }] },
  { label: 'Stuck beams at the bus stop', problems: [{ kind: 'stuck_beam', x: 233, y: 115 }] },
  { label: 'Tower C misconfigured', problems: [{ kind: 'misconfig', tower: 2 }] },
  { label: 'Crowd surge on the street', problems: [{ kind: 'crowd_surge', x: 140, y: 100, people: 40 }] },
]

export default function Toolbar() {
  const tool = useGame((s) => s.tool)
  const setTool = useGame((s) => s.setTool)
  const addProblem = useGame((s) => s.addProblem)
  const problems = useGame((s) => s.frame?.problems)
  const active = TOOLS.find((t) => t.tool.kind === tool?.kind)

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex flex-col gap-2 p-3">
      {problems && problems.length > 0 && (
        <div className="pointer-events-auto flex flex-wrap items-center gap-1.5">
          {problems.map((p) => <ProblemChip key={p.id} p={p} />)}
        </div>
      )}
      <div data-tour="toolbar" className="pointer-events-auto flex flex-wrap items-end gap-3 rounded-xl border border-slate-800 bg-slate-950/90 p-2 backdrop-blur">
        <div>
          <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Create a problem: pick one, then click on the street
          </div>
          <div className="flex flex-wrap gap-1">
            {TOOLS.map((t) => {
              const on = tool?.kind === t.tool.kind
              return (
                <button key={t.tool.kind} title={`${t.hint} (${t.cause})`}
                  onClick={() => setTool(on ? null : t.tool)}
                  className={`flex w-[64px] flex-col xl:w-[72px] items-center rounded-lg border px-1 py-1.5 text-[11px] leading-tight transition
                    ${on ? 'border-amber-400 bg-amber-400/15 text-amber-200' : 'border-slate-800 bg-slate-900 text-slate-300 hover:border-slate-600'}`}>
                  <span className="text-xl">{t.icon}</span>
                  <span className="mt-0.5 text-center">{t.label}</span>
                </button>
              )
            })}
          </div>
        </div>
        <div data-tour="scenarios" className="ml-auto">
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
