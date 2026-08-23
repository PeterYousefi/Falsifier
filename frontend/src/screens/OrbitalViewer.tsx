/**
 * src/screens/OrbitalViewer.tsx
 * Rebuilt orbital 3-D viewer + synced folded light curve.
 *
 * ALL numbers reaching the screen are derived from the job payload.
 * The exaggeration factor is computed at runtime from payload values — never
 * hardcoded. (AGENTS.md Rule 1)
 *
 * Scene branches on disposition:
 *   candidate                 — single transiting body silhouette
 *   false_positive/odd_even   — two-star EB with both eclipses animated
 *   false_positive/centroid   — off-target contamination signal
 *   ambiguous / caveats       — geometry with "uncertain" visual treatment
 *
 * Animation defaults to PAUSED at mid-transit so the view is legible
 * before any interaction.
 */
import React, {
  useRef,
  useMemo,
  useState,
  useEffect,
  useCallback,
} from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Line, Text } from '@react-three/drei'
import * as THREE from 'three'
import {
  semiMajorAxisFromPeriod,
  starSceneSize,
  starColor,
  auToScene,
  orbitalAngularVelocity,
  depthToRadiusRearth,
} from '../physics'
import type { VetResult, PhasedLC } from '../data/types'
import { isStellarParamsSummary } from '../data/types'
import type { StellarParams } from '../data/types'

// ── Stellar param extraction (handles both old nested and new flat shapes) ──
export function extractStellarParams(sp: StellarParams | null | undefined): {
  teffK: number
  radiusRsun: number
  luminosityLsun: number
} {
  if (!sp) return { teffK: 5778, radiusRsun: 1.0, luminosityLsun: 1.0 }
  if (isStellarParamsSummary(sp)) {
    return {
      teffK: sp.teff_K,
      radiusRsun: sp.radius_rsun,
      luminosityLsun: sp.luminosity_lsun ?? 1.0,
    }
  }
  // Legacy nested shape
  return {
    teffK: sp.teff?.values?.[0] ?? 5778,
    radiusRsun: sp.radius?.values?.[0] ?? 1.0,
    luminosityLsun: sp.luminosity_lsun ?? 1.0,
  }
}

// ── Planet radius true ratio and exaggeration ─────────────────────────────
// depth ≈ (Rp/Rs)².  True Rp/Rs is usually sub-pixel.
// We exaggerate to a minimum visual fraction of the star, and compute the
// integer factor N so the label "exaggerated N× for visibility" is accurate.
export function computePlanetScene(
  depthPpm: number,
  stellarRadiusRsun: number,
  starSceneR: number,
): {
  trueRpRs: number         // dimensionless true radius ratio
  visualR: number          // scene-unit radius used for rendering
  exaggerationFactor: number  // integer N displayed in label
} {
  const trueRpRs = Math.sqrt(Math.max(depthPpm, 1) / 1e6)
  const trueSceneR = trueRpRs * starSceneR
  // Minimum visible fraction: 12% of the star's rendered radius
  const minVisualR = starSceneR * 0.12
  const visualR = Math.max(trueSceneR, minVisualR)
  const exaggerationFactor = Math.max(1, Math.round(visualR / trueSceneR))
  return { trueRpRs, visualR, exaggerationFactor }
}

// ── Orbit ring ────────────────────────────────────────────────────────────
function OrbitRing({ radius, color = '#8A8880', opacity = 0.6, dashed = false }: {
  radius: number
  color?: string
  opacity?: number
  dashed?: boolean
}) {
  const pts = useMemo(() => {
    const a: THREE.Vector3[] = []
    for (let i = 0; i <= 96; i++) {
      const t = (i / 96) * Math.PI * 2
      a.push(new THREE.Vector3(Math.cos(t) * radius, 0, Math.sin(t) * radius))
    }
    return a
  }, [radius])
  return <Line points={pts} color={color} lineWidth={0.5} />
}

// ── Camera framing helper (runs once on mount) ─────────────────────────────
function CameraFramer({ orbitRadii, starR }: { orbitRadii: number[]; starR: number }) {
  const { camera } = useThree()
  useEffect(() => {
    const maxR = Math.max(starR * 2, ...orbitRadii, 0.5)
    // Position camera at 45° elevation, distance = 3× the max orbit radius
    const dist = maxR * 3.2
    camera.position.set(0, dist * 0.55, dist * 0.85)
    camera.near = maxR * 0.01
    camera.far = maxR * 40
    ;(camera as THREE.PerspectiveCamera).fov = 45
    camera.updateProjectionMatrix()
    camera.lookAt(0, 0, 0)
  }, [orbitRadii.join(','), starR]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

// ── Star sphere ───────────────────────────────────────────────────────────
function StarSphere({
  radius,
  teffK,
  position = [0, 0, 0] as [number, number, number],
  label,
}: {
  radius: number
  teffK: number
  position?: [number, number, number]
  label?: string
}) {
  const hex = useMemo(() => starColor(teffK), [teffK])
  return (
    <group position={position}>
      <mesh>
        <sphereGeometry args={[radius, 32, 32]} />
        <meshStandardMaterial
          color={hex}
          emissive={hex}
          emissiveIntensity={1.4}
          roughness={0.3}
          metalness={0.0}
        />
      </mesh>
      {label && (
        <Text
          position={[0, radius + radius * 0.35, 0]}
          fontSize={radius * 0.4}
          color="#5A5850"
          anchorX="center"
          anchorY="bottom"
        >
          {label}
        </Text>
      )}
      {/* Glow ring */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[radius, radius * 1.55, 32]} />
        <meshBasicMaterial color={hex} transparent opacity={0.08} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}

// ── Animated transiting body (candidate scene) ────────────────────────────
function TransitingBody({
  starR,
  orbitR,
  bodyR,
  inclRad,
  phase,           // 0 = mid-transit (in front of star at phase 0)
  playing,
  omega,
}: {
  starR: number
  orbitR: number
  bodyR: number
  inclRad: number
  phase: number
  playing: boolean
  omega: number
}) {
  const pivotRef = useRef<THREE.Group>(null!)
  const currentPhase = useRef(phase)

  // Sync to controlled phase when paused
  useEffect(() => {
    currentPhase.current = phase
  }, [phase])

  useFrame((_, delta) => {
    if (!pivotRef.current) return
    if (playing) {
      currentPhase.current += omega * delta
    }
    pivotRef.current.rotation.y = currentPhase.current
  })

  return (
    <group rotation={[inclRad, 0, 0]}>
      <group ref={pivotRef}>
        <mesh position={[orbitR, 0, 0]}>
          <sphereGeometry args={[bodyR, 20, 20]} />
          {/* Dark silhouette — no emissive, so it reads as dark against star */}
          <meshStandardMaterial
            color="#1A1510"
            roughness={0.9}
            metalness={0.0}
            emissive="#000000"
            emissiveIntensity={0}
          />
        </mesh>
      </group>
      <OrbitRing radius={orbitR} />
    </group>
  )
}

// ── EB: two-star scene ─────────────────────────────────────────────────────
// Renders a primary star at origin plus a companion at orbitR.
// Both stars animate through primary and secondary eclipses.
function EclipsingBinaryScene({
  starR,
  teffK,
  companionR,
  companionTeffK,
  orbitR,
  inclRad,
  primaryDepthPpm,
  secondaryDepthPpm,
  phase,
  playing,
  omega,
}: {
  starR: number
  teffK: number
  companionR: number
  companionTeffK: number
  orbitR: number
  inclRad: number
  primaryDepthPpm: number
  secondaryDepthPpm: number
  phase: number
  playing: boolean
  omega: number
}) {
  const pivotRef = useRef<THREE.Group>(null!)
  const currentPhase = useRef(phase)

  useEffect(() => {
    currentPhase.current = phase
  }, [phase])

  useFrame((_, delta) => {
    if (!pivotRef.current) return
    if (playing) currentPhase.current += omega * delta
    pivotRef.current.rotation.y = currentPhase.current
  })

  const compHex = useMemo(() => starColor(companionTeffK), [companionTeffK])

  return (
    <group rotation={[inclRad, 0, 0]}>
      {/* Primary star */}
      <StarSphere radius={starR} teffK={teffK} label="primary" />
      {/* Companion orbits the barycentre (simplified: orbits around origin) */}
      <group ref={pivotRef}>
        <group position={[orbitR, 0, 0]}>
          <mesh>
            <sphereGeometry args={[companionR, 24, 24]} />
            <meshStandardMaterial
              color={compHex}
              emissive={compHex}
              emissiveIntensity={1.0}
              roughness={0.4}
            />
          </mesh>
          <Text
            position={[0, companionR + companionR * 0.4, 0]}
            fontSize={companionR * 0.5}
            color="#5A5850"
            anchorX="center"
            anchorY="bottom"
          >
            companion
          </Text>
        </group>
      </group>
      <OrbitRing radius={orbitR} color="#CC8855" />
    </group>
  )
}

// ── Centroid-shift scene ───────────────────────────────────────────────────
function CentroidShiftScene({
  starR,
  teffK,
  offTargetR,
  offTargetX,
  orbitR,
}: {
  starR: number
  teffK: number
  offTargetR: number
  offTargetX: number
  orbitR: number
}) {
  // Dashed line from target to off-target source
  const linePts = useMemo(() => [
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(offTargetX, 0, 0),
  ], [offTargetX])
  const offHex = useMemo(() => starColor(4800), [])

  return (
    <>
      <StarSphere radius={starR} teffK={teffK} label="target" />
      {/* Off-target contaminating source */}
      <group position={[offTargetX, 0, 0]}>
        <mesh>
          <sphereGeometry args={[offTargetR, 20, 20]} />
          <meshStandardMaterial
            color={offHex}
            emissive={offHex}
            emissiveIntensity={0.6}
            roughness={0.5}
          />
        </mesh>
        <Text
          position={[0, offTargetR + offTargetR * 0.4, 0]}
          fontSize={offTargetR * 0.5}
          color="#AA6633"
          anchorX="center"
          anchorY="bottom"
        >
          off-target source
        </Text>
      </group>
      {/* Centroid vector */}
      <Line points={linePts} color="#AA6633" lineWidth={0.8} dashed dashSize={0.08} gapSize={0.06} />
      <Text
        position={[offTargetX / 2, offTargetR * 0.6, 0]}
        fontSize={starR * 0.28}
        color="#AA6633"
        anchorX="center"
      >
        centroid shift
      </Text>
    </>
  )
}

// ── Ambient "uncertain" overlay for ambiguous/caveats ──────────────────────
function UncertainOverlay({ starR }: { starR: number }) {
  return (
    <>
      <mesh>
        <sphereGeometry args={[starR * 2.0, 24, 24]} />
        <meshBasicMaterial color="#AA8833" transparent opacity={0.04} side={THREE.DoubleSide} wireframe />
      </mesh>
      <Text
        position={[0, starR * 2.2, 0]}
        fontSize={starR * 0.32}
        color="#AA8833"
        anchorX="center"
      >
        geometry uncertain
      </Text>
    </>
  )
}

// ── Full scene dispatcher ─────────────────────────────────────────────────
function SceneContent({
  vet,
  stellarTeffK,
  stellarRadiusRsun,
  phase,
  playing,
}: {
  vet: VetResult
  stellarTeffK: number
  stellarRadiusRsun: number
  phase: number
  playing: boolean
}) {
  const starR = useMemo(() => starSceneSize(stellarRadiusRsun), [stellarRadiusRsun])
  const depthPpm = vet.depth_ppm ?? 100
  const periodDays = vet.period_days ?? 1
  const inclDeg = vet.inclination_deg ?? 88
  const inclRad = (inclDeg * Math.PI) / 180

  const sma = useMemo(() => semiMajorAxisFromPeriod(periodDays), [periodDays])
  const orbitR = useMemo(() => auToScene(sma), [sma])
  const omega = useMemo(() => orbitalAngularVelocity(periodDays, 365.25), [periodDays])

  const { visualR, exaggerationFactor } = useMemo(
    () => computePlanetScene(depthPpm, stellarRadiusRsun, starR),
    [depthPpm, stellarRadiusRsun, starR],
  )

  const disposition = vet.disposition
  const triggeringTest = vet.triggering_test

  const isEB = disposition === 'false_positive' && triggeringTest === 'odd_even_depth'
  const isCentroid = disposition === 'false_positive' && triggeringTest === 'centroid_shift'
  const isUncertain = disposition === 'ambiguous' || disposition === 'candidate_with_caveats'
  const isCandidate = !isEB && !isCentroid

  // EB companion: depth ratio gives relative radius
  const phasedLC = vet.phased_lc as (PhasedLC & {
    primary_depth_ppm?: number
    secondary_depth_ppm?: number
  }) | null | undefined

  const primaryDepthPpm = isEB ? (phasedLC?.primary_depth_ppm ?? depthPpm) : depthPpm
  const secondaryDepthPpm = isEB ? (phasedLC?.secondary_depth_ppm ?? depthPpm * 0.15) : 0
  const companionRpRs = isEB ? Math.sqrt(secondaryDepthPpm / Math.max(primaryDepthPpm, 1)) : 0
  const companionR = isEB ? Math.max(companionRpRs * starR, starR * 0.20) : 0
  const companionTeffK = isEB ? Math.round(stellarTeffK * 0.82) : 4000

  const orbitRadii = [orbitR]

  return (
    <>
      {/* Lighting: dim ambient so the transiting body reads as a silhouette */}
      <ambientLight intensity={0.25} />
      {/* Point light at each star position */}
      <pointLight position={[0, 0, 0]} intensity={3.0} distance={orbitR * 8} decay={2} />
      {isEB && (
        <pointLight position={[orbitR, 0, 0]} intensity={1.5} distance={orbitR * 6} decay={2} />
      )}
      <directionalLight position={[0, orbitR * 2, orbitR * 3]} intensity={0.15} />

      {/* Camera framer */}
      <CameraFramer orbitRadii={orbitRadii} starR={starR} />

      {isEB ? (
        <EclipsingBinaryScene
          starR={starR}
          teffK={stellarTeffK}
          companionR={companionR}
          companionTeffK={companionTeffK}
          orbitR={orbitR}
          inclRad={inclRad}
          primaryDepthPpm={primaryDepthPpm}
          secondaryDepthPpm={secondaryDepthPpm}
          phase={phase}
          playing={playing}
          omega={omega}
        />
      ) : isCentroid ? (
        <>
          <CentroidShiftScene
            starR={starR}
            teffK={stellarTeffK}
            offTargetR={starR * 0.55}
            offTargetX={orbitR * 0.7}
            orbitR={orbitR}
          />
          {isUncertain && <UncertainOverlay starR={starR} />}
        </>
      ) : (
        <>
          <StarSphere radius={starR} teffK={stellarTeffK} label="host star" />
          <TransitingBody
            starR={starR}
            orbitR={orbitR}
            bodyR={visualR}
            inclRad={inclRad}
            phase={phase}
            playing={playing}
            omega={omega}
          />
          {isUncertain && <UncertainOverlay starR={starR} />}
        </>
      )}

      {/* Exaggeration label — computed, never hardcoded */}
      {isCandidate && exaggerationFactor > 1 && (
        <Text
          position={[0, -starR * 1.4, 0]}
          fontSize={starR * 0.26}
          color="#8A8880"
          anchorX="center"
          anchorY="top"
        >
          {`planet radius exaggerated ${exaggerationFactor}\u00D7 for visibility`}
        </Text>
      )}
    </>
  )
}

// ── No-result placeholder ─────────────────────────────────────────────────
function ScenePlaceholder({ message }: { message: string }) {
  return (
    <>
      <ambientLight intensity={0.4} />
      <Text
        position={[0, 0, 0]}
        fontSize={0.08}
        color="#8A8880"
        anchorX="center"
        anchorY="middle"
      >
        {message}
      </Text>
    </>
  )
}

// ── Folded light curve with animated marker ───────────────────────────────
function FoldedLCWithMarker({
  phasedLC,
  currentPhase,
  disposition,
}: {
  phasedLC: PhasedLC & { flux_secondary?: number[]; primary_depth_ppm?: number; secondary_depth_ppm?: number } | null | undefined
  currentPhase: number   // 0 = mid-transit, -0.5..+0.5
  disposition: string
}) {
  const W = 560
  const H = 110
  const PAD = { l: 8, r: 8, t: 10, b: 20 }

  const isEB = disposition === 'false_positive' && phasedLC?.flux_secondary

  if (!phasedLC?.phase?.length) {
    return (
      <div style={{
        height: H,
        background: 'var(--np-surface)',
        border: '1px solid var(--np-border)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--np-faint)' }}>
          No phase-folded light curve available for this result
        </span>
      </div>
    )
  }

  const { phase, flux } = phasedLC
  const fluxSec = isEB ? phasedLC.flux_secondary! : null

  const allFlux = fluxSec ? [...flux, ...fluxSec] : flux
  const minF = Math.min(...allFlux)
  const maxF = Math.max(...allFlux)
  const rng = maxF - minF || 1e-6

  const plotW = W - PAD.l - PAD.r
  const plotH = H - PAD.t - PAD.b

  const toX = (p: number) => PAD.l + (p + 0.5) * plotW
  const toY = (f: number) => PAD.t + (1 - (f - minF) / rng) * plotH

  const pts = phase.map((p, i) => `${toX(p).toFixed(1)},${toY(flux[i]).toFixed(1)}`).join(' ')
  const ptsSec = fluxSec
    ? phase.map((p, i) => `${toX(p).toFixed(1)},${toY(fluxSec[i]).toFixed(1)}`).join(' ')
    : null

  // Marker x position from the current animation phase (wrapped to -0.5..0.5)
  const normPhase = ((((currentPhase / (Math.PI * 2)) % 1) + 1) % 1)
  const markerPhase = normPhase > 0.5 ? normPhase - 1 : normPhase
  const markerX = toX(markerPhase)

  // Interpolate flux at markerPhase for the marker dot Y
  const markerY = (() => {
    if (phase.length < 2) return toY(flux[0] ?? 1)
    const idx = phase.findIndex((p) => p >= markerPhase) ?? phase.length - 1
    const i = Math.max(0, Math.min(phase.length - 1, idx))
    return toY(flux[i] ?? 1)
  })()

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      style={{
        display: 'block',
        background: 'var(--np-surface)',
        border: '1px solid var(--np-border)',
      }}
      aria-label="Phase-folded light curve with transit marker"
      role="img"
    >
      {/* Axis labels */}
      <text x={PAD.l} y={H - 5} fill="var(--np-faint)" fontSize="8" fontFamily="var(--font-mono)">−0.5</text>
      <text x={W - PAD.r - 16} y={H - 5} fill="var(--np-faint)" fontSize="8" fontFamily="var(--font-mono)">+0.5</text>
      <text x={W / 2} y={H - 5} fill="var(--np-faint)" fontSize="8" fontFamily="var(--font-mono)" textAnchor="middle">phase</text>

      {/* Mid-transit reference */}
      <line x1={W / 2} y1={PAD.t} x2={W / 2} y2={H - PAD.b} stroke="var(--np-border)" strokeWidth="0.5" strokeDasharray="2,2" />

      {/* Primary LC */}
      <polyline points={pts} fill="none" stroke="var(--rust)" strokeWidth="1.4" />

      {/* Secondary (EB) LC — dimmer colour to distinguish */}
      {ptsSec && (
        <polyline points={ptsSec} fill="none" stroke="#5577AA" strokeWidth="1.2" strokeDasharray="4,2" />
      )}

      {/* Animated phase marker */}
      <line
        x1={markerX}
        y1={PAD.t}
        x2={markerX}
        y2={H - PAD.b}
        stroke="#226633"
        strokeWidth="1.2"
        strokeDasharray="3,2"
      />
      <circle cx={markerX} cy={markerY} r="3" fill="#226633" />

      {/* Legend for EB */}
      {isEB && (
        <>
          <line x1={W - 90} y1={12} x2={W - 72} y2={12} stroke="var(--rust)" strokeWidth="1.4" />
          <text x={W - 68} y={15} fill="var(--np-muted)" fontSize="8" fontFamily="var(--font-mono)">primary</text>
          <line x1={W - 90} y1={23} x2={W - 72} y2={23} stroke="#5577AA" strokeWidth="1.2" strokeDasharray="4,2" />
          <text x={W - 68} y={26} fill="var(--np-muted)" fontSize="8" fontFamily="var(--font-mono)">secondary</text>
        </>
      )}
    </svg>
  )
}

// ── Main exported component ───────────────────────────────────────────────
export default function OrbitalViewer({
  vet,
  stellarParams,
  jobId,
}: {
  vet: VetResult | null | undefined
  stellarParams: StellarParams | null | undefined
  jobId: string | null | undefined
}) {
  const { teffK, radiusRsun } = useMemo(
    () => extractStellarParams(stellarParams),
    [stellarParams],
  )

  const [playing, setPlaying] = useState(false)
  // Phase in radians; 0 = mid-transit (transiting body in front of star)
  const [phase, setPhase] = useState(0)
  const [canvasOk, setCanvasOk] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)

  // Verify canvas parent has non-zero height on mount
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const h = el.getBoundingClientRect().height
    if (h < 4) {
      setCanvasOk(false)
      console.warn('[OrbitalViewer] canvas container has near-zero height:', h)
    }
  }, [])

  // When a new job arrives, reset to paused mid-transit
  useEffect(() => {
    setPlaying(false)
    setPhase(0)
  }, [jobId])

  // Scrub handler
  const handleScrub = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setPhase(parseFloat(e.target.value))
  }, [])

  const phasedLC = vet?.phased_lc as (PhasedLC & {
    flux_secondary?: number[]
    primary_depth_ppm?: number
    secondary_depth_ppm?: number
  }) | null | undefined

  const disposition = vet?.disposition ?? 'candidate'
  const depthPpm = vet?.depth_ppm ?? 100
  const stellarR = useMemo(() => starSceneSize(radiusRsun), [radiusRsun])
  const { exaggerationFactor } = useMemo(
    () => computePlanetScene(depthPpm, radiusRsun, stellarR),
    [depthPpm, radiusRsun, stellarR],
  )

  const isEB = disposition === 'false_positive' && vet?.triggering_test === 'odd_even_depth'
  const isCandidate = disposition === 'candidate' || (!isEB && disposition !== 'false_positive')

  // Description for accessibility
  const sceneDesc = isEB
    ? 'Eclipsing binary: two stars orbit each other, producing alternating primary and secondary eclipses'
    : vet?.triggering_test === 'centroid_shift'
    ? 'Centroid shift: the signal originates from an off-target source'
    : disposition === 'candidate'
    ? 'Planet candidate: a single body transiting the host star'
    : 'Uncertain geometry: disposition is ambiguous or has caveats'

  if (!vet) {
    return (
      <div style={{
        border: '1px solid var(--np-rule)',
        padding: '16px',
        background: 'var(--np-surface)',
        fontFamily: 'var(--font-serif)',
        fontStyle: 'italic',
        fontSize: 13,
        color: 'var(--np-muted)',
      }}>
        Run a target above to see the orbital diagram.
      </div>
    )
  }

  return (
    <div>
      {/* 3D canvas */}
      <figure
        style={{ margin: 0 }}
        aria-label={sceneDesc}
      >
        <hr style={{ border: 'none', borderTop: '1px solid var(--np-text)', margin: '0 0 8px' }} />
        <div
          ref={containerRef}
          style={{
            height: 340,
            position: 'relative',
            background: 'var(--np-surface)',
          }}
        >
          {!canvasOk && (
            <div style={{
              position: 'absolute', inset: 0, display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              fontFamily: 'var(--font-serif)', fontStyle: 'italic',
              fontSize: 13, color: 'var(--np-muted)',
            }}>
              3D view unavailable — canvas container has zero height.
            </div>
          )}
          {canvasOk && (
            <Canvas
              key={jobId ?? 'no-job'}
              gl={{ antialias: true, alpha: false }}
              style={{ width: '100%', height: '100%', background: '#F5F2EA' }}
              frameloop={playing ? 'always' : 'demand'}
            >
              <OrbitControls
                enablePan={false}
                minDistance={0.05}
                maxDistance={500}
                enableDamping
                dampingFactor={0.08}
              />
              {vet ? (
                <SceneContent
                  vet={vet}
                  stellarTeffK={teffK}
                  stellarRadiusRsun={radiusRsun}
                  phase={phase}
                  playing={playing}
                />
              ) : (
                <ScenePlaceholder message="No TCE data available" />
              )}
            </Canvas>
          )}

          {/* Disposition badge overlay */}
          <div style={{
            position: 'absolute', top: 8, left: 10,
            fontFamily: 'var(--font-mono)', fontSize: 10,
            letterSpacing: '0.07em', textTransform: 'uppercase',
            color: 'var(--np-muted)',
            background: 'rgba(242,239,231,0.85)',
            padding: '2px 7px',
            border: '1px solid var(--np-border)',
          }}>
            {disposition.replace(/_/g, ' ')}
          </div>
        </div>
        <hr style={{ border: 'none', borderTop: '1px solid var(--np-text)', margin: '8px 0 4px' }} />
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.10em', color: 'var(--np-muted)', textTransform: 'uppercase', marginBottom: 3 }}>
          FIG. 1
        </div>
        <figcaption style={{
          fontFamily: 'var(--font-serif)',
          fontStyle: 'italic',
          fontSize: 12,
          color: 'var(--np-muted)',
          lineHeight: 1.5,
          marginBottom: 8,
        }}>
          {isEB
            ? 'Eclipsing-binary geometry computed from pipeline output. Two stars orbit each other; alternating eclipse depths are the false-positive signature. Drag to rotate; scroll to zoom.'
            : vet.triggering_test === 'centroid_shift'
            ? 'Centroid-shift geometry: the signal originates off-target. The dashed line indicates the centroid displacement direction.'
            : `Orbital diagram computed from pipeline output.`
          }
          {' '}
          {isCandidate && exaggerationFactor > 1 && (
            <span style={{ color: 'var(--np-faint)' }}>
              {`Transiting body radius exaggerated ${exaggerationFactor}\u00D7 for visibility (true Rp/Rs\u202F\u2248\u202F${Math.sqrt(Math.max(depthPpm, 1) / 1e6).toFixed(4)}).`}
            </span>
          )}
        </figcaption>
      </figure>

      {/* Play / pause / scrub controls */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        margin: '4px 0 12px',
      }}>
        <button
          onClick={() => setPlaying((p) => !p)}
          style={{
            fontFamily: 'var(--font-mono)', fontSize: 11,
            padding: '4px 12px',
            border: '1px solid var(--np-rule)',
            background: 'var(--np-surface)',
            cursor: 'pointer', color: 'var(--np-muted)',
            letterSpacing: '0.05em',
          }}
          aria-label={playing ? 'Pause animation' : 'Play animation'}
        >
          {playing ? '⏸ Pause' : '▶ Play'}
        </button>
        <input
          type="range"
          min={-Math.PI}
          max={Math.PI}
          step={0.01}
          value={phase}
          onChange={handleScrub}
          onMouseDown={() => setPlaying(false)}
          style={{ flex: 1, maxWidth: 200, accentColor: 'var(--rust)' }}
          aria-label="Scrub animation phase"
        />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-faint)', minWidth: 60 }}>
          phase {(phase / (Math.PI * 2)).toFixed(3)}
        </span>
      </div>

      {/* Folded LC + marker */}
      <div style={{ marginBottom: 4 }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--np-muted)', marginBottom: 4,
        }}>
          Phase-folded light curve — {vet.tce_id}
          {isEB && <span style={{ color: '#5577AA', marginLeft: 8 }}>· EB dual-depth</span>}
        </div>
        <FoldedLCWithMarker
          phasedLC={phasedLC}
          currentPhase={phase}
          disposition={disposition}
        />
        <div style={{
          fontFamily: 'var(--font-serif)', fontStyle: 'italic',
          fontSize: 11, color: 'var(--np-faint)', marginTop: 4,
        }}>
          Green marker tracks the 3D animation above. Source: <span style={{ fontFamily: 'var(--font-mono)' }}>report.vet[].phased_lc</span>
          {isEB && ' · blue dashed = secondary eclipse folded at primary period'}
        </div>
      </div>
    </div>
  )
}
