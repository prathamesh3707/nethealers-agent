import { useEffect, useState } from 'react'
import { api, type Incident } from '../api'
import { useGame } from '../store'

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
export const game = () => useGame.getState()

/** The incident a tour or demo talks about: the biggest one (the bus). */
export function mainIncident(): Incident | null {
  const incs = (game().frame?.incidents ?? []).filter((i) => i.status !== 'false_alarm')
  return [...incs].sort((a, b) => b.phones.length - a.phones.length || a.opened - b.opened)[0] ?? null
}

/** Advance the paused simulation by one second and wait for the new frame to arrive. */
export async function stepOnce() {
  const id = game().sessionId
  if (!id) return
  const before = game().frame?.tick ?? 0
  await api.control(id, 'step')
  for (let w = 0; w < 40 && (game().frame?.tick ?? 0) <= before; w++) await sleep(50)
}

export async function stepUntil(done: () => boolean, max: number) {
  for (let i = 0; i < max && !done(); i++) await stepOnce()
}

/** Start a fresh, paused game for a tour or demo. */
export async function freshPausedGame() {
  const g = game()
  g.setIntro(false)
  g.setMode('simple')
  g.setTool(null)
  g.select(null)
  await g.start({ start_paused: true })
  await sleep(300)
}

/** Follow the first on-screen element among `targets` (data-tour anchors). */
export function useTargetRect(targets: string[] | undefined, deps: unknown[] = []): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null)
  const key = targets?.join(',') ?? ''
  useEffect(() => {
    if (!targets?.length) { setRect(null); return }
    const measure = () => {
      const el = targets.map((t) => document.querySelector(`[data-tour="${t}"]`)).find(Boolean) as HTMLElement | undefined
      if (el) el.scrollIntoView({ block: 'nearest' })
      setRect(el ? el.getBoundingClientRect() : null)
    }
    measure()
    const t = setInterval(measure, 250)
    return () => clearInterval(t)
  }, [key, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
  return rect
}

/** Where to put a card of width `w` next to `rect` without covering it. */
export function placeNear(rect: DOMRect | null, w: number, h = 300): React.CSSProperties {
  if (!rect) return { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
  const vw = window.innerWidth
  const vh = window.innerHeight
  const pad = 14
  const clampX = (x: number) => Math.min(Math.max(pad, x), vw - w - pad)
  const clampY = (y: number) => Math.min(Math.max(pad, y), vh - h - pad)
  if (rect.width > vw * 0.45 && rect.height > vh * 0.4) return { left: clampX(rect.left + 24), top: clampY(rect.top + 110) }
  if (rect.left > vw * 0.5) return { left: clampX(rect.left - w - pad), top: clampY(rect.top) }
  if (rect.right < vw * 0.5) return { left: clampX(rect.right + pad), top: clampY(rect.top) }
  if (rect.top > vh * 0.55) return { left: clampX(rect.left), top: clampY(rect.top - h - pad) }
  return { left: clampX(rect.left), top: clampY(rect.bottom + pad) }
}

/** Dim everything except `rect`, with a ring around it. */
export function Highlight({ rect, dim = true }: { rect: DOMRect | null; dim?: boolean }) {
  if (!rect) return dim ? <div className="absolute inset-0 bg-slate-950/70" /> : null
  return (
    <div className="absolute rounded-xl ring-2 ring-sky-400 transition-all duration-300"
      style={{ left: rect.left - 4, top: rect.top - 4, width: rect.width + 8, height: rect.height + 8,
        boxShadow: dim ? '0 0 0 9999px rgba(2, 6, 23, 0.62)' : '0 0 24px rgba(56,189,248,0.6)' }} />
  )
}
