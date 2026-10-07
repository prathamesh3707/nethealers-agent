import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import type { Building } from '../api'
import { facade, rng, roof, styleOf, type Style } from './facades'

/**
 * A building with painted facades (windows, shopfronts, signs) and rooftop details (parapet, water tanks,
 * AC units). The solid box is exactly the simulator's building, so signal paths still match what you see.
 * `at` is the box centre in three.js coordinates (x right, y up, z toward the viewer = sim south).
 */
export function BuildingModel({ b, at }: { b: Building; at: THREE.Vector3 }) {
  const style = styleOf(b.name, b.material)
  const w = b.x1 - b.x0
  const d = b.y1 - b.y0
  const h = b.height
  // Buildings north of the road face south (+z in three.js); those south of it face north (-z).
  const facesSouth = (b.y0 + b.y1) / 2 > 100

  const materials = useMemo(() => {
    const glass = style === 'glass'
    const side = (wm: number, front: boolean, key: string) => {
      const f = facade(style, wm, h, b.name + key, front)
      return new THREE.MeshStandardMaterial({
        map: f.map, emissiveMap: f.glow, emissive: '#ffffff', emissiveIntensity: 0.85,
        roughness: glass ? 0.15 : 0.9, metalness: glass ? 0.45 : 0.04, transparent: glass, opacity: glass ? 0.9 : 1,
      })
    }
    // BoxGeometry face order: +x, -x, +y (roof), -y, +z (south), -z (north)
    return [
      side(d, false, ':e'), side(d, false, ':w'),
      new THREE.MeshStandardMaterial({ map: roof(style, w, d), roughness: 0.95 }),
      new THREE.MeshStandardMaterial({ color: '#1f2937' }),
      side(w, facesSouth, ':s'), side(w, !facesSouth, ':n'),
    ]
  }, [style, w, d, h, b.name, facesSouth])
  useEffect(() => () => materials.forEach((m) => { m.map?.dispose(); m.emissiveMap?.dispose(); m.dispose() }),
    [materials])

  return (
    <group position={at}>
      <mesh material={materials} castShadow receiveShadow>
        <boxGeometry args={[w, h, d]} />
      </mesh>
      <group position={[0, h / 2, 0]}>
        <Rooftop style={style} w={w} d={d} seed={b.name} />
      </group>
    </group>
  )
}

function Box({ size, at, color, emissive }: { size: [number, number, number]; at: [number, number, number]; color: string; emissive?: string }) {
  return (
    <mesh position={at} castShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} roughness={0.8} emissive={emissive ?? '#000000'} emissiveIntensity={emissive ? 0.8 : 0} />
    </mesh>
  )
}

/** Things on the roof: a parapet all round, then water tanks on homes and shops, AC units on offices. */
function Rooftop({ style, w, d, seed }: { style: Style; w: number; d: number; seed: string }) {
  const items = useMemo(() => {
    const r = rng(seed + ':roof')
    const out: { kind: 'tank' | 'ac' | 'stair'; x: number; z: number }[] = []
    const spots = (n: number) => Array.from({ length: n }, (_, i) => ({
      x: -w / 2 + ((i + 0.5) * w) / n + (r() - 0.5) * 2,
      z: (r() - 0.5) * (d - 6),
    }))
    if (style === 'homes' || style === 'shops') {
      spots(Math.min(5, Math.max(1, Math.floor(w / 14)))).forEach((p) => out.push({ kind: 'tank', ...p }))
      out.push({ kind: 'stair', x: w / 2 - 4, z: -d / 2 + 4 })
    } else if (style === 'glass' || style === 'mall' || style === 'plain') {
      spots(Math.min(6, Math.max(2, Math.floor(w / 12)))).forEach((p) => out.push({ kind: 'ac', ...p }))
    } else if (style === 'hospital') {
      out.push({ kind: 'stair', x: -w / 2 + 5, z: -d / 2 + 4 }, { kind: 'ac', x: w / 2 - 6, z: d / 2 - 5 })
    }
    return out
  }, [style, w, d, seed])

  if (style === 'flyover') {
    // a railing along both long edges of the deck
    return (
      <group>
        {[-1, 1].map((s) => (
          <group key={s}>
            <Box size={[w, 0.12, 0.12]} at={[0, 1.0, s * (d / 2 - 0.2)]} color="#cbd5e1" />
            {Array.from({ length: Math.floor(w / 3) }, (_, i) => (
              <Box key={i} size={[0.12, 1.0, 0.12]} at={[-w / 2 + 1.5 + i * 3, 0.5, s * (d / 2 - 0.2)]} color="#94a3b8" />
            ))}
          </group>
        ))}
      </group>
    )
  }
  const parapet = style === 'glass' ? '#1e3a5f' : '#78716c'
  return (
    <group>
      <Box size={[w, 0.9, 0.35]} at={[0, 0.45, d / 2 - 0.17]} color={parapet} />
      <Box size={[w, 0.9, 0.35]} at={[0, 0.45, -d / 2 + 0.17]} color={parapet} />
      <Box size={[0.35, 0.9, d]} at={[w / 2 - 0.17, 0.45, 0]} color={parapet} />
      <Box size={[0.35, 0.9, d]} at={[-w / 2 + 0.17, 0.45, 0]} color={parapet} />
      {items.map((it, i) => it.kind === 'tank' ? (
        <group key={i} position={[it.x, 0, it.z]}>
          <Box size={[2.2, 0.5, 2.2]} at={[0, 0.25, 0]} color="#57534e" />
          <mesh position={[0, 1.2, 0]} castShadow>
            <cylinderGeometry args={[0.8, 0.8, 1.4, 16]} />
            <meshStandardMaterial color="#1c1917" roughness={0.6} />
          </mesh>
        </group>
      ) : it.kind === 'ac' ? (
        <Box key={i} size={[2.2, 1.1, 1.4]} at={[it.x, 0.55, it.z]} color="#d4d4d8" />
      ) : (
        <Box key={i} size={[4, 2.8, 3.2]} at={[it.x, 1.4, it.z]} color="#a8a29e" />
      ))}
    </group>
  )
}
