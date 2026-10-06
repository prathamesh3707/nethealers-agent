import { useState } from 'react'
import { useGame } from '../store'

const SLIDES = [
  {
    icon: '📡',
    title: 'The problem',
    body: [
      '5G gets its speed from high frequencies and narrow beams aimed at each phone. The catch: they are easily blocked.',
      'A bus, a crowd or a new hoarding between a tower and a phone can drop the signal within seconds. Today such problems often stay until customers complain or an engineer investigates by hand.',
    ],
  },
  {
    icon: '🤖',
    title: 'The self-healing agent',
    body: [
      'Our AI agent watches every user’s signal, works out the cause, and tests possible fixes on a digital twin (a virtual copy of the street) before touching the real network.',
      'It applies only fixes that pass hard safety rules, measures the real result, and undoes anything that did not work. Large changes always need a person’s approval.',
    ],
  },
  {
    icon: '🎮',
    title: 'How to use this demo',
    body: [
      'The UI tour explains every part of this screen. The incident demo then plays one bus incident step by step. Or explore freely: pick a problem (bus, truck, crowd…), click on the street, and move it with the ◀ ▶ buttons.',
      'Users are dots: green = good service, amber = slow, red = no service. The right panel shows what the agent is doing, step by step. You are the network operator: approve or reject its bigger changes.',
    ],
  },
]

export default function Intro() {
  const open = useGame((s) => s.introOpen)
  const setIntro = useGame((s) => s.setIntro)
  const [n, setN] = useState(0)
  if (!open) return null
  const s = SLIDES[n]
  const last = n === SLIDES.length - 1
  const close = () => { setIntro(false); setN(0) }
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div className="w-full max-w-xl rounded-2xl border border-slate-700 bg-slate-900 p-7 shadow-2xl">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>NetHealers · AI for Good Build-a-thon 5.0</span>
          <button className="hover:text-slate-300" onClick={close}>Skip ✕</button>
        </div>
        <div className="mt-5 text-4xl">{s.icon}</div>
        <h2 className="mt-3 text-2xl font-bold text-slate-50">{s.title}</h2>
        {s.body.map((p) => <p key={p} className="mt-3 text-[15px] leading-relaxed text-slate-300">{p}</p>)}
        <div className="mt-7 flex items-center justify-between">
          <div className="flex gap-1.5">
            {SLIDES.map((_, i) => (
              <button key={i} onClick={() => setN(i)} aria-label={`Slide ${i + 1}`}
                className={`h-2 rounded-full transition-all ${i === n ? 'w-6 bg-sky-400' : 'w-2 bg-slate-700'}`} />
            ))}
          </div>
          <div className="flex gap-2">
            {n > 0 && <button className="btn bg-slate-800 hover:bg-slate-700" onClick={() => setN(n - 1)}>Back</button>}
            {!last && <button className="btn bg-sky-500 text-sky-950 hover:bg-sky-400" onClick={() => setN(n + 1)}>Next</button>}
            {last && (
              <>
                <button className="btn bg-slate-800 hover:bg-slate-700" onClick={() => { close(); useGame.getState().setTour(0) }}>
                  ⓘ UI tour
                </button>
                <button className="btn bg-emerald-500 text-emerald-950 hover:bg-emerald-400" onClick={() => {
                  close()
                  useGame.getState().setDemo(true)
                }}>▶ Incident demo</button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
