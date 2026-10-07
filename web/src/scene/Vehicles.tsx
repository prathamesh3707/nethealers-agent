import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { VEHICLE_SIZE, type VehicleKind } from './vehicleGeometry'

// Low-poly vehicles built from simple shapes. Each one is drawn at exactly the size the simulator uses for
// its signal blockage (src/nethealers/sim/config.py BLOCKER_TYPES), so what you see is what blocks.
// Local frame: +x is the front, +y is up, -z is the vehicle's left (the kerb side when driving on the left).

const CAR_COLORS = ['#e11d48', '#2563eb', '#f1f5f9', '#94a3b8', '#16a34a', '#f59e0b', '#7c3aed']

interface Look { opacity: number; tint?: string }

/** A solid part. `look.tint` recolours everything (used for the placement preview). */
function Part({ size, at, color, look, emissive, metal = 0.1, rough = 0.7, shadow = true }: {
  size: [number, number, number]; at: [number, number, number]; color: string; look: Look
  emissive?: string; metal?: number; rough?: number; shadow?: boolean
}) {
  const c = look.tint ?? color
  return (
    <mesh position={at} castShadow={shadow && look.opacity === 1}>
      <boxGeometry args={size} />
      <meshStandardMaterial color={c} metalness={metal} roughness={rough} transparent={look.opacity < 1}
        opacity={look.opacity} emissive={emissive ?? '#000000'} emissiveIntensity={emissive ? 0.9 : 0} />
    </mesh>
  )
}

const GLASS = '#0f172a'

function Wheels({ axles, half, r, look, spin }: {
  axles: number[]; half: number; r: number; look: Look; spin: React.RefObject<number>
}) {
  const group = useRef<THREE.Group>(null)
  useFrame(() => {
    group.current?.children.forEach((w) => { w.rotation.z = -(spin.current ?? 0) / r })
  })
  return (
    <group ref={group}>
      {axles.flatMap((x) => [-half, half].map((z) => (
        <group key={`${x}:${z}`} position={[x, r, z]}>
          <mesh rotation-x={Math.PI / 2} castShadow={look.opacity === 1}>
            <cylinderGeometry args={[r, r, 0.32, 14]} />
            <meshStandardMaterial color={look.tint ?? '#111827'} roughness={0.9} transparent={look.opacity < 1}
              opacity={look.opacity} />
          </mesh>
          {/* hub, so a turning wheel is visible */}
          <mesh position={[r * 0.45, 0, z > 0 ? 0.17 : -0.17]}>
            <boxGeometry args={[r * 0.5, r * 0.25, 0.02]} />
            <meshStandardMaterial color={look.tint ?? '#9ca3af'} transparent={look.opacity < 1} opacity={look.opacity} />
          </mesh>
        </group>
      )))}
    </group>
  )
}

function Bus({ look, spin }: { look: Look; spin: React.RefObject<number> }) {
  const { length: L, width: W, height: H } = VEHICLE_SIZE.bus
  const bottom = 0.35
  const top = H - 0.2
  const pillars = Array.from({ length: 8 }, (_, i) => -L / 2 + 1.4 + i * 1.55)
  return (
    <group>
      <Part size={[L, top - bottom, W]} at={[0, (top + bottom) / 2, 0]} color="#c2410c" look={look} />
      <Part size={[L + 0.02, 0.4, W + 0.02]} at={[0, bottom + 0.2, 0]} color="#7c2d12" look={look} />
      <Part size={[L + 0.02, 0.18, W + 0.02]} at={[0, 1.62, 0]} color="#fde68a" look={look} />
      {/* window band on both sides, with pillars */}
      {[-1, 1].map((s) => (
        <group key={s}>
          <Part size={[L - 1.6, 1.05, 0.04]} at={[-0.3, 2.35, s * (W / 2 + 0.01)]} color={GLASS} look={look}
            metal={0.4} rough={0.15} shadow={false} />
          {pillars.map((x) => (
            <Part key={x} size={[0.12, 1.07, 0.06]} at={[x, 2.35, s * (W / 2 + 0.02)]} color="#c2410c" look={look}
              shadow={false} />
          ))}
        </group>
      ))}
      {/* doors on the kerb side */}
      {[L / 2 - 1.6, -L / 2 + 4.2].map((x) => (
        <Part key={x} size={[1.1, 2.3, 0.05]} at={[x, bottom + 1.2, -(W / 2 + 0.02)]} color="#1f2937" look={look}
          shadow={false} />
      ))}
      {/* front: windscreen, route board, lights */}
      <Part size={[0.05, 1.35, W - 0.3]} at={[L / 2 + 0.01, 2.2, 0]} color={GLASS} look={look} metal={0.4} rough={0.15} />
      <Part size={[0.06, 0.36, W - 0.7]} at={[L / 2 + 0.02, top - 0.32, 0]} color="#f59e0b" look={look} emissive="#f59e0b" />
      {[-1, 1].map((s) => (
        <Part key={s} size={[0.06, 0.18, 0.4]} at={[L / 2 + 0.03, 0.85, s * (W / 2 - 0.35)]} color="#fef9c3"
          look={look} emissive="#fef08a" />
      ))}
      {/* back: window and tail lights */}
      <Part size={[0.05, 0.8, W - 0.6]} at={[-L / 2 - 0.01, 2.4, 0]} color={GLASS} look={look} />
      {[-1, 1].map((s) => (
        <Part key={s} size={[0.06, 0.3, 0.25]} at={[-L / 2 - 0.03, 0.95, s * (W / 2 - 0.3)]} color="#dc2626"
          look={look} emissive="#b91c1c" />
      ))}
      <Part size={[3.2, 0.28, 1.6]} at={[-1, top + 0.14, 0]} color="#e5e7eb" look={look} />
      <Wheels axles={[L / 2 - 2.6, -L / 2 + 3.1]} half={W / 2 - 0.12} r={0.5} look={look} spin={spin} />
    </group>
  )
}

function Truck({ look, spin }: { look: Look; spin: React.RefObject<number> }) {
  const { length: L, width: W, height: H } = VEHICLE_SIZE.truck
  const cabL = 2.2
  const cabX = L / 2 - cabL / 2
  const boxL = L - cabL - 0.25
  const boxX = -L / 2 + boxL / 2
  const ribs = Array.from({ length: 5 }, (_, i) => -L / 2 + 0.6 + i * (boxL - 1.2) / 4)
  return (
    <group>
      <Part size={[L - 0.2, 0.35, W - 0.5]} at={[0, 0.75, 0]} color="#1f2937" look={look} />
      {/* cab, painted the way Indian lorries often are */}
      <Part size={[cabL, 2.4, W]} at={[cabX, 2.0, 0]} color="#f59e0b" look={look} />
      <Part size={[cabL + 0.02, 0.25, W + 0.02]} at={[cabX, 1.15, 0]} color="#dc2626" look={look} />
      <Part size={[cabL + 0.02, 0.12, W + 0.02]} at={[cabX, 2.6, 0]} color="#16a34a" look={look} />
      <Part size={[0.05, 0.9, W - 0.3]} at={[L / 2 + 0.01, 2.55, 0]} color={GLASS} look={look} metal={0.4} rough={0.15} />
      {[-1, 1].map((s) => (
        <Part key={s} size={[1.0, 0.8, 0.04]} at={[cabX + 0.3, 2.55, s * (W / 2 + 0.01)]} color={GLASS} look={look}
          shadow={false} />
      ))}
      <Part size={[0.12, 0.3, W]} at={[L / 2 + 0.06, 0.95, 0]} color="#d1d5db" look={look} />
      {[-1, 1].map((s) => (
        <Part key={s} size={[0.06, 0.2, 0.35]} at={[L / 2 + 0.12, 1.35, s * (W / 2 - 0.3)]} color="#fef9c3"
          look={look} emissive="#fef08a" />
      ))}
      {/* cargo body under a tarpaulin */}
      <Part size={[boxL, H - 1.0, W]} at={[boxX, 1.0 + (H - 1.0) / 2, 0]} color="#1d4ed8" look={look} rough={0.95} />
      {ribs.map((x) => (
        <Part key={x} size={[0.1, H - 0.95, W + 0.04]} at={[x, 1.0 + (H - 1.0) / 2, 0]} color="#1e3a8a" look={look}
          shadow={false} />
      ))}
      {[-1, 1].map((s) => (
        <Part key={s} size={[0.06, 0.3, 0.25]} at={[-L / 2 - 0.03, 1.1, s * (W / 2 - 0.3)]} color="#dc2626"
          look={look} emissive="#b91c1c" />
      ))}
      <Wheels axles={[L / 2 - 1.2, -L / 2 + 2.6, -L / 2 + 1.5]} half={W / 2 - 0.12} r={0.52} look={look} spin={spin} />
    </group>
  )
}

function Car({ look, spin, color }: { look: Look; spin: React.RefObject<number>; color: string }) {
  const { length: L, width: W, height: H } = VEHICLE_SIZE.car
  return (
    <group>
      <Part size={[L, 0.6, W]} at={[0, 0.58, 0]} color={color} look={look} metal={0.35} rough={0.35} />
      <Part size={[2.3, H - 0.92, W - 0.16]} at={[-0.25, (0.88 + H) / 2 - 0.02, 0]} color={GLASS} look={look}
        metal={0.4} rough={0.15} />
      <Part size={[2.1, 0.08, W - 0.2]} at={[-0.3, H - 0.04, 0]} color={color} look={look} metal={0.35} rough={0.35} />
      {[-1, 1].map((s) => (
        <group key={s}>
          <Part size={[0.05, 0.14, 0.42]} at={[L / 2 + 0.01, 0.7, s * (W / 2 - 0.3)]} color="#fef9c3" look={look}
            emissive="#fef08a" shadow={false} />
          <Part size={[0.05, 0.14, 0.32]} at={[-L / 2 - 0.01, 0.72, s * (W / 2 - 0.3)]} color="#dc2626" look={look}
            emissive="#b91c1c" shadow={false} />
        </group>
      ))}
      <Wheels axles={[L / 2 - 0.85, -L / 2 + 0.85]} half={W / 2 - 0.1} r={0.33} look={look} spin={spin} />
    </group>
  )
}

/**
 * A vehicle, sitting on the ground at its group's origin and facing `heading` (radians, 0 = east).
 * Its wheels turn by however far the enclosing group moves forward, so a driving bus rolls.
 */
export function Vehicle({ kind, id = '', heading, opacity = 1, tint }: {
  kind: VehicleKind; id?: string; heading: number; opacity?: number; tint?: string
}) {
  const root = useRef<THREE.Group>(null)
  const spin = useRef(0)
  const last = useRef<THREE.Vector3 | null>(null)
  const look = useMemo(() => ({ opacity, tint }), [opacity, tint])
  const color = useMemo(() => {
    let h = 0
    for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
    return CAR_COLORS[h % CAR_COLORS.length]
  }, [id])
  useFrame(() => {
    if (!root.current) return
    const p = root.current.getWorldPosition(new THREE.Vector3())
    if (last.current) {
      const d = p.clone().sub(last.current)
      spin.current += d.x * Math.cos(heading) - d.z * Math.sin(heading)
    }
    last.current = p
  })
  return (
    <group ref={root} rotation-y={heading}>
      {kind === 'bus' && <Bus look={look} spin={spin} />}
      {kind === 'truck' && <Truck look={look} spin={spin} />}
      {kind === 'car' && <Car look={look} spin={spin} color={color} />}
    </group>
  )
}
