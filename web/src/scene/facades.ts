import * as THREE from 'three'

// Facade, roof and billboard pictures painted on canvases. Each building face gets a texture sized to that
// face in metres, so windows stay the right size whatever the building. A second canvas holds only what
// glows (lit windows, signs), used as the emissive map so the street looks alive against the dark sky.

export type Style = 'shops' | 'homes' | 'glass' | 'hospital' | 'mall' | 'flyover' | 'plain'

export function styleOf(name: string, material: string): Style {
  const n = name.toLowerCase()
  if (n.includes('shop') || n.includes('market')) return 'shops'
  if (n.includes('apartment') || n.includes('flat') || n.includes('home')) return 'homes'
  if (n.includes('hospital')) return 'hospital'
  if (n.includes('mall')) return 'mall'
  if (n.includes('flyover')) return 'flyover'
  if (material === 'glass') return 'glass'
  return 'plain'
}

const BASE: Record<Style, string> = {
  shops: '#9a6a4f', homes: '#a8a29e', glass: '#3b82b8', hospital: '#e7e5e4', mall: '#6b7280', flyover: '#8b8f96',
  plain: '#94a3b8',
}

/** A small seeded random generator, so a building looks the same every time it is drawn. */
export function rng(seed: string | number): () => number {
  let h = typeof seed === 'number' ? seed : 0
  if (typeof seed === 'string') for (const c of seed) h = (Math.imul(h, 31) + c.charCodeAt(0)) | 0
  return () => {
    h = (h + 0x6d2b79f5) | 0
    let t = Math.imul(h ^ (h >>> 15), 1 | h)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function canvas(wm: number, hm: number, maxPx = 1024) {
  const ppm = Math.min(10, maxPx / Math.max(wm, hm)) // pixels per metre
  const c = document.createElement('canvas')
  c.width = Math.max(8, Math.round(wm * ppm))
  c.height = Math.max(8, Math.round(hm * ppm))
  const g = c.getContext('2d')!
  // canvas y runs down; draw in metres from the ground up
  g.setTransform(ppm, 0, 0, -ppm, 0, c.height)
  return { c, g, ppm }
}

function tex(c: HTMLCanvasElement, srgb = true): THREE.CanvasTexture {
  const t = new THREE.CanvasTexture(c)
  if (srgb) t.colorSpace = THREE.SRGBColorSpace
  t.anisotropy = 4
  return t
}

const FLOOR_M = 3.2
const SHOP_SIGNS = ['MOBILE', 'CHEMIST', 'CHAI', 'SWEETS', 'TAILOR', 'BANK', 'XEROX', 'KIRANA', 'PHONES', 'OPTICAL']
const AWNINGS = ['#dc2626', '#2563eb', '#16a34a', '#ea580c', '#7c3aed', '#0891b2', '#ca8a04']

/** One building face: `front` is the side facing Station Road. Returns the picture and its glow. */
export function facade(style: Style, wm: number, hm: number, seed: string, front: boolean) {
  const { c, g } = canvas(wm, hm)
  const glowC = canvas(wm, hm)
  const gl = glowC.g
  const r = rng(seed)
  gl.fillStyle = '#000'
  gl.fillRect(0, 0, wm, hm)
  g.fillStyle = BASE[style]
  g.fillRect(0, 0, wm, hm)

  const floors = Math.max(1, Math.floor(hm / FLOOR_M))
  const text = (ctx: CanvasRenderingContext2D, s: string, x: number, y: number, size: number, color: string) => {
    ctx.save()
    ctx.scale(1, -1) // undo the flip for text
    ctx.fillStyle = color
    ctx.font = `bold ${size}px system-ui, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(s, x, -y)
    ctx.restore()
  }

  if (style === 'flyover') {
    g.fillStyle = '#6b7280'
    for (let x = 0; x < wm; x += 6) g.fillRect(x, 0, 0.15, hm) // panel joints
    g.fillStyle = '#4b5563'
    g.fillRect(0, hm - 1.2, wm, 1.2) // deck edge
    for (let x = 0; x < wm; x += 2) { // black and yellow kerb paint
      g.fillStyle = Math.floor(x / 2) % 2 ? '#facc15' : '#111827'
      g.fillRect(x, 0, 2, 0.6)
    }
    return { map: tex(c), glow: tex(glowC.c) }
  }

  if (style === 'glass') {
    g.fillStyle = '#1e3a5f'
    g.fillRect(0, 0, wm, hm)
    for (let f = 0; f < floors; f++) {
      const lit = r() < 0.45
      if (lit) {
        gl.fillStyle = 'rgba(186,230,253,0.55)'
        gl.fillRect(0, f * FLOOR_M + 0.4, wm, FLOOR_M - 0.8)
        g.fillStyle = '#5b8db8'
        g.fillRect(0, f * FLOOR_M + 0.4, wm, FLOOR_M - 0.8)
      }
    }
    g.fillStyle = '#cbd5e1'
    for (let f = 0; f <= floors; f++) g.fillRect(0, f * FLOOR_M - 0.08, wm, 0.16) // floor bands
    for (let x = 0; x <= wm; x += 1.6) g.fillRect(x - 0.05, 0, 0.1, hm) // mullions
    if (front) {
      g.fillStyle = '#0f172a'
      g.fillRect(wm / 2 - 3, 0, 6, 3.4) // entrance
      gl.fillStyle = '#fde68a'
      gl.fillRect(wm / 2 - 2.6, 0.2, 5.2, 2.8)
    }
    return { map: tex(c), glow: tex(glowC.c) }
  }

  // Masonry styles: rows of windows; shops get shopfronts on the street side.
  const winW = style === 'hospital' ? 1.8 : 1.3
  const pitch = style === 'homes' ? 2.4 : style === 'hospital' ? 3.0 : 2.8
  const startFloor = (style === 'shops' || style === 'mall') && front ? 1 : 0
  for (let f = startFloor; f < floors; f++) {
    const y0 = f * FLOOR_M + 0.9
    for (let x = 0.8; x + winW < wm - 0.4; x += pitch) {
      const lit = r() < (style === 'hospital' ? 0.6 : 0.33)
      g.fillStyle = lit ? '#fcd34d' : style === 'hospital' ? '#64748b' : '#1e293b'
      g.fillRect(x, y0, winW, 1.5)
      if (lit) {
        gl.fillStyle = style === 'hospital' ? '#e0f2fe' : '#fbbf24'
        gl.fillRect(x, y0, winW, 1.5)
      }
      if (style === 'homes' && f > 0 && r() < 0.5) { // small balcony with a railing
        g.fillStyle = '#78716c'
        g.fillRect(x - 0.3, y0 - 0.5, winW + 0.6, 0.35)
      }
    }
    if (style === 'hospital') { // horizontal white bands between floors
      g.fillStyle = '#f5f5f4'
      g.fillRect(0, f * FLOOR_M, wm, 0.3)
    }
  }

  if (front && style === 'shops') {
    let x = 0.5
    while (x < wm - 3) {
      const w = Math.min(wm - x - 0.5, 4 + r() * 3)
      const open = r() < 0.65
      g.fillStyle = open ? '#fde68a' : '#6b7280'
      g.fillRect(x, 0, w - 0.4, 2.6)
      if (open) {
        gl.fillStyle = '#f59e0b'
        gl.fillRect(x, 0, w - 0.4, 2.6)
      } else {
        g.fillStyle = '#4b5563'
        for (let y = 0.2; y < 2.6; y += 0.3) g.fillRect(x, y, w - 0.4, 0.06) // shutter ribs
      }
      const awning = AWNINGS[Math.floor(r() * AWNINGS.length)]
      g.fillStyle = awning
      g.fillRect(x - 0.1, 2.6, w - 0.2, 0.5)
      g.fillStyle = '#f8fafc'
      for (let s = x; s < x + w - 0.4; s += 0.8) g.fillRect(s, 2.6, 0.35, 0.5) // stripes
      g.fillStyle = '#0f172a'
      g.fillRect(x, 3.15, w - 0.4, 0.75) // signboard
      text(g, SHOP_SIGNS[Math.floor(r() * SHOP_SIGNS.length)], x + (w - 0.4) / 2, 3.52, 0.55, awning)
      gl.fillStyle = awning
      gl.globalAlpha = 0.5
      gl.fillRect(x, 3.15, w - 0.4, 0.75)
      gl.globalAlpha = 1
      x += w
    }
  }

  if (front && style === 'mall') {
    g.fillStyle = '#0f172a'
    g.fillRect(1, 0.2, wm - 2, 3.0) // glass storefront
    gl.fillStyle = '#7dd3fc'
    gl.globalAlpha = 0.6
    gl.fillRect(1, 0.2, wm - 2, 3.0)
    gl.globalAlpha = 1
    g.fillStyle = '#111827'
    g.fillRect(wm * 0.2, hm - 4.2, wm * 0.6, 3.2) // sign band
    text(g, 'CITY MALL', wm / 2, hm - 2.6, 2.4, '#f472b6')
    text(gl, 'CITY MALL', wm / 2, hm - 2.6, 2.4, '#ec4899')
  }

  if (front && style === 'hospital') {
    const cx = wm / 2
    const cy = hm - 3
    g.fillStyle = '#ffffff'
    g.fillRect(cx - 2.2, cy - 2.2, 4.4, 4.4)
    g.fillStyle = '#dc2626'
    g.fillRect(cx - 0.55, cy - 1.8, 1.1, 3.6)
    g.fillRect(cx - 1.8, cy - 0.55, 3.6, 1.1)
    gl.fillStyle = '#ef4444'
    gl.fillRect(cx - 0.55, cy - 1.8, 1.1, 3.6)
    gl.fillRect(cx - 1.8, cy - 0.55, 3.6, 1.1)
    g.fillStyle = '#ffffff'
    g.fillRect(cx - 6, 1.25, 12, 1.3) // sign plate over the entrance
    text(g, 'HOSPITAL', cx, 1.9, 1.1, '#b91c1c')
    g.fillStyle = '#334155'
    g.fillRect(cx - 3, 0, 6, 1.1) // entrance canopy shadow
  }
  return { map: tex(c), glow: tex(glowC.c) }
}

/** The roof as seen from above: concrete with a helipad on the hospital. */
export function roof(style: Style, wm: number, dm: number) {
  const { c, g } = canvas(wm, dm, 512)
  g.fillStyle = style === 'glass' ? '#334155' : style === 'hospital' ? '#d6d3d1' : '#57534e'
  g.fillRect(0, 0, wm, dm)
  g.fillStyle = 'rgba(0,0,0,0.12)'
  for (let x = 0; x < wm; x += 4) g.fillRect(x, 0, 0.1, dm)
  if (style === 'hospital') {
    const cx = wm / 2
    const cy = dm / 2
    g.strokeStyle = '#facc15'
    g.lineWidth = 0.8
    g.beginPath()
    g.arc(cx, cy, 7, 0, Math.PI * 2)
    g.stroke()
    g.fillStyle = '#f8fafc' // the H
    g.fillRect(cx - 3, cy - 3.5, 1.2, 7)
    g.fillRect(cx + 1.8, cy - 3.5, 1.2, 7)
    g.fillRect(cx - 3, cy - 0.6, 6, 1.2)
  }
  return tex(c)
}

const ADS = [
  { bg: ['#7c3aed', '#db2777'], head: '5G UNLIMITED', sub: 'Plans from ₹299', fg: '#ffffff' },
  { bg: ['#f59e0b', '#dc2626'], head: 'MEGA SALE', sub: 'Up to 50% off · City Mall', fg: '#ffffff' },
  { bg: ['#065f46', '#10b981'], head: 'KADAK CHAI', sub: 'Since 1987', fg: '#fef3c7' },
  { bg: ['#1e3a8a', '#0ea5e9'], head: 'NEW FLATS', sub: '2 & 3 BHK · Near Station Road', fg: '#ffffff' },
  { bg: ['#111827', '#374151'], head: 'CRICKET LIVE', sub: 'Watch every ball on 5G', fg: '#facc15' },
]

/** A billboard advert (one of a few designs, chosen by the hoarding's id). */
export function advert(seed: string) {
  const ad = ADS[Math.floor(rng(seed)() * ADS.length)]
  const c = document.createElement('canvas')
  c.width = 640
  c.height = 320
  const g = c.getContext('2d')!
  const grad = g.createLinearGradient(0, 0, 640, 320)
  grad.addColorStop(0, ad.bg[0])
  grad.addColorStop(1, ad.bg[1])
  g.fillStyle = grad
  g.fillRect(0, 0, 640, 320)
  g.fillStyle = 'rgba(255,255,255,0.12)'
  g.beginPath()
  g.arc(560, 60, 140, 0, Math.PI * 2)
  g.fill()
  g.fillStyle = ad.fg
  g.textAlign = 'left'
  g.font = 'bold 74px system-ui, sans-serif'
  g.fillText(ad.head, 34, 150)
  g.font = '600 34px system-ui, sans-serif'
  g.fillText(ad.sub, 38, 220)
  return tex(c)
}
