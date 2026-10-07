import { Html, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { Blocker, Building, Phone, Scene, Tower, Zone } from '../api'
import { BAND_COLOR } from '../stages'
import { useFocusedIncident, useGame } from '../store'
import { freeSpot, headingFor, isVehicle, laneY, VEHICLE_SIZE, type Rect } from './vehicleGeometry'
import { Vehicle } from './Vehicles'
import { BuildingModel } from './Buildings'
import { HoardingModel } from './Hoarding'
import { CrowdModel } from './People'

// Simulator metres (x east, y north, z up) -> three.js (x right, y up, z toward the viewer).
const CX = 200
const CY = 110
const toV = (x: number, y: number, h = 0) => new THREE.Vector3(x - CX, h, -(y - CY))

const BLOCKER_COLOR: Record<string, string> = {
  bus: '#facc15', truck: '#f97316', car: '#60a5fa', crowd: '#e879f9', kiosk: '#fb7185', hoarding: '#c084fc',
}

export default function Street() {
  const scene = useGame((s) => s.scene)
  const tool = useGame((s) => s.tool)
  if (!scene) return <div className="grid h-full place-items-center text-slate-500">Starting the street…</div>
  return (
    <Canvas
      shadows
      camera={{ position: [-20, 300, 250], fov: 45, near: 1, far: 3000 }}
      style={{ cursor: tool ? 'crosshair' : 'grab' }}
    >
      <color attach="background" args={['#0b1220']} />
      <fog attach="fog" args={['#0b1220', 450, 900]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[-150, 260, 160]} intensity={1.3} castShadow
        shadow-mapSize={[2048, 2048]} shadow-camera-left={-260} shadow-camera-right={260}
        shadow-camera-top={200} shadow-camera-bottom={-200} />
      <World scene={scene} />
      <OrbitControls makeDefault target={[0, 0, 0]} maxPolarAngle={Math.PI / 2.15} minDistance={60} maxDistance={700} />
    </Canvas>
  )
}

function World({ scene }: { scene: Scene }) {
  const frame = useGame((s) => s.frame)
  const [x0, x1, y0, y1] = scene.extent
  return (
    <group>
      <Ground extent={[x0, x1, y0, y1]} />
      {scene.zones.map((z) => <ZoneArea key={z.name} zone={z} load={frame?.towers[z.tower]?.load ?? 0} />)}
      {scene.buildings.map((b) => <BuildingBox key={b.name} b={b} />)}
      {frame?.towers.map((t) => <TowerMast key={t.id} t={t} />)}
      {frame && <Links phones={frame.phones} towers={frame.towers} blockers={frame.blockers} />}
      {frame && <Phones phones={frame.phones} />}
      {frame?.blockers.map((b) => <BlockerBox key={b.id} b={b} />)}
      {frame?.problems.filter((p) => p.kind === 'booster' && p.x != null).map((p) => (
        <Booster key={p.id} x={p.x!} y={p.y!} />
      ))}
    </group>
  )
}

// ---------------------------------------------------------------- ground and click-to-place

function Ground({ extent }: { extent: [number, number, number, number] }) {
  const tool = useGame((s) => s.tool)
  const place = useGame((s) => s.place)
  const [hover, setHover] = useState<THREE.Vector3 | null>(null)
  const vehicleTool = tool && isVehicle(tool.kind) ? tool.kind : null
  const [x0, x1, y0, y1] = extent
  const w = x1 - x0
  const h = y1 - y0
  const centre = toV((x0 + x1) / 2, (y0 + y1) / 2)

  const toWorld = (p: THREE.Vector3) => ({ x: p.x + CX, y: -p.z + CY })
  const onDown = (e: ThreeEvent<PointerEvent>) => {
    if (!tool || e.button !== 0) return
    e.stopPropagation()
    const { x, y } = toWorld(e.point)
    void place(Math.round(x * 10) / 10, Math.round(y * 10) / 10)
  }

  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[centre.x, -0.05, centre.z]} receiveShadow
        onPointerDown={onDown}
        onPointerMove={(e) => tool && setHover(e.point.clone())}
        onPointerOut={() => setHover(null)}>
        <planeGeometry args={[w + 200, h + 200]} />
        <meshStandardMaterial color="#111827" />
      </mesh>
      {/* Station Road and its pavements */}
      <Strip x0={x0} x1={x1} y0={88} y1={112} color="#1f2937" />
      <Strip x0={x0} x1={x1} y0={82.5} y1={87.5} color="#334155" />
      <Strip x0={x0} x1={x1} y0={112.5} y1={117.5} color="#334155" />
      <Strip x0={222} x1={244} y0={113} y1={117} color="#0e7490" h={0.03} />
      <Html zIndexRange={[20, 0]} position={toV(233, 119, 0.2)} center className="pointer-events-none">
        <div className="label whitespace-nowrap text-cyan-300">Bus stop</div>
      </Html>
      {Array.from({ length: Math.floor(w / 12) }, (_, i) => (
        <Strip key={i} x0={x0 + i * 12 + 2} x1={x0 + i * 12 + 7} y0={99.7} y1={100.3} color="#64748b" h={0.03} />
      ))}
      {hover && tool && !vehicleTool && (
        <mesh position={[hover.x, 0.3, hover.z]} rotation-x={-Math.PI / 2}>
          <ringGeometry args={[3, 4.2, 32]} />
          <meshBasicMaterial color="#fbbf24" transparent opacity={0.9} />
        </mesh>
      )}
      {hover && vehicleTool && <PlacementGhost kind={vehicleTool} at={toWorld(hover)} extent={[x0, x1]} />}
    </group>
  )
}

/**
 * A see-through vehicle that follows the mouse, already snapped to the lane and slid to where the server
 * will actually park it: green where you point, amber if it has to move along to a free spot, red if the
 * road is full there.
 */
function PlacementGhost({ kind, at, extent }: { kind: 'bus' | 'truck' | 'car'; at: { x: number; y: number }; extent: [number, number] }) {
  const blockers = useGame((s) => s.frame?.blockers)
  const buildings = useGame((s) => s.scene?.buildings)
  const y = laneY(at.y)
  const spot = useMemo(() => {
    const rects: Rect[] = (blockers ?? []).map((b) => ({ x0: b.x0, x1: b.x1, y0: b.y0, y1: b.y1 }))
    const walls: Rect[] = (buildings ?? []).map((b) => ({ x0: b.x0, x1: b.x1, y0: b.y0, y1: b.y1 }))
    return freeSpot(kind, at.x, y, rects, walls, extent)
  }, [kind, at.x, y, blockers, buildings, extent])
  const x = spot ?? at.x
  const slid = spot !== null && Math.abs(spot - at.x) > 0.25
  const tint = spot === null ? '#ef4444' : slid ? '#f59e0b' : '#22c55e'
  const { length, width } = VEHICLE_SIZE[kind]
  return (
    <group position={toV(x, y)}>
      <Vehicle kind={kind} heading={headingFor(x - length / 2, x + length / 2, y - width / 2, y + width / 2)}
        opacity={0.45} tint={tint} />
      <Html zIndexRange={[20, 0]} position={[0, VEHICLE_SIZE[kind].height + 3, 0]} center className="pointer-events-none">
        <div className="label whitespace-nowrap" style={{ color: tint }}>
          {spot === null ? 'No room here' : slid ? `Moves ${Math.abs(spot - at.x).toFixed(0)} m to a free spot` : 'Click to park here'}
        </div>
      </Html>
    </group>
  )
}

function Strip({ x0, x1, y0, y1, color, h = 0.01 }: { x0: number; x1: number; y0: number; y1: number; color: string; h?: number }) {
  const c = toV((x0 + x1) / 2, (y0 + y1) / 2, h)
  return (
    <mesh rotation-x={-Math.PI / 2} position={c} receiveShadow>
      <planeGeometry args={[x1 - x0, y1 - y0]} />
      <meshStandardMaterial color={color} />
    </mesh>
  )
}

function ZoneArea({ zone, load }: { zone: Zone; load: number }) {
  const c = toV((zone.x0 + zone.x1) / 2, (zone.y0 + zone.y1) / 2, 0.06)
  const over = load > zone.max_load
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={c}>
        <planeGeometry args={[zone.x1 - zone.x0, zone.y1 - zone.y0]} />
        <meshBasicMaterial color={over ? '#ef4444' : '#f43f5e'} transparent opacity={over ? 0.35 : 0.13} />
      </mesh>
      <Html zIndexRange={[20, 0]} position={toV(zone.x0 + 4, zone.y0 + 12, 1)} className="pointer-events-none">
        <div data-tour="hospital" className={`label whitespace-nowrap ${over ? 'text-red-300' : 'text-rose-300'}`}>
          🏥 Protected: keep spare capacity · {Math.round(load * 100)}% used of {Math.round(zone.max_load * 100)}%{over ? ' · OVER LIMIT' : ''}
        </div>
      </Html>
    </group>
  )
}

function BuildingBox({ b }: { b: Building }) {
  const c = toV((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, b.height / 2)
  return (
    <group>
      <BuildingModel b={b} at={c} />
      <Html zIndexRange={[20, 0]} position={toV((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2, b.height + 3)} center className="pointer-events-none">
        <div className="label whitespace-nowrap text-slate-300">{b.name}</div>
      </Html>
    </group>
  )
}

// ---------------------------------------------------------------- network

function TowerMast({ t }: { t: Tower }) {
  const planned = useGame((s) => s.plannedTowers[t.id])
  const mode = useGame((s) => s.mode)
  const changed = planned && (Math.abs(planned.power - t.power_dbm) > 0.01 || Math.abs(planned.tilt - t.tilt) > 0.01)
  const base = toV(t.x, t.y)
  const sector = useMemo(() => {
    // the tower's coverage sector, drawn on the ground (boresight is degrees from east, counter-clockwise)
    const g = new THREE.CircleGeometry(70, 32, THREE.MathUtils.degToRad(t.boresight - 60), THREE.MathUtils.degToRad(120))
    g.rotateX(-Math.PI / 2)
    return g
  }, [t.boresight])
  return (
    <group position={base}>
      <mesh geometry={sector} position={[0, 0.08, 0]}>
        <meshBasicMaterial color="#38bdf8" transparent opacity={0.06} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[0, t.z / 2, 0]} castShadow>
        <cylinderGeometry args={[0.6, 0.9, t.z, 10]} />
        <meshStandardMaterial color="#cbd5e1" />
      </mesh>
      <mesh position={[0, t.z + 1, 0]}>
        <boxGeometry args={[2.4, 2, 2.4]} />
        <meshStandardMaterial color={changed ? '#fbbf24' : '#e2e8f0'} emissive={changed ? '#b45309' : '#0ea5e9'}
          emissiveIntensity={0.6} />
      </mesh>
      <Html zIndexRange={[20, 0]} position={[0, t.z + 9, 0]} center className="pointer-events-none">
        <div data-tour={t.id === 0 ? 'tower' : undefined} className="label whitespace-nowrap text-center">
          <div className="font-semibold text-sky-200">📡 {t.name}</div>
          {mode === 'expert' ? (
            <div className={changed ? 'text-amber-300' : 'text-slate-400'}>
              {t.power_dbm.toFixed(0)} dBm · tilt {t.tilt.toFixed(0)}° · load {(t.load * 100).toFixed(0)}%
            </div>
          ) : (
            <div className="text-slate-400">
              {(t.load * 100).toFixed(0)}% busy{changed ? <span className="text-amber-300"> · adjusted by agent</span> : ''}
            </div>
          )}
        </div>
      </Html>
    </group>
  )
}

/** Where the 2D segment a->b first enters the box, as a fraction along it (Liang–Barsky), or null. */
function hitBox(ax: number, ay: number, bx: number, by: number, b: Blocker): number | null {
  let t0 = 0
  let t1 = 1
  const dx = bx - ax
  const dy = by - ay
  const edges: [number, number][] = [[-dx, ax - b.x0], [dx, b.x1 - ax], [-dy, ay - b.y0], [dy, b.y1 - ay]]
  for (const [p, q] of edges) {
    if (p === 0) { if (q < 0) return null; continue }
    const r = q / p
    if (p < 0) { if (r > t1) return null; if (r > t0) t0 = r } else { if (r < t0) return null; if (r < t1) t1 = r }
  }
  return t0 > 0.02 && t0 < 0.98 ? t0 : null
}

/**
 * A line from each phone to the tower serving it, coloured by its signal. Where a bus, crowd or board
 * cuts the line, it is drawn red up to the obstacle with a ✖ there: the blockage you can see.
 */
function Links({ phones, towers, blockers }: { phones: Phone[]; towers: Tower[]; blockers: Blocker[] }) {
  const mode = useGame((s) => s.mode)
  const { geom, blockedGeom, hits } = useMemo(() => {
    const pos: number[] = []
    const col: number[] = []
    const bpos: number[] = []
    const hitPts: THREE.Vector3[] = []
    const c = new THREE.Color()
    for (const p of phones) {
      const t = towers[p.tower]
      if (!t) continue
      const a = toV(t.x, t.y, t.z + 1)
      const b = toV(p.x, p.y, 1.4)
      let hit: number | null = null
      for (const bl of blockers) {
        const h = hitBox(t.x, t.y, p.x, p.y, bl)
        if (h !== null && (hit === null || h < hit)) hit = h
      }
      if (hit !== null && p.band !== 'good') {
        const m = a.clone().lerp(b, hit)
        bpos.push(a.x, a.y, a.z, m.x, m.y, m.z)
        hitPts.push(m)
        continue
      }
      pos.push(a.x, a.y, a.z, b.x, b.y, b.z)
      c.set(BAND_COLOR[p.band])
      col.push(c.r, c.g, c.b, c.r, c.g, c.b)
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    const bg = new THREE.BufferGeometry()
    bg.setAttribute('position', new THREE.Float32BufferAttribute(bpos, 3))
    return { geom: g, blockedGeom: bg, hits: hitPts }
  }, [phones, towers, blockers])
  useEffect(() => () => { geom.dispose(); blockedGeom.dispose() }, [geom, blockedGeom])
  return (
    <group>
      <lineSegments geometry={geom}>
        <lineBasicMaterial vertexColors transparent opacity={mode === 'simple' ? 0.32 : 0.22} />
      </lineSegments>
      <lineSegments geometry={blockedGeom}>
        <lineBasicMaterial color="#ef4444" transparent opacity={0.9} />
      </lineSegments>
      {hits.map((h, i) => <BlockMark key={i} at={h} />)}
    </group>
  )
}

const crossGeom = new THREE.BoxGeometry(2.6, 0.5, 0.5)

function BlockMark({ at }: { at: THREE.Vector3 }) {
  return (
    <group position={at}>
      <mesh geometry={crossGeom} rotation-y={Math.PI / 4}><meshBasicMaterial color="#ef4444" /></mesh>
      <mesh geometry={crossGeom} rotation-y={-Math.PI / 4}><meshBasicMaterial color="#ef4444" /></mesh>
    </group>
  )
}

function Phones({ phones }: { phones: Phone[] }) {
  const focus = useFocusedIncident()
  const inFocus = useMemo(() => new Set(focus && !['resolved', 'false_alarm'].includes(focus.status) ? focus.phones : []),
    [focus])
  return (
    <group>
      {phones.map((p) => <PhoneDot key={p.id} p={p} focused={inFocus.has(p.id)} />)}
    </group>
  )
}

const dotGeom = new THREE.SphereGeometry(1.3, 14, 10)
const ringGeom = new THREE.RingGeometry(2.2, 2.9, 24)

function PhoneDot({ p, focused }: { p: Phone; focused: boolean }) {
  const ring = useRef<THREE.Mesh>(null)
  const [hover, setHover] = useState(false)
  const pos = toV(p.x, p.y, 1.4)
  const color = BAND_COLOR[p.band]
  useFrame(({ clock }) => {
    if (ring.current) {
      const s = 1 + 0.35 * Math.sin(clock.elapsedTime * 5)
      ring.current.scale.set(s, s, s)
    }
  })
  return (
    <group position={pos}>
      <mesh geometry={dotGeom} onPointerOver={() => setHover(true)} onPointerOut={() => setHover(false)}>
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={p.band === 'good' ? 0.5 : 1.1} />
      </mesh>
      {focused && (
        <mesh ref={ring} geometry={ringGeom} rotation-x={-Math.PI / 2} position={[0, -1.2, 0]}>
          <meshBasicMaterial color="#fbbf24" transparent opacity={0.85} side={THREE.DoubleSide} />
        </mesh>
      )}
      {hover && (
        <Html zIndexRange={[20, 0]} center position={[0, 5, 0]} className="pointer-events-none">
          <div className="label whitespace-nowrap">
            Phone {p.id} · {p.sinr.toFixed(0)} dB · {p.mbps.toFixed(1)}/{p.wants_mbps.toFixed(1)} Mbps · T{'ABC'[p.tower] ?? p.tower}
          </div>
        </Html>
      )}
    </group>
  )
}

// ---------------------------------------------------------------- problems on the street

function BlockerBox({ b }: { b: Blocker }) {
  const ref = useRef<THREE.Group>(null)
  const selected = useGame((s) => s.movable === b.id)
  const target = toV((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
  // glide between ticks so a driving bus moves smoothly instead of jumping 10 m a second
  useFrame((_, dt) => {
    if (ref.current) ref.current.position.lerp(target, Math.min(1, dt * 3))
  })
  const color = BLOCKER_COLOR[b.kind] ?? '#f87171'
  const vehicle = isVehicle(b.kind)
  return (
    <group ref={ref} position={target}>
      {vehicle ? (
        <Vehicle kind={b.kind as 'bus' | 'truck' | 'car'} id={b.id} heading={headingFor(b.x0, b.x1, b.y0, b.y1)}
          opacity={b.hidden ? 0.45 : 1} />
      ) : b.kind === 'hoarding' ? (
        <HoardingModel id={b.id} w={b.x1 - b.x0} d={b.y1 - b.y0} h={b.height} opacity={b.hidden ? 0.45 : 1} />
      ) : b.kind === 'crowd' ? (
        <CrowdModel id={b.id} w={b.x1 - b.x0} d={b.y1 - b.y0} h={b.height} opacity={b.hidden ? 0.45 : 1} />
      ) : (
        <mesh position={[0, b.height / 2, 0]} castShadow>
          <boxGeometry args={[b.x1 - b.x0, b.height, b.y1 - b.y0]} />
          <meshStandardMaterial color={color} transparent={b.hidden} opacity={b.hidden ? 0.45 : 1}
            emissive={color} emissiveIntensity={0.15} />
        </mesh>
      )}
      {selected && <Footprint w={b.x1 - b.x0} d={b.y1 - b.y0} />}
      <Html zIndexRange={[20, 0]} position={[0, b.height + 3, 0]} center className="pointer-events-none">
        <div data-tour="blocker" className={`label whitespace-nowrap font-semibold ${vehicle && !selected ? 'opacity-70' : ''}`}
          style={{ color: vehicle || b.kind === 'hoarding' || b.kind === 'crowd' ? '#e2e8f0' : color }}>
          {vehicle || b.kind === 'hoarding' || b.kind === 'crowd' ? '' : '⬛ '}
          {b.kind}{b.hidden ? ' (twin can’t see)' : ''}{selected ? ' · ◀ ▶ moves it' : ''}
        </div>
      </Html>
    </group>
  )
}

/** Amber outline on the ground around the blocker the arrow buttons will move. */
function Footprint({ w, d }: { w: number; d: number }) {
  const pad = 0.8
  const edge = 0.25
  const parts: [number, number, number, number][] = [
    [0, -(d / 2 + pad), w + 2 * pad, edge], [0, d / 2 + pad, w + 2 * pad, edge],
    [-(w / 2 + pad), 0, edge, d + 2 * pad], [w / 2 + pad, 0, edge, d + 2 * pad],
  ]
  return (
    <group position={[0, 0.06, 0]}>
      {parts.map(([x, z, sx, sz], i) => (
        <mesh key={i} position={[x, 0, z]} rotation-x={-Math.PI / 2}>
          <planeGeometry args={[sx, sz]} />
          <meshBasicMaterial color="#fbbf24" />
        </mesh>
      ))}
    </group>
  )
}

function Booster({ x, y }: { x: number; y: number }) {
  const ref = useRef<THREE.Mesh>(null)
  useFrame(({ clock }) => {
    if (ref.current) {
      const s = 1 + ((clock.elapsedTime * 0.8) % 1) * 5
      ref.current.scale.set(s, s, s)
      ;(ref.current.material as THREE.MeshBasicMaterial).opacity = 0.6 * (1 - ((clock.elapsedTime * 0.8) % 1))
    }
  })
  return (
    <group position={toV(x, y, 0.3)}>
      <mesh ref={ref} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[3, 3.6, 32]} />
        <meshBasicMaterial color="#f43f5e" transparent opacity={0.6} />
      </mesh>
      <mesh position={[0, 2, 0]}>
        <boxGeometry args={[2, 4, 2]} />
        <meshStandardMaterial color="#f43f5e" emissive="#f43f5e" emissiveIntensity={0.6} />
      </mesh>
      <Html zIndexRange={[20, 0]} position={[0, 7, 0]} center className="pointer-events-none">
        <div className="label whitespace-nowrap text-rose-300">📶 illegal booster</div>
      </Html>
    </group>
  )
}
