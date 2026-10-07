import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { rng } from './facades'

// A crowd standing in the signal path, drawn as people. They wear plain greys on purpose: on this street a
// colour always means a phone and its signal, and these people are only an obstacle in the simulator
// (none of them is one of the tracked phones). Everyone fits inside the simulator's crowd box, so the
// blockage you see is the blockage it computes.

const CLOTHES = ['#9ca3af', '#6b7280', '#4b5563', '#d1d5db', '#78716c', '#a8a29e']
const SKIN = ['#8d5524', '#a0673b', '#c68642', '#7a4a2a', '#b07a4f']
const HAIR = ['#111827', '#1f2937', '#292524', '#44403c']

interface Person { x: number; z: number; yaw: number; h: number; top: string; legs: string; skin: string; hair: string; phase: number }

/** Scatter people over a w x d area (metres), never closer than 0.65 m to each other. */
function scatter(seed: string, w: number, d: number, maxH: number): Person[] {
  const r = rng(seed)
  const pick = <T,>(a: T[]) => a[Math.floor(r() * a.length)]
  const target = Math.max(4, Math.round((w * d) / 2.0))
  const out: Person[] = []
  for (let tries = 0; out.length < target && tries < target * 30; tries++) {
    const x = (r() - 0.5) * (w - 0.6)
    const z = (r() - 0.5) * (d - 0.6)
    if (out.some((p) => Math.hypot(p.x - x, p.z - z) < 0.65)) continue
    out.push({
      x, z, yaw: r() * Math.PI * 2, h: Math.min(maxH, 1.5 + r() * 0.3), top: pick(CLOTHES), legs: pick(CLOTHES),
      skin: pick(SKIN), hair: pick(HAIR), phase: r() * Math.PI * 2,
    })
  }
  return out
}

const legGeom = new THREE.BoxGeometry(0.34, 1, 0.22)
const bodyGeom = new THREE.BoxGeometry(0.44, 1, 0.26)
const armGeom = new THREE.BoxGeometry(0.11, 1, 0.12)
const headGeom = new THREE.SphereGeometry(0.12, 10, 8)

function Figure({ p, opacity }: { p: Person; opacity: number }) {
  const ref = useRef<THREE.Group>(null)
  useFrame(({ clock }) => {
    // a slow shift of weight, so the crowd looks alive without walking anywhere
    if (ref.current) ref.current.rotation.z = Math.sin(clock.elapsedTime * 0.9 + p.phase) * 0.035
  })
  const legH = p.h * 0.47
  const bodyH = p.h * 0.36
  const headY = legH + bodyH + 0.12
  const see = { transparent: opacity < 1, opacity }
  return (
    <group position={[p.x, 0, p.z]} rotation-y={p.yaw}>
      <group ref={ref}>
        <mesh geometry={legGeom} position={[0, legH / 2, 0]} scale={[1, legH, 1]} castShadow={opacity === 1}>
          <meshStandardMaterial color={p.legs} roughness={0.9} {...see} />
        </mesh>
        <mesh geometry={bodyGeom} position={[0, legH + bodyH / 2, 0]} scale={[1, bodyH, 1]} castShadow={opacity === 1}>
          <meshStandardMaterial color={p.top} roughness={0.9} {...see} />
        </mesh>
        {[-1, 1].map((s) => (
          <mesh key={s} geometry={armGeom} position={[s * 0.28, legH + bodyH * 0.52, 0]} scale={[1, bodyH * 0.95, 1]}>
            <meshStandardMaterial color={p.top} roughness={0.9} {...see} />
          </mesh>
        ))}
        <mesh geometry={headGeom} position={[0, headY, 0]} castShadow={opacity === 1}>
          <meshStandardMaterial color={p.skin} roughness={0.8} {...see} />
        </mesh>
        <mesh geometry={headGeom} position={[0, headY + 0.04, -0.02]} scale={[1.02, 0.7, 1.02]}>
          <meshStandardMaterial color={p.hair} roughness={0.9} {...see} />
        </mesh>
      </group>
    </group>
  )
}

/** A crowd filling a w x d area (x and z extents in metres), standing on the ground at its group's origin. */
export function CrowdModel({ id, w, d, h, opacity = 1 }: { id: string; w: number; d: number; h: number; opacity?: number }) {
  const people = useMemo(() => scatter(id, w, d, h), [id, w, d, h])
  return (
    <group>
      {people.map((p, i) => <Figure key={i} p={p} opacity={opacity} />)}
    </group>
  )
}
