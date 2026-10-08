// Types and calls for the Python game backend (src/nethealers/api/app.py).

export type Band = 'good' | 'fair' | 'poor'

export interface Building { name: string; x0: number; x1: number; y0: number; y1: number; height: number; material: string }
export interface Zone { name: string; x0: number; x1: number; y0: number; y1: number; tower: number; max_load: number }
export interface Scene {
  name: string
  extent: [number, number, number, number]
  buildings: Building[]
  zones: Zone[]
  beam_angles: number[]
  problem_kinds: string[]
}

export interface Phone {
  id: number; x: number; y: number; tower: number; beam_az: number; sinr: number; band: Band
  group: string; mbps: number; wants_mbps: number
}
export interface Tower {
  id: number; name: string; x: number; y: number; z: number; boresight: number; tilt: number
  power_dbm: number; load: number
}
export interface Blocker { id: string; kind: string; x0: number; x1: number; y0: number; y1: number; height: number; hidden: boolean }
export interface Problem { id: string; label: string; kind: string; x: number | null; y: number | null; moving: boolean }
export interface Incident {
  id: string; status: string; cause: string; confidence: number; probs: Record<string, number>
  phones: number[]; place: string; outcome: string | null; opened: number; closed: number | null
  stage: string; stage_tick: number; attempts: number; kept: number; decision_ms: number
  waiting_for_you: boolean; pending: string | null; pending_reasons: string[]
}
export interface AgentEvent {
  tick: number; stage: string; agent: string; text: string; incident: string | null
  data: Record<string, unknown>; ms: number
}
export interface Score {
  good: number; fair: number; poor: number; degraded_now: number; phones_rescued: number
  fixes_applied: number; fixes_undone: number; asked_you: number
}
export interface Frame {
  tick: number; paused: boolean; speed: number
  phones: Phone[]; towers: Tower[]; blockers: Blocker[]; problems: Problem[]; incidents: Incident[]
  events: AgentEvent[]; score: Score
  timing: { tick_ms: number; agent_ms: number }
  llm: { live: boolean; providers?: string[]; calls?: number; tokens_in?: number; tokens_out?: number }
  error: string | null
  without_agent: { good: number; fair: number; poor: number; degraded_now: number } | null
}

export interface NewGame { language_model: boolean; speed: number; auto_approve_after?: number | null; start_paused?: boolean }
export interface NewProblem {
  kind: string; x?: number; y?: number; drive?: boolean; stay?: number; tower?: number; people?: number
  along_y?: boolean; hidden?: boolean
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not JSON */ }
    throw new ApiError(r.status, String(detail))
  }
  return r.json() as Promise<T>
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export const api = {
  newGame: (g: NewGame) =>
    call<{ id: string; scene: Scene; state: Frame; language_model: boolean }>('POST', '/sessions', g),
  scene: (id: string) => call<Scene>('GET', `/sessions/${id}/scene`),
  state: (id: string) => call<Frame>('GET', `/sessions/${id}/state`),
  events: (id: string) => call<AgentEvent[]>('GET', `/sessions/${id}/events`),
  incident: (id: string, inc: string) => call<{ events: AgentEvent[] }>('GET', `/sessions/${id}/incidents/${inc}`),
  roles: (id: string, inc: string) => call<Coordination>('GET', `/sessions/${id}/incidents/${inc}/roles`),
  addProblem: (id: string, p: NewProblem) =>
    call<{ id: string; x?: number; y?: number }>('POST', `/sessions/${id}/problems`, p),
  removeProblem: (id: string, pid: string) => call('DELETE', `/sessions/${id}/problems/${pid}`),
  moveProblem: (id: string, pid: string, x: number, y: number) =>
    call('POST', `/sessions/${id}/problems/${pid}/move`, { x, y }),
  sendAway: (id: string, pid: string) => call('POST', `/sessions/${id}/problems/${pid}/leave`),
  control: (id: string, action: string, value?: number) =>
    call('POST', `/sessions/${id}/control`, { action, value }),
  answer: (id: string, incident: string, decision: 'approve' | 'reject') =>
    call('POST', `/sessions/${id}/answer`, { incident, decision }),
  stop: (id: string) => call('DELETE', `/sessions/${id}`),
}

export interface KbDoc {
  id: string; title: string; publisher?: string; kind: string; scope?: string; country?: string; url?: string
  passages: number; sha256?: string
}
export interface KbHit {
  id: string; doc_id: string; title: string; page: number; score: number; kind: string; scope: string
  country: string; url: string; text: string
}
export interface GapPassage {
  group: string; passage_id: string; doc_id: string; title: string; page: number; score: number; scope: string
  country: string; url: string; excerpt: string
}
export interface GapExample { passage: string; jurisdiction: string; title: string; page: number; what_it_does: string }
export interface GapTopic {
  id: string; title: string; question: string; seen_in: string; national_coverage: number
  passages: Record<string, GapPassage>; national_position: string; gaps: { type: string; summary: string }[]
  conflicts: string; severity: 'high' | 'medium' | 'low'; global_examples: GapExample[]; regional: GapExample[]
  recommendation: string; confidence: string; method: string
}
export interface GapReport { topics: GapTopic[]; documents: KbDoc[]; gap_types: string[]; method: string }
export interface KbOverview {
  documents: KbDoc[]; passages: number
  evaluation: { questions: number; recall_at: Record<string, number>; mrr: number; scoped_recall_at_3: number } | null
}

export type RoleId = 'noc' | 'planner' | 'regulator' | 'person'
export interface Coordination {
  roles: { id: RoleId; name: string; mandate: string; sees: string; cannot: string }[]
  messages: { role: RoleId; t: number; tick: number; stage: string; text: string }[]
  handovers: { from: RoleId; to: RoleId; t: number }[]
  first_heard: Partial<Record<RoleId, number>>
  opened_tick: number
}

export interface AdviserPassage extends GapPassage { authority: string }
export type Verdict = 'allowed' | 'conditional' | 'not allowed' | 'not established'
export interface AdviserAnswer {
  question: string; verdict: Verdict; answer: string; conditions: string[]; responsible: string
  recommended_action: string; elsewhere: string; confidence: 'high' | 'medium' | 'low'; cited: string[]; note: string
  method: string; passages: Record<string, AdviserPassage>; incident: Record<string, unknown> | null
}

export interface AlignmentSource {
  id: string; missing?: boolean; title?: string; page?: number; url?: string; authority?: string; excerpt?: string
}
export interface Alignment {
  y3172: { node: string; ours: string; code: string; evidence: string; status: string; note?: string }[]
  y3173: { dimension: string; who: string; ours: string }[]
  ai_ready: { dimension: string; ours: string; status: string; note?: string }[]
  policy_to_control: {
    id: string; policy: string; actor: string; standard: string; control: string; code: string; test: string
    status: string; note?: string; sources: AlignmentSource[]
  }[]
}

export const kb = {
  overview: () => call<KbOverview>('GET', '/kb'),
  search: (q: string, scope?: string) =>
    call<KbHit[]>('GET', `/kb/search?q=${encodeURIComponent(q)}${scope ? `&scope=${scope}` : ''}&k=8`),
  gaps: () => call<GapReport>('GET', '/gaps'),
  alignment: () => call<Alignment>('GET', '/alignment'),
  ask: (question: string, sessionId?: string | null, incidentId?: string | null) =>
    call<AdviserAnswer>('POST', '/adviser', { question, session_id: sessionId ?? null, incident_id: incidentId ?? null }),
}

export function liveUrl(id: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/sessions/${id}/live`
}
