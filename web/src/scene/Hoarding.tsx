import { useEffect, useMemo } from 'react'
import { advert } from './facades'

/**
 * A roadside billboard: two steel legs, a framed panel with an advert on both sides, and lamps on top.
 * It fills the simulator's hoarding box (8 m wide, 0.5 m deep, 6 m tall), so the blockage matches.
 * Sits on the ground at its group's origin; `w` and `d` are the box's x and z extents in metres.
 */
export function HoardingModel({ id, w, d, h, opacity = 1 }: { id: string; w: number; d: number; h: number; opacity?: number }) {
  const ad = useMemo(() => advert(id), [id])
  useEffect(() => () => ad.dispose(), [ad])
  const alongZ = d > w
  const L = Math.max(w, d)
  const T = Math.min(w, d)
  const bottom = 1.6
  const panelH = h - bottom
  const see = { transparent: opacity < 1, opacity }
  return (
    <group rotation-y={alongZ ? Math.PI / 2 : 0}>
      {[-1, 1].map((s) => (
        <mesh key={s} position={[s * L * 0.3, (bottom + 0.4) / 2, 0]} castShadow>
          <boxGeometry args={[0.35, bottom + 0.4, 0.35]} />
          <meshStandardMaterial color="#6b7280" metalness={0.6} roughness={0.4} {...see} />
        </mesh>
      ))}
      <mesh position={[0, bottom + panelH / 2, 0]} castShadow>
        <boxGeometry args={[L, panelH, T]} />
        <meshStandardMaterial color="#1f2937" metalness={0.3} roughness={0.6} {...see} />
      </mesh>
      {[1, -1].map((s) => (
        <mesh key={s} position={[0, bottom + panelH / 2, s * (T / 2 + 0.02)]} rotation-y={s > 0 ? 0 : Math.PI}>
          <planeGeometry args={[L - 0.4, panelH - 0.4]} />
          <meshStandardMaterial map={ad} emissiveMap={ad} emissive="#ffffff" emissiveIntensity={0.35} roughness={0.6} {...see} />
        </mesh>
      ))}
      {[-L / 3, 0, L / 3].map((x) => (
        <group key={x} position={[x, h, T / 2]}>
          <mesh position={[0, 0.1, 0.35]}>
            <boxGeometry args={[0.08, 0.08, 0.7]} />
            <meshStandardMaterial color="#9ca3af" {...see} />
          </mesh>
          <mesh position={[0, 0.05, 0.75]}>
            <boxGeometry args={[0.45, 0.18, 0.25]} />
            <meshStandardMaterial color="#fef9c3" emissive="#fde68a" emissiveIntensity={1} {...see} />
          </mesh>
        </group>
      ))}
    </group>
  )
}
