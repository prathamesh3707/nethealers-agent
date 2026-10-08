import { useEffect, useState } from 'react'
import { kb, type Alignment, type AlignmentSource } from '../api'

/**
 * How NetHealers lines up with ITU-T Y.3172 (the ML pipeline), Y.3173 (who does what), the ITU AI Ready framework,
 * and how each policy requirement becomes a control, a test and evidence. Read from config/itu_alignment.yaml;
 * the quoted passages come live from the knowledge base. A mapping for discussion, not a claim of conformance.
 */

const STATUS: Record<string, string> = {
  demonstrated: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40',
  partial: 'bg-amber-500/15 text-amber-300 ring-amber-500/40',
  simulated: 'bg-sky-500/15 text-sky-300 ring-sky-500/40',
  planned: 'bg-slate-700/60 text-slate-300 ring-slate-500/40',
}
const WHO: Record<string, string> = {
  Human: 'text-amber-300', 'Human and system': 'text-sky-300', System: 'text-emerald-300',
}

function Status({ s }: { s: string }) {
  return <span className={`chip shrink-0 ring-1 ${STATUS[s] ?? STATUS.planned}`}>{s}</span>
}

function H({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mb-3 mt-8 first:mt-0">
      <h2 className="text-lg font-bold text-slate-50">{title}</h2>
      <p className="text-xs text-slate-400">{sub}</p>
    </div>
  )
}

export default function ItuAlignment() {
  const [data, setData] = useState<Alignment | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { kb.alignment().then(setData).catch((e) => setError(String(e.message ?? e))) }, [])
  if (error) return <p className="p-6 text-sm text-red-300">{error}</p>
  if (!data) return <p className="p-6 text-sm text-slate-400">Loading the ITU alignment…</p>
  const pipeline = data.y3172.filter((r) => /^(SRC|C|PP|M|P|D|SINK)\b/.test(r.node))
  return (
    <div className="mx-auto max-w-6xl p-6">
      <p className="mb-6 rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-xs leading-relaxed text-slate-400">
        A mapping for discussion, not a claim of ITU conformance. Every row names the code that does it and where to
        see it working. Status: <Status s="demonstrated" /> works and is tested, <Status s="partial" /> works with a
        stated limit, <Status s="simulated" /> works against the simulator, not a live network, <Status s="planned" /> not built yet.
      </p>

      <H title="ITU-T Y.3172: our ML pipeline, node by node" sub="Source → collector → preprocessor → model → policy → distributor → sink, plus the orchestrator, intent and sandbox" />
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {pipeline.map((r, i) => (
          <span key={r.node} className="flex items-center gap-1.5">
            <span className={`rounded-md px-2 py-1 text-xs font-semibold ring-1 ${STATUS[r.status] ?? STATUS.planned}`}>{r.node.split(' ')[0]}</span>
            {i < pipeline.length - 1 && <span className="text-slate-600">→</span>}
          </span>
        ))}
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-[11px] uppercase tracking-wider text-slate-400">
            <tr><th className="p-2.5">Y.3172 node</th><th className="p-2.5">In NetHealers</th><th className="p-2.5">Code</th><th className="p-2.5">Where to see it</th><th className="p-2.5">Status</th></tr>
          </thead>
          <tbody>
            {data.y3172.map((r) => (
              <tr key={r.node} className="border-t border-slate-800 align-top">
                <td className="w-44 p-2.5 font-semibold text-slate-100">{r.node}</td>
                <td className="p-2.5 text-slate-300">{r.ours}{r.note && <div className="mt-1 text-xs text-amber-200/80">{r.note}</div>}</td>
                <td className="w-56 p-2.5 font-mono text-[11px] text-slate-400">{r.code}</td>
                <td className="w-52 p-2.5 text-xs text-slate-400">{r.evidence}</td>
                <td className="w-28 p-2.5"><Status s={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <H title="ITU-T Y.3173: who does what" sub="Five dimensions, each done by a human, a human and the system, or the system. The overall level is the lowest of the five, so we claim no high level." />
      <div className="grid grid-cols-5 gap-2">
        {data.y3173.map((d) => (
          <div key={d.dimension} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <div className="text-xs text-slate-400">{d.dimension}</div>
            <div className={`mt-0.5 text-sm font-bold ${WHO[d.who] ?? 'text-slate-200'}`}>{d.who}</div>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-300">{d.ours}</p>
          </div>
        ))}
      </div>

      <H title="From policy to control" sub="Each requirement, who is responsible, the standard, the control in our code, the test, and the passage it rests on" />
      <div className="space-y-3">
        {data.policy_to_control.map((r) => <PolicyRow key={r.id} r={r} />)}
      </div>

      <H title="ITU AI Ready framework: six dimensions" sub="Where the project stands on each" />
      <div className="grid grid-cols-3 gap-2">
        {data.ai_ready.map((d) => (
          <div key={d.dimension} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-100">{d.dimension}</span><Status s={d.status} /></div>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-300">{d.ours}</p>
            {d.note && <p className="mt-1 text-xs text-amber-200/80">{d.note}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

function PolicyRow({ r }: { r: Alignment['policy_to_control'][number] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-[15px] font-semibold text-slate-100">{r.policy}</div>
        <Status s={r.status} />
      </div>
      <div className="mt-3 grid grid-cols-[repeat(4,minmax(0,1fr))] gap-2 text-xs">
        <Cell label="Responsible" text={r.actor} />
        <Cell label="Standard" text={r.standard} />
        <Cell label="Control in our code" text={r.control} sub={r.code} />
        <Cell label="Test and evidence" text={r.test} />
      </div>
      {r.note && <p className="mt-2 text-xs text-amber-200/80">{r.note}</p>}
      <button onClick={() => setOpen(!open)} className="mt-2 text-xs text-sky-400 hover:underline">
        {open ? 'Hide' : 'Show'} the {r.sources.length === 1 ? 'passage' : `${r.sources.length} passages`} it rests on
      </button>
      {open && <div className="mt-2 space-y-2">{r.sources.map((s) => <Quote key={s.id} s={s} />)}</div>}
    </div>
  )
}

function Cell({ label, text, sub }: { label: string; text: string; sub?: string }) {
  return (
    <div className="rounded-md bg-slate-950/60 p-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-0.5 leading-relaxed text-slate-200">{text}</div>
      {sub && <div className="mt-1 font-mono text-[10px] text-slate-500">{sub}</div>}
    </div>
  )
}

function Quote({ s }: { s: AlignmentSource }) {
  if (s.missing) return <p className="text-xs text-red-300">Passage {s.id} is not in the knowledge base: run scripts/build_library.py.</p>
  return (
    <div className="rounded-md bg-slate-950/70 p-2.5">
      <div className="text-xs text-slate-400"><b className="text-slate-200">{s.title}</b>, p. {s.page} · {s.authority}
        {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="ml-2 text-sky-400 hover:underline">source ↗</a>}</div>
      <blockquote className="mt-1 border-l-2 border-slate-600 pl-2 text-xs italic leading-relaxed text-slate-300">“{s.excerpt}…”</blockquote>
    </div>
  )
}
