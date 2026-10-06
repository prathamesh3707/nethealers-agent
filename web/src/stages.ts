// The agent's loop as the side panel draws it. Each backend event "stage" belongs to one step.

export interface Step { key: string; label: string; who: string; stages: string[]; color: string }

export const STEPS: Step[] = [
  { key: 'observe', label: 'Observe', who: 'Monitor', stages: ['detect', 'note'], color: '#38bdf8' },
  { key: 'diagnose', label: 'Diagnose', who: 'LWM + classifier', stages: ['diagnose'], color: '#a78bfa' },
  { key: 'twin', label: 'Rehearse', who: 'Digital twin', stages: ['rehearse'], color: '#2dd4bf' },
  { key: 'plan', label: 'Plan', who: 'Planner', stages: ['plan'], color: '#818cf8' },
  { key: 'safety', label: 'Safety', who: 'Rule-checker + adviser', stages: ['check', 'review'], color: '#fbbf24' },
  { key: 'human', label: 'Operator', who: 'You', stages: ['escalate', 'approve'], color: '#fb923c' },
  { key: 'act', label: 'Act', who: 'Executor', stages: ['act', 'withdraw'], color: '#4ade80' },
  { key: 'verify', label: 'Verify', who: 'Verifier', stages: ['verify', 'undo', 'resolve'], color: '#f472b6' },
]

const BY_STAGE = new Map<string, Step>()
for (const s of STEPS) for (const st of s.stages) BY_STAGE.set(st, s)

export const stepOf = (stage: string): Step => BY_STAGE.get(stage) ?? STEPS[0]

export const STAGE_LABEL: Record<string, string> = {
  detect: 'detect', note: 'note', diagnose: 'diagnose', rehearse: 'rehearse', plan: 'plan', check: 'check',
  review: 'review', escalate: 'ask', approve: 'answer', act: 'act', withdraw: 'withdraw', verify: 'verify',
  undo: 'undo', resolve: 'resolve',
}

export const BAND_COLOR = { good: '#22c55e', fair: '#f59e0b', poor: '#ef4444' } as const

export const CAUSE_LABEL: Record<string, string> = {
  blockage: 'Blockage', wrong_beam: 'Wrong beam', interference: 'Interference', congestion: 'Congestion',
  none: 'Normal variation', unknown: 'Unknown',
}

export const STATUS_LABEL: Record<string, string> = {
  new: 'planning', verifying: 'checking result', waiting_human: 'waiting for you', escalated: 'handed to operator',
  fixed: 'fixed', closing: 'withdrawing', resolved: 'closed', false_alarm: 'false alarm',
}

export function clock(tick: number): string {
  const m = Math.floor(tick / 60)
  const s = tick % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function ms(v: number): string {
  if (v >= 1000) return `${(v / 1000).toFixed(1)} s`
  if (v >= 10) return `${Math.round(v)} ms`
  return `${v.toFixed(1)} ms`
}
