import { Fragment, useEffect, useMemo, useState } from 'react'
import { kb, type AdviserAnswer, type AdviserPassage, type GapPassage, type GapReport, type GapTopic, type KbHit, type KbOverview, type Verdict } from '../api'
import { useGame, type PolicyTab } from '../store'
import ItuAlignment from './ItuAlignment'

/**
 * Policy & knowledge base: the gap analysis (what the host country's documents say about the problems our agent
 * runs into, the gaps, and how other jurisdictions and neighbouring countries handle them) and the knowledge base
 * it is built on. Every claim links to the exact passage it comes from.
 */

const SEV = {
  high: 'bg-red-500/20 text-red-300 ring-red-500/40',
  medium: 'bg-amber-500/20 text-amber-300 ring-amber-500/40',
  low: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40',
} as const
const TABS: [PolicyTab, string][] = [
  ['ask', 'Ask the adviser'], ['gaps', 'Gap analysis'], ['kb', 'Knowledge base'], ['itu', 'ITU alignment'],
]
const SCOPE_LABEL: Record<string, string> = {
  national: 'India (host country)', operator: 'Operator policy', standard: 'ITU-T standards',
  global: 'Global examples', regional: 'Neighbouring countries',
}
const SCOPE_TONE: Record<string, string> = {
  national: 'text-orange-300', operator: 'text-sky-300', standard: 'text-violet-300', global: 'text-emerald-300',
  regional: 'text-pink-300',
}

export default function PolicyPanel() {
  const open = useGame((s) => s.policyOpen)
  const setOpen = useGame((s) => s.setPolicyOpen)
  const tab = useGame((s) => s.policyTab)
  const setTab = (t: PolicyTab) => useGame.setState({ policyTab: t })
  const [report, setReport] = useState<GapReport | null>(null)
  const [overview, setOverview] = useState<KbOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    kb.gaps().then(setReport).catch((e) => setError(String(e.message ?? e)))
    kb.overview().then(setOverview).catch(() => {})
  }, [open])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-slate-950/97 backdrop-blur">
      <header className="flex items-center gap-4 border-b border-slate-800 px-5 py-3">
        <div>
          <div className="text-base font-bold text-slate-50">⚖ Policy &amp; knowledge base</div>
          <div className="text-xs text-slate-400">
            What the law and standards say about an AI agent running a 5G network, where they fall short, and how others handle it
          </div>
        </div>
        <div className="ml-6 flex overflow-hidden rounded-md border border-slate-700">
          {TABS.map(([t, label]) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1.5 text-sm ${tab === t ? 'bg-sky-500 text-sky-950' : 'text-slate-300 hover:bg-slate-800'}`}>
              {label}
            </button>
          ))}
        </div>
        <button className="btn ml-auto bg-slate-800 hover:bg-slate-700" onClick={() => setOpen(false)}>Close ✕</button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {error && tab === 'gaps' && <p className="p-6 text-sm text-red-300">{error}</p>}
        {tab === 'ask' && <Ask />}
        {tab === 'gaps' && <Gaps report={report} />}
        {tab === 'kb' && <Knowledge overview={overview} />}
        {tab === 'itu' && <ItuAlignment />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- ask the adviser

const VERDICT: Record<Verdict, { label: string; tone: string }> = {
  allowed: { label: 'Allowed', tone: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40' },
  conditional: { label: 'Allowed, with conditions', tone: 'bg-amber-500/15 text-amber-300 ring-amber-500/40' },
  'not allowed': { label: 'Not allowed', tone: 'bg-red-500/20 text-red-300 ring-red-500/40' },
  'not established': { label: 'Not established by the documents', tone: 'bg-slate-700/60 text-slate-200 ring-slate-500/40' },
}
const EXAMPLES = [
  'Can the agent move users onto the hospital tower during an emergency?',
  'Can the agent raise tower power without a person approving it?',
  'Who is accountable if an automatic network change causes an outage?',
  'Can the agent use people’s location data to fix the network?',
]

function Ask() {
  const sessionId = useGame((s) => s.sessionId)
  const incidents = useGame((s) => s.frame?.incidents) ?? []
  const chosen = useGame((s) => s.adviserIncident)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [answers, setAnswers] = useState<AdviserAnswer[]>([])
  const [shown, setShown] = useState(0)
  const [cite, setCite] = useState<string | null>(null)
  const ask = async (question: string) => {
    if (!question.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const a = await kb.ask(question, sessionId, chosen)
      setAnswers((xs) => [a, ...xs])
      setShown(0)
      setCite(null)
      setQ('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  const a = answers[shown]
  const sources = a ? Object.entries(a.passages).sort(([x], [y]) => Number(!a.cited.includes(x)) - Number(!a.cited.includes(y))) : []
  const p = a && cite ? a.passages[cite] : null
  return (
    <div className="grid h-full min-h-0 grid-cols-[1fr_380px]">
      <div className="overflow-y-auto p-6">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-2xl font-bold text-slate-50">Ask the policy and legal adviser</h2>
          <p className="mt-1 text-sm leading-relaxed text-slate-400">
            It answers only from the knowledge base, says which passages carry legal weight in India, and says
            “not established” when the documents don’t answer. It only advises: it has no way to change the network.
            Every question and answer is saved in the audit log.
          </p>
          <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <label className="text-xs text-slate-400">About
              <select value={chosen ?? ''} onChange={(e) => useGame.setState({ adviserIncident: e.target.value || null })}
                className="ml-2 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200">
                <option value="">a general question</option>
                {incidents.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.cause} {i.place} ({i.status})</option>)}
              </select>
            </label>
            <div className="mt-3 flex gap-2">
              <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void ask(q)}
                placeholder="e.g. Can the agent move users onto the hospital tower during an emergency?"
                className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500" />
              <button className="btn bg-sky-500 text-sky-950 hover:bg-sky-400" disabled={busy || !q.trim()} onClick={() => void ask(q)}>
                {busy ? 'Reading the documents…' : 'Ask'}
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {EXAMPLES.map((x) => (
                <button key={x} disabled={busy} onClick={() => { setQ(x); void ask(x) }}
                  className="chip bg-slate-800 text-left text-slate-300 hover:bg-slate-700 hover:text-slate-100">{x}</button>
              ))}
            </div>
          </div>
          {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
          {a && <AnswerCard a={a} onCite={setCite} />}
          {answers.length > 1 && (
            <div className="mt-6">
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Earlier questions</div>
              <ul className="space-y-1">
                {answers.map((x, i) => i !== shown && (
                  <li key={i}>
                    <button onClick={() => { setShown(i); setCite(null) }} className="w-full rounded-md bg-slate-900/70 px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800">
                      <span className={`chip mr-2 ring-1 ${VERDICT[x.verdict].tone}`}>{x.verdict}</span>{x.question}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
      <aside className="overflow-y-auto border-l border-slate-800 bg-slate-900/40 p-4">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{p ? `Source of ${cite}` : 'Passages it was given'}</div>
        {!a && <p className="text-xs text-slate-500">Ask a question to see the passages behind the answer.</p>}
        {p ? <PassageCard n={cite!} p={p} onBack={() => setCite(null)} /> : (
          <ul className="space-y-1.5">
            {sources.map(([n, x]) => (
              <li key={n}>
                <button onClick={() => setCite(n)} className={`w-full rounded-md p-2 text-left text-xs hover:bg-slate-800 ${a.cited.includes(n) ? 'bg-slate-800/80 ring-1 ring-sky-700' : 'bg-slate-900'}`}>
                  <span className={`mr-1 font-semibold ${SCOPE_TONE[x.scope] ?? ''}`}>{n}</span>
                  <span className="text-slate-300">{x.title}</span><span className="text-slate-500">, p. {x.page}</span>
                  <div className="text-[10px] text-slate-400">{x.authority}{a.cited.includes(n) ? ' · cited' : ''}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  )
}

function AnswerCard({ a, onCite }: { a: AdviserAnswer; onCite: (n: string) => void }) {
  const v = VERDICT[a.verdict]
  const about = a.incident as { id?: string; cause?: string; place?: string } | null
  return (
    <article className="mt-5 rounded-xl border border-slate-700 bg-slate-900/80 p-5">
      <div className="text-sm text-slate-400">“{a.question}”{about?.id && <span className="ml-2 chip bg-slate-800 text-slate-300">about {about.id}: {about.cause} {about.place}</span>}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className={`chip text-sm ring-1 ${v.tone}`}>{v.label}</span>
        <span className="chip bg-slate-800 text-slate-400">confidence {a.confidence}</span>
        <span className="text-[11px] text-slate-500">{a.method}</span>
      </div>
      <p className="mt-3 text-[15px] leading-relaxed text-slate-100"><Cited text={a.answer} passages={a.passages} onCite={onCite} /></p>
      {a.conditions.length > 0 && (
        <Section title="Conditions" tone="text-amber-300">
          <ul className="list-disc space-y-1 pl-5">{a.conditions.map((c, i) => <li key={i}><Cited text={c} passages={a.passages} onCite={onCite} /></li>)}</ul>
        </Section>
      )}
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-slate-950/60 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-sky-300">Who is responsible</div>
          <div className="mt-1 text-sm text-slate-200"><Cited text={a.responsible} passages={a.passages} onCite={onCite} /></div>
        </div>
        <div className="rounded-lg bg-slate-950/60 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-300">What the team should do</div>
          <div className="mt-1 text-sm text-slate-200">{a.recommended_action ? <Cited text={a.recommended_action} passages={a.passages} onCite={onCite} /> : '–'}</div>
        </div>
      </div>
      {a.elsewhere && (
        <Section title="Elsewhere (does not apply in India)" tone="text-emerald-300">
          <Cited text={a.elsewhere} passages={a.passages} onCite={onCite} />
        </Section>
      )}
      {a.note && <p className="mt-3 rounded-md bg-amber-500/10 p-2 text-xs text-amber-200">{a.note}</p>}
    </article>
  )
}

// ---------------------------------------------------------------- gap analysis

function Gaps({ report }: { report: GapReport | null }) {
  const [sel, setSel] = useState<string | null>(null)
  const order = { high: 0, medium: 1, low: 2 }
  const topics = useMemo(() => [...(report?.topics ?? [])].sort((a, b) => order[a.severity] - order[b.severity]),
    [report]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!report) return <p className="p-6 text-sm text-slate-400">Loading the gap analysis…</p>
  const current = topics.find((t) => t.id === sel) ?? topics[0]
  const counts = topics.reduce<Record<string, number>>((a, t) => {
    for (const g of new Set(t.gaps.map((x) => x.type))) a[g] = (a[g] ?? 0) + 1
    return a
  }, {})
  return (
    <div className="grid h-full grid-cols-[360px_1fr]">
      <aside className="overflow-y-auto border-r border-slate-800 p-3">
        <p className="mb-3 px-1 text-xs leading-relaxed text-slate-400">
          {topics.length} questions our agent runs into, each checked against India’s documents, ITU-T standards, global
          examples (EU, US, Singapore) and neighbouring countries (Sri Lanka, Bangladesh, Nepal).
        </p>
        <div className="mb-3 flex flex-wrap gap-1 px-1">
          {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([t, n]) => (
            <span key={t} className="chip bg-slate-800 text-slate-300">{t} · {n}</span>
          ))}
        </div>
        <ul className="space-y-1.5">
          {topics.map((t) => (
            <li key={t.id}>
              <button onClick={() => setSel(t.id)}
                className={`w-full rounded-lg border p-2.5 text-left transition ${t.id === current?.id ? 'border-sky-500 bg-sky-500/10' : 'border-slate-800 bg-slate-900/60 hover:border-slate-600'}`}>
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-slate-100">{t.title}</span>
                  <span className={`chip shrink-0 ring-1 ${SEV[t.severity]}`}>{t.severity}</span>
                </div>
                <div className="mt-1 text-[11px] text-slate-400">{[...new Set(t.gaps.map((g) => g.type))].join(' · ') || 'no gap found'}</div>
                <div className="mt-1.5 flex items-center gap-2 text-[10px] text-slate-500">
                  <span>India coverage</span>
                  <div className="h-1 flex-1 rounded bg-slate-800"><div className="h-1 rounded bg-orange-400" style={{ width: `${Math.min(100, t.national_coverage * 100)}%` }} /></div>
                  <span>{[...new Set([...t.global_examples, ...t.regional].map((e) => e.jurisdiction))].length} jurisdictions</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-3 px-1 text-[11px] leading-relaxed text-slate-500">
          Method: {report.method}. A gap means “not covered by the documents in this knowledge base”; confirm with a lawyer
          before relying on it. Full report: docs/gap_analysis.md.
        </p>
      </aside>
      {current && <Topic t={current} />}
    </div>
  )
}

/** Text with [P3] / (P3, P4) citations turned into clickable passage chips. */
type CitePassages = Record<string, { title: string; page: number; scope: string }>

function Cited({ text, passages, onCite }: { text: string; passages: CitePassages; onCite: (n: string) => void }) {
  const parts = text.split(/(\[?\(?P\d+(?:,\s*P\d+)*\)?\]?)/g)
  return (
    <>
      {parts.map((part, i) => {
        const nums = part.match(/P\d+/g)
        if (!nums || !/^[[(]?P\d+/.test(part)) return <Fragment key={i}>{part}</Fragment>
        return (
          <span key={i} className="whitespace-nowrap">
            {nums.filter((n) => passages[n]).map((n) => (
              <button key={n} onClick={() => onCite(n)} title={`${passages[n].title}, p. ${passages[n].page}`}
                className={`mx-0.5 rounded px-1 text-[11px] font-semibold ring-1 ring-slate-600 hover:bg-slate-700 ${SCOPE_TONE[passages[n].scope] ?? ''}`}>
                {n}
              </button>
            ))}
          </span>
        )
      })}
    </>
  )
}

function Topic({ t }: { t: GapTopic }) {
  const [cite, setCite] = useState<string | null>(null)
  useEffect(() => setCite(null), [t.id])
  const p = cite ? t.passages[cite] : null
  return (
    <div className="grid min-h-0 grid-cols-[1fr_380px] gap-0">
      <article className="overflow-y-auto p-6">
        <div className="flex items-center gap-2">
          <span className={`chip ring-1 ${SEV[t.severity]}`}>{t.severity} severity</span>
          <span className="chip bg-slate-800 text-slate-400">confidence {t.confidence}</span>
        </div>
        <h2 className="mt-2 text-2xl font-bold text-slate-50">{t.title}</h2>
        <p className="mt-2 text-[15px] text-slate-300"><b className="text-slate-100">Question.</b> {t.question}</p>
        <div className="mt-3 rounded-lg border border-sky-800/60 bg-sky-950/30 p-3 text-sm text-sky-100">
          <b>Where our agent meets it.</b> {t.seen_in}
        </div>

        <Section title="What India’s documents say" tone="text-orange-300">
          <Cited text={t.national_position} passages={t.passages} onCite={setCite} />
        </Section>

        {t.gaps.length > 0 && (
          <Section title="Gaps" tone="text-red-300">
            <ul className="space-y-2">
              {t.gaps.map((g, i) => (
                <li key={i}><span className="chip mr-2 bg-red-500/15 text-red-300">{g.type}</span><Cited text={g.summary} passages={t.passages} onCite={setCite} /></li>
              ))}
            </ul>
          </Section>
        )}
        {t.conflicts && (
          <Section title="Conflicting objectives" tone="text-amber-300"><Cited text={t.conflicts} passages={t.passages} onCite={setCite} /></Section>
        )}
        {t.global_examples.length > 0 && (
          <Section title="How others handle it" tone="text-emerald-300">
            <Examples items={t.global_examples} t={t} onCite={setCite} />
          </Section>
        )}
        {t.regional.length > 0 && (
          <Section title="Neighbouring countries" tone="text-pink-300">
            <Examples items={t.regional} t={t} onCite={setCite} />
          </Section>
        )}
        {t.recommendation && (
          <Section title="What a rule or standard should clarify" tone="text-sky-300">
            <Cited text={t.recommendation} passages={t.passages} onCite={setCite} />
          </Section>
        )}
      </article>
      <aside className="overflow-y-auto border-l border-slate-800 bg-slate-900/40 p-4">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          {p ? `Source of ${cite}` : 'Sources'}
        </div>
        {p ? (
          <PassageCard n={cite!} p={p} onBack={() => setCite(null)} />
        ) : (
          <ul className="space-y-1.5">
            {Object.entries(t.passages).map(([n, x]) => (
              <li key={n}>
                <button onClick={() => setCite(n)} className="w-full rounded-md bg-slate-900 p-2 text-left text-xs hover:bg-slate-800">
                  <span className={`mr-1 font-semibold ${SCOPE_TONE[x.scope] ?? ''}`}>{n}</span>
                  <span className="text-slate-300">{x.title}</span>
                  <span className="text-slate-500">, p. {x.page}</span>
                  <div className="text-[10px] text-slate-500">{SCOPE_LABEL[x.scope] ?? x.scope} · {x.country}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  )
}

function Section({ title, tone, children }: { title: string; tone: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className={`mb-1.5 text-xs font-semibold uppercase tracking-wider ${tone}`}>{title}</h3>
      <div className="text-[15px] leading-relaxed text-slate-200">{children}</div>
    </section>
  )
}

function Examples({ items, t, onCite }: { items: GapTopic['global_examples']; t: GapTopic; onCite: (n: string) => void }) {
  return (
    <ul className="space-y-2">
      {items.map((e, i) => (
        <li key={i} className="rounded-lg bg-slate-900/70 p-2.5">
          <div className="text-xs text-slate-400">
            <b className="text-slate-200">{e.jurisdiction}</b> · {e.title}, p. {e.page}
            <button onClick={() => onCite(e.passage)} className="ml-2 rounded px-1 text-[11px] font-semibold text-sky-300 ring-1 ring-slate-600 hover:bg-slate-700">
              {e.passage}
            </button>
          </div>
          <div className="mt-0.5 text-sm text-slate-200"><Cited text={e.what_it_does} passages={t.passages} onCite={onCite} /></div>
        </li>
      ))}
    </ul>
  )
}

function PassageCard({ n, p, onBack }: { n: string; p: GapPassage | AdviserPassage; onBack: () => void }) {
  return (
    <div>
      <button onClick={onBack} className="mb-2 text-xs text-sky-400 hover:underline">← all sources</button>
      <div className={`text-sm font-semibold ${SCOPE_TONE[p.scope] ?? ''}`}>{n} · {SCOPE_LABEL[p.scope] ?? p.scope}</div>
      {'authority' in p && <div className="mt-0.5 text-xs font-medium text-slate-300">{p.authority}</div>}
      <div className="mt-1 text-sm text-slate-100">{p.title}</div>
      <div className="text-xs text-slate-400">page {p.page} · {p.country} · similarity {p.score.toFixed(2)}</div>
      <blockquote className="mt-3 border-l-2 border-slate-600 pl-3 text-[13px] italic leading-relaxed text-slate-300">“{p.excerpt}…”</blockquote>
      {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="mt-3 inline-block text-xs text-sky-400 hover:underline">Open the official document ↗</a>}
    </div>
  )
}

// ---------------------------------------------------------------- knowledge base

function Knowledge({ overview }: { overview: KbOverview | null }) {
  const [q, setQ] = useState('')
  const [scope, setScope] = useState('')
  const [hits, setHits] = useState<KbHit[] | null>(null)
  const [busy, setBusy] = useState(false)
  const search = async () => {
    if (!q.trim()) return
    setBusy(true)
    try { setHits(await kb.search(q, scope || undefined)) } finally { setBusy(false) }
  }
  if (!overview) return <p className="p-6 text-sm text-slate-400">Loading the knowledge base…</p>
  const groups = ['national', 'operator', 'standard', 'global', 'regional']
  const ev = overview.evaluation
  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="grid grid-cols-4 gap-3">
        <Stat label="documents" value={String(overview.documents.filter((d) => d.passages).length)} />
        <Stat label="passages indexed" value={String(overview.passages)} />
        <Stat label="right document in top 3 (all documents)" value={ev ? `${Math.round(ev.recall_at['3'] * 100)}%` : '–'} />
        <Stat label="right document in top 3 (within its group, as the agents search)" value={ev ? `${Math.round(ev.scoped_recall_at_3 * 100)}%` : '–'} />
      </div>
      {ev && <p className="mt-2 text-xs text-slate-500">Retrieval test: {ev.questions} hand-written questions with known answers (config/kb_eval.yaml, report in docs/kb_report.md). Mean reciprocal rank {ev.mrr.toFixed(2)}.</p>}

      <div className="mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="text-sm font-semibold text-slate-100">Search the knowledge base</div>
        <div className="mt-2 flex gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void search()}
            placeholder="e.g. Can traffic be prioritised during a public emergency?"
            className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500" />
          <select value={scope} onChange={(e) => setScope(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-200">
            <option value="">All documents</option>
            {groups.map((g) => <option key={g} value={g}>{SCOPE_LABEL[g]}</option>)}
          </select>
          <button className="btn bg-sky-500 text-sky-950 hover:bg-sky-400" disabled={busy} onClick={() => void search()}>
            {busy ? 'Searching…' : 'Search'}
          </button>
        </div>
        {hits && (
          <ul className="mt-3 space-y-2">
            {hits.length === 0 && <li className="text-sm text-slate-500">Nothing found.</li>}
            {hits.map((h) => (
              <li key={h.id} className="rounded-lg bg-slate-950/70 p-3">
                <div className="text-xs">
                  <span className={`font-semibold ${SCOPE_TONE[h.scope] ?? ''}`}>{SCOPE_LABEL[h.scope] ?? h.scope}</span>
                  <span className="text-slate-400"> · {h.title}, p. {h.page} · similarity {h.score.toFixed(2)}</span>
                  {h.url && <a href={h.url} target="_blank" rel="noreferrer" className="ml-2 text-sky-400 hover:underline">source ↗</a>}
                </div>
                <p className="mt-1 text-sm leading-relaxed text-slate-300">{h.text.slice(0, 600)}{h.text.length > 600 ? '…' : ''}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {groups.map((g) => {
        const docs = overview.documents.filter((d) => (d.scope ?? 'national') === g)
        if (!docs.length) return null
        return (
          <section key={g} className="mt-6">
            <h3 className={`mb-2 text-xs font-semibold uppercase tracking-wider ${SCOPE_TONE[g]}`}>{SCOPE_LABEL[g]}</h3>
            <div className="overflow-hidden rounded-lg border border-slate-800">
              <table className="w-full text-sm">
                <tbody>
                  {docs.map((d) => (
                    <tr key={d.id} className="border-b border-slate-800 last:border-0">
                      <td className="p-2.5 text-slate-200">
                        {d.url ? <a href={d.url} target="_blank" rel="noreferrer" className="hover:underline">{d.title}</a> : d.title}
                        <div className="text-[11px] text-slate-500">{d.publisher} · {d.kind}{d.sha256 ? ` · sha256 ${d.sha256.slice(0, 12)}…` : ''}</div>
                      </td>
                      <td className="w-28 p-2.5 text-xs text-slate-400">{d.country}</td>
                      <td className="w-28 p-2.5 text-right font-mono text-xs text-slate-300">{d.passages} passages</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )
      })}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
      <div className="font-mono text-2xl text-slate-50">{value}</div>
      <div className="text-[11px] leading-tight text-slate-400">{label}</div>
    </div>
  )
}
