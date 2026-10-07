// Vehicle sizes and the spacing rule, shared by the 3D models and the placement preview.
// Sizes match the simulator (src/nethealers/sim/config.py BLOCKER_TYPES); spacing mirrors sim/space.py.

export const VEHICLE_SIZE: Record<VehicleKind, { length: number; width: number; height: number }> = {
  bus: { length: 14, width: 2.6, height: 3.4 },
  truck: { length: 9, width: 2.5, height: 4.0 },
  car: { length: 4.5, width: 1.8, height: 1.5 },
}
export type VehicleKind = 'bus' | 'truck' | 'car'
export const isVehicle = (kind: string): kind is VehicleKind => kind in VEHICLE_SIZE

/** Which way a vehicle on Station Road faces: traffic keeps left, so the north lane heads east. */
export function headingFor(x0: number, x1: number, y0: number, y1: number): number {
  const alongY = y1 - y0 > x1 - x0
  const northLane = (y0 + y1) / 2 > 100
  if (alongY) return northLane ? Math.PI / 2 : -Math.PI / 2
  return northLane ? 0 : Math.PI
}

/** Client-side copy of the server's spacing rule, for the placement preview. */
export const GAP_M = 1.0

export interface Rect { x0: number; x1: number; y0: number; y1: number }

function touches(a: Rect, b: Rect, gap: number): boolean {
  return a.x0 < b.x1 + gap && a.x1 > b.x0 - gap && a.y0 < b.y1 + gap && a.y1 > b.y0 - gap
}

/** Nearest centre x along the lane where `kind` fits, or null: mirrors sim/space.py free_spot. */
export function freeSpot(kind: VehicleKind, x: number, y: number, blockers: Rect[], buildings: Rect[],
  extent: [number, number]): number | null {
  const { length, width } = VEHICLE_SIZE[kind]
  const rect = (cx: number): Rect => ({ x0: cx - length / 2, x1: cx + length / 2, y0: y - width / 2, y1: y + width / 2 })
  for (let k = 0; k <= 160; k++) {
    for (const cx of k === 0 ? [x] : [x + k * 0.5, x - k * 0.5]) {
      if (cx - length / 2 < extent[0] || cx + length / 2 > extent[1]) continue
      const r = rect(cx)
      if (blockers.some((b) => touches(r, b, GAP_M)) || buildings.some((b) => touches(r, b, 0))) continue
      return cx
    }
  }
  return null
}

/** Lane centres of Station Road (traffic keeps left, so the north lane heads east). */
export const laneY = (y: number) => (y > 100 ? 107.8 : 92.2)
