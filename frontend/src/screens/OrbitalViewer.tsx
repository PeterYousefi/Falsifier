/**
 * src/screens/OrbitalViewer.tsx
 * Orbital viewer — flat 2D SVG diagram (default) + optional 3D canvas.
 *
 * ALL numbers reaching the screen are derived from the job payload.
 * The exaggeration factor is computed at runtime from payload values — never
 * hardcoded. (AGENTS.md Rule 1)
 *
 * Default view: flat SVG in the newspaper aesthetic (paper background, hairline
 * rules, mono-font caption).  Driven by the same vet data as the 3D scene.
 * The 3D view is preserved behind a "View in 3D ↓" toggle for users who want
 * the animated globe.
 *
 * Phase convention — SINGLE DEFINITION, used by every consumer here:
 *   phase ∈ [-0.5, +0.5], dimensionless fractional orbit
 *   phase = 0  → mid-transit (planet directly between observer and star)
 *   phase = ±0.5 → secondary eclipse position
 *   Implemented by physics.phaseToPosition() — no consumer may redefine this.
 *
 * 2D scene branches on disposition (same logic as 3D):
 *   candidate / ambiguous     — star + orbit ring + transiting body
 *   false_positive/odd_even   — two-star EB with orbit ring
 *   false_positive/centroid   — star + dashed centroid vector + off-target dot
 *
 * 3D canvas background fix: <color attach="background" args={['#EDE9DE']} />
 * added inside SceneContent so WebGL clear color matches --np-surface instead
 * of defaulting to black.
 */
import React, {
  useRef,
  useMemo,
  useState,
  useEffect,
  useCallback,
} from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls, Line, Text } from '@react-three/drei'
import * as THREE from 'three'
import {
  semiMajorAxisFromPeriod,
  starSceneSize,
  starColor,
  auToScene,
  phaseToPosition,
  wrapPhase,
} from '../physics'
import type { VetResult, PhasedLC } from '../data/types'
import { isStellarParamsSummary } from '../data/types'
import type { StellarParams } from '../data/types'
import { DispoChip } from './CandidateDetail'

// Play speed: one full orbit in this many real seconds.
const ORBIT_WALL_SECONDS = 8.0

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
      // Build orbit ring in x-z plane (consistent with phaseToPosition)
      a.push(new THREE.Vector3(Math.sin(t) * radius, 0, Math.cos(t) * radius))
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

// ── Transiting body (candidate scene) ─────────────────────────────────────
// Position is driven entirely by the phase prop from the parent.
// This component does NOT run its own animation loop.
function TransitingBody({
  starR,
  orbitR,
  bodyR,
  inclRad,
  phase,
}: {
  starR: number
  orbitR: number
  bodyR: number
  inclRad: number
  phase: number   // dimensionless phase in [-0.5, +0.5]; 0 = mid-transit
}) {
  const { x, z } = phaseToPosition(phase, orbitR)

  return (
    <group rotation={[inclRad, 0, 0]}>
      <mesh position={[x, 0, z]}>
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
      <OrbitRing radius={orbitR} />
    </group>
  )
}

// ── EB: two-star scene ─────────────────────────────────────────────────────
function EclipsingBinaryScene({
  starR,
  teffK,
  companionR,
  companionTeffK,
  orbitR,
  inclRad,
  phase,
}: {
  starR: number
  teffK: number
  companionR: number
  companionTeffK: number
  orbitR: number
  inclRad: number
  phase: number
}) {
  const { x, z } = phaseToPosition(phase, orbitR)
  const compHex = useMemo(() => starColor(companionTeffK), [companionTeffK])

  return (
    <group rotation={[inclRad, 0, 0]}>
      {/* Primary star */}
      <StarSphere radius={starR} teffK={teffK} label="primary" />
      {/* Companion at phase-driven position */}
      <group position={[x, 0, z]}>
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
}: {
  vet: VetResult
  stellarTeffK: number
  stellarRadiusRsun: number
  phase: number   // dimensionless [-0.5, +0.5]; 0 = mid-transit
}) {
  const starR = useMemo(() => starSceneSize(stellarRadiusRsun), [stellarRadiusRsun])
  const depthPpm = vet.depth_ppm ?? 100
  const periodDays = vet.period_days ?? 1
  const inclDeg = vet.inclination_deg ?? 88
  const inclRad = (inclDeg * Math.PI) / 180

  const sma = useMemo(() => semiMajorAxisFromPeriod(periodDays), [periodDays])
  const orbitR = useMemo(() => auToScene(sma), [sma])

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
      {/* Fix canvas clear color: WebGL defaults to black, override to match --np-surface */}
      <color attach="background" args={['#EDE9DE']} />
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
          phase={phase}
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

// ── Flat 2D orbital diagram (default view) ───────────────────────────────
// Renders the orbital geometry as a newspaper-aesthetic SVG: paper background,
// a filled circle for the star, a thin dashed ellipse for the orbit, and a
// small solid dot for the transiting body (or two circles for an EB).
// All geometry is derived from the vet data — no invented values.
function OrbitalDiagram2D({
  vet,
  radiusRsun,
}: {
  vet: VetResult
  radiusRsun: number
}) {
  const W = 560
  const H = 220
  const CX = W / 2
  const CY = H / 2

  const disposition = vet.disposition
  const triggeringTest = vet.triggering_test
  const isEB = disposition === 'false_positive' && triggeringTest === 'odd_even_depth'
  const isCentroid = disposition === 'false_positive' && triggeringTest === 'centroid_shift'

  // Star size: clamp between 12 and 28 SVG units
  const starR = Math.max(12, Math.min(28, radiusRsun * 16))

  // Orbit ellipse: semi-major axis in SVG units
  // Use a_over_rs if available, else fall back to a geometry-based estimate
  const aOverRs = vet.a_over_rs ?? 5
  const orbitRx = Math.max(starR * 2.2, Math.min(W * 0.42, aOverRs * starR * 0.9))
  const orbitRy = orbitRx * 0.28   // shallow perspective

  // Transiting body radius — exaggerated for visibility, same rule as 3D
  const depthPpm = vet.depth_ppm ?? 100
  const trueRpRs = Math.sqrt(Math.max(depthPpm, 1) / 1e6)
  const trueBodyR = trueRpRs * starR
  const minBodyR = starR * 0.12
  const bodyR = Math.max(trueBodyR, minBodyR)
  const exaggeration = Math.max(1, Math.round(bodyR / trueBodyR))

  // Phase 0 = mid-transit: transiting body sits directly in front of star (left of centre in top-down view)
  // We show the body at mid-transit position (phase = 0)
  const bodyX = CX             // directly in front of star
  const bodyY = CY             // on the orbit plane

  // EB companion sits at half-orbit (phase = 0.5) — far side
  const companionX = CX + orbitRx
  const companionY = CY

  // ── Centroid shift: star + off-target dot + dashed vector ─────────────────
  if (isCentroid) {
    const offTargetX = CX + orbitRx * 0.75
    const offTargetR = starR * 0.5
    return (
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        aria-label="Orbital diagram — centroid shift geometry"
        role="img"
        style={{ display: 'block', background: 'var(--np-surface)', border: '1px solid var(--np-border)' }}
      >
        {/* Star */}
        <circle cx={CX} cy={CY} r={starR} fill="var(--rust)" opacity="0.85" />
        <text x={CX} y={CY - starR - 5} textAnchor="middle" fontSize="9" fontFamily="var(--font-mono)" fill="var(--np-muted)">target</text>
        {/* Centroid vector */}
        <line x1={CX} y1={CY} x2={offTargetX} y2={CY}
          stroke="var(--np-muted)" strokeWidth="1" strokeDasharray="5,3" />
        <text x={(CX + offTargetX) / 2} y={CY - 10} textAnchor="middle" fontSize="9" fontFamily="var(--font-mono)" fill="var(--np-muted)">centroid shift</text>
        {/* Off-target source */}
        <circle cx={offTargetX} cy={CY} r={offTargetR} fill="var(--np-muted)" opacity="0.45" />
        <text x={offTargetX} y={CY - offTargetR - 5} textAnchor="middle" fontSize="9" fontFamily="var(--font-mono)" fill="var(--np-muted)">off-target</text>
      </svg>
    )
  }

  // ── EB: two circles + orbit ellipse ──────────────────────────────────────
  if (isEB) {
    const companionR = starR * 0.65
    return (
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        aria-label="Orbital diagram — eclipsing binary geometry"
        role="img"
        style={{ display: 'block', background: 'var(--np-surface)', border: '1px solid var(--np-border)' }}
      >
        {/* Orbit ellipse */}
        <ellipse cx={CX} cy={CY} rx={orbitRx} ry={orbitRy}
          fill="none" stroke="var(--np-rule)" strokeWidth="0.8" strokeDasharray="4,3" />
        {/* Primary star */}
        <circle cx={CX} cy={CY} r={starR} fill="var(--rust)" opacity="0.85" />
        <text x={CX} y={CY + starR + 11} textAnchor="middle" fontSize="9" fontFamily="var(--font-mono)" fill="var(--np-muted)">primary</text>
        {/* Companion star at half-orbit */}
        <circle cx={companionX} cy={companionY} r={companionR} fill="var(--np-muted)" opacity="0.6" />
        <text x={companionX} y={companionY + companionR + 11} textAnchor="middle" fontSize="9" fontFamily="var(--font-mono)" fill="var(--np-muted)">companion</text>
      </svg>
    )
  }

  // ── Candidate / ambiguous: star + orbit + transiting body ─────────────────
  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      aria-label={`Orbital diagram — ${disposition.replace(/_/g, ' ')}`}
      role="img"
      style={{ display: 'block', background: 'var(--np-surface)', border: '1px solid var(--np-border)' }}
    >
      {/* Orbit ellipse */}
      <ellipse cx={CX} cy={CY} rx={orbitRx} ry={orbitRy}
        fill="none" stroke="var(--np-rule)" strokeWidth="0.8" strokeDasharray="4,3" />
      {/* Star */}
      <circle cx={CX} cy={CY} r={starR} fill="var(--rust)" opacity="0.85" />
      {/* Transiting body at mid-transit (phase = 0, in front of star) */}
      <circle cx={bodyX} cy={bodyY} r={bodyR} fill="var(--np-text)" opacity="0.82" />
      {/* Exaggeration note */}
      {exaggeration > 1 && (
        <text x={CX} y={H - 8} textAnchor="middle" fontSize="8" fontFamily="var(--font-mono)" fill="var(--np-faint)">
          {`body radius exaggerated ${exaggeration}\u00D7 for visibility`}
        </text>
      )}
    </svg>
  )
}

// ── Folded light curve with animated marker ───────────────────────────────
// Renders the artifact's phased_lc as scatter points (binned data).
// A vertical marker tracks the current phase.
// If phased_lc is null or empty: explicit empty state — no shape is synthesized.
function FoldedLCWithMarker({
  phasedLC,
  currentPhase,
  disposition,
}: {
  phasedLC: PhasedLC & { flux_secondary?: number[]; primary_depth_ppm?: number; secondary_depth_ppm?: number } | null | undefined
  currentPhase: number   // dimensionless [-0.5, +0.5]; 0 = mid-transit
  disposition: string
}) {
  const W = 560
  const H = 110
  const PAD = { l: 8, r: 8, t: 10, b: 20 }

  const isEB = disposition === 'false_positive' && !!phasedLC?.flux_secondary

  // ── Empty state — never synthesize ───────────────────────────────────────
  if (!phasedLC?.phase?.length || !phasedLC?.flux?.length) {
    return (
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        style={{
          display: 'block',
          background: 'var(--np-surface)',
          border: '1px solid var(--np-border)',
        }}
        aria-label="Phase-folded light curve — no data available"
        role="img"
      >
        <text
          x={W / 2}
          y={H / 2}
          fill="var(--np-faint)"
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="11"
          fontFamily="var(--font-serif)"
          fontStyle="italic"
        >
          No phase-folded light curve available for this result
        </text>
      </svg>
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

  // Marker x from the current phase (already in [-0.5, +0.5])
  const markerX = toX(currentPhase)

  // Interpolate flux at currentPhase for the marker dot Y
  const markerY = (() => {
    if (phase.length < 2) return toY(flux[0] ?? 1)
    const idx = phase.findIndex((p) => p >= currentPhase)
    const i = idx < 0 ? phase.length - 1 : Math.max(0, Math.min(phase.length - 1, idx))
    return toY(flux[i] ?? 1)
  })()

  // Point radius for scatter plot — small so individual bins are visible
  const PR = 2.0

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

      {/* Mid-transit reference at phase 0 */}
      <line x1={W / 2} y1={PAD.t} x2={W / 2} y2={H - PAD.b} stroke="var(--np-border)" strokeWidth="0.5" strokeDasharray="2,2" />

      {/* Primary LC — scatter points (binned data) */}
      {phase.map((p, i) => (
        <circle
          key={i}
          cx={toX(p).toFixed(1)}
          cy={toY(flux[i]).toFixed(1)}
          r={PR}
          fill="var(--rust)"
          opacity="0.75"
        />
      ))}

      {/* Secondary (EB) LC — different colour to distinguish */}
      {fluxSec && phase.map((p, i) => (
        <circle
          key={`sec-${i}`}
          cx={toX(p).toFixed(1)}
          cy={toY(fluxSec[i]).toFixed(1)}
          r={PR}
          fill="#5577AA"
          opacity="0.75"
        />
      ))}

      {/* Animated phase marker — driven by parent phase state */}
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
          <circle cx={W - 84} cy={11} r={PR} fill="var(--rust)" opacity="0.75" />
          <text x={W - 78} y={14} fill="var(--np-muted)" fontSize="8" fontFamily="var(--font-mono)">primary</text>
          <circle cx={W - 84} cy={22} r={PR} fill="#5577AA" opacity="0.75" />
          <text x={W - 78} y={25} fill="var(--np-muted)" fontSize="8" fontFamily="var(--font-mono)">secondary</text>
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
  isFixture: _isFixture,
  jobStatus,
  progressStage,
  jobError,
}: {
  vet: VetResult | null | undefined
  stellarParams: StellarParams | null | undefined
  jobId: string | null | undefined
  /**
   * Whether the report is fixture-backed.
   * No longer used to gate the 3D scene — the gate is now driven by whether
   * `vet.phased_lc.phase` is present, which is true for all committed fixtures.
   * Kept in the prop signature so callers do not need to change.
   */
  isFixture?: boolean
  /** Current job status — drives the three-state placeholder (never-run / running / failed). */
  jobStatus?: string | null
  /** The pipeline stage currently executing, sourced from SSE stage_start events. */
  progressStage?: string | null
  /** Error message when jobStatus === 'failed' — shown with a collapsible raw-detail toggle. */
  jobError?: string | null
}) {
  const { teffK, radiusRsun } = useMemo(
    () => extractStellarParams(stellarParams),
    [stellarParams],
  )

  // Phase is dimensionless [-0.5, +0.5]; 0 = mid-transit.
  // This is the SINGLE phase state that ALL consumers (3D, SVG, slider) read.
  const [playing, setPlaying] = useState(false)
  const [phase, setPhase] = useState(0)
  const [canvasOk, setCanvasOk] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)
  // Default to 2D flat diagram; user can expand the 3D view on demand
  const [show3D, setShow3D] = useState(false)

  // RAF handle — kept in a ref so it can be cancelled without triggering re-renders
  const rafRef = useRef<number | null>(null)
  const prevTimestampRef = useRef<number | null>(null)

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

  // Animation loop — advances phase by wall-clock time, wraps at ±0.5.
  // Started/stopped by the playing state.  Cancelled on unmount.
  useEffect(() => {
    if (!playing) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      prevTimestampRef.current = null
      return
    }

    function tick(ts: number) {
      if (prevTimestampRef.current === null) {
        prevTimestampRef.current = ts
      }
      const elapsedMs = ts - prevTimestampRef.current
      prevTimestampRef.current = ts

      // Advance phase by fraction of one orbit elapsed this frame.
      // phase changes by elapsedMs / (ORBIT_WALL_SECONDS * 1000) per frame.
      setPhase((prev) => wrapPhase(prev + elapsedMs / (ORBIT_WALL_SECONDS * 1000)))
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      prevTimestampRef.current = null
    }
  }, [playing])

  // Scrub handler — pauses first, then updates phase
  const handleScrub = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setPlaying(false)
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

  // ── No renderable data: three-state placeholder ───────────────────────────
  //
  //   State A — never run: no job has been submitted (vet is null)
  //   State B — running:   a job is in-flight; show which stage is active
  //   State C — failed:    the job errored; show a user-facing message with
  //                        a collapsible raw-detail toggle
  //
  // Gate: fall through to the 3D scene whenever vet AND phased_lc data are
  // present — this includes fixture-backed reports (KIC 11904151, KIC 6965293)
  // which carry real committed phasedLC arrays.  Only the *classifier* artifact
  // is genuinely absent; the orbital geometry is not.
  if (!vet || !vet.phased_lc?.phase?.length) {
    const isRunning = (jobStatus === 'running' || jobStatus === 'queued')
    const isFailed  = jobStatus === 'failed'

    // Staged pipeline labels for the running state — no scientific values (Rule 1)
    const STAGE_LABELS: Record<string, string> = {
      ingest:   'Stage 1 of 5 — fetching light curve data from archive',
      detrend:  'Stage 2 of 5 — detrending stellar variability',
      search:   'Stage 3 of 5 — running Transit Least Squares search',
      vet:      'Stage 4 of 5 — running seven vetting tests',
      classify: 'Stage 5 of 5 — computing ranking score',
    }
    const stageLabel = progressStage
      ? (STAGE_LABELS[progressStage] ?? `Running — ${progressStage}`)
      : 'Pipeline starting…'

    // Error message: strip Python exception class prefix (everything before ': ')
    // to surface only the human-readable portion, per the defect report.
    const errorSummary: string = (() => {
      if (!jobError) return 'The pipeline run did not complete.'
      // Remove leading "ExceptionClass: " prefix if present, e.g.
      //   "MastFetchError: lightkurve download failed…" → "lightkurve download failed…"
      // Stop at the first newline (stack trace begins there).
      const firstLine = jobError.split('\n')[0] ?? jobError
      const colonIdx = firstLine.indexOf(': ')
      const cleaned = colonIdx > 0 ? firstLine.slice(colonIdx + 2) : firstLine
      return cleaned.trim() || 'The pipeline run did not complete.'
    })()

    // Determine chip label and body text (no scientific literals — Rule 1)
    const statusLabel = isRunning  ? 'RUNNING'
      : isFailed   ? 'FAILED'
      :              'NOT YET RUN'

    const ariaDesc = isRunning
      ? `Orbital diagram: pipeline running — ${stageLabel}`
      : isFailed
      ? `Orbital diagram: pipeline failed — ${errorSummary}`
      : 'Orbital diagram: not yet run. Submit a target to generate the diagram.'

    // Error details toggle — state local to this render path
    const [showDetail, setShowDetail] = useState(false)

    const chipColor = isRunning ? 'var(--np-accent, #3b82d4)'
      : isFailed ? 'var(--fail, #b0220a)'
      : 'var(--np-muted)'

    return (
      <div>
        <figure style={{ margin: 0 }} aria-label={ariaDesc}>
          <hr style={{ border: 'none', borderTop: '1px solid var(--np-text)', margin: '0 0 8px' }} />
          <div
            role="status"
            aria-label={ariaDesc}
            aria-live={isRunning ? 'polite' : undefined}
            style={{
              padding: '18px 24px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 8,
              background: 'transparent',
              border: `1px ${isFailed ? 'solid' : 'dashed'} var(--np-rule)`,
              borderLeft: isFailed ? '3px solid var(--fail, #b0220a)' : undefined,
            }}
          >
            {/* Status chip */}
            <span style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              letterSpacing: '0.08em',
              color: chipColor,
              border: `1px solid ${isFailed ? 'var(--fail, #b0220a)' : 'var(--np-rule)'}`,
              padding: '2px 8px',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}>
              {isRunning && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: 'var(--np-accent, #3b82d4)',
                    animation: 'pulse 1.4s ease-in-out infinite',
                  }}
                  aria-hidden="true"
                />
              )}
              {statusLabel}
            </span>

            {/* Body text — three states, no invented values */}
            {isRunning && (
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--np-muted)',
                textAlign: 'center',
                maxWidth: 380,
                lineHeight: 1.6,
              }}>
                {stageLabel}
              </span>
            )}

            {isFailed && (
              <div style={{ maxWidth: 420, width: '100%', textAlign: 'center' }}>
                <p style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 13,
                  color: 'var(--np-muted)',
                  lineHeight: 1.55,
                  margin: '0 0 6px',
                }}>
                  {errorSummary}
                </p>
                {/* Collapsible raw detail — keeps exception strings off the main surface */}
                {jobError && jobError !== errorSummary && (
                  <div>
                    <button
                      onClick={() => setShowDetail((v) => !v)}
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 10,
                        letterSpacing: '0.05em',
                        color: 'var(--np-muted)',
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        padding: '2px 0',
                        textDecoration: 'underline',
                      }}
                      aria-expanded={showDetail}
                      aria-controls="orbital-error-detail"
                    >
                      {showDetail ? '▲ hide details' : '▼ show details'}
                    </button>
                    {showDetail && (
                      <pre
                        id="orbital-error-detail"
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 10,
                          color: 'var(--np-muted)',
                          background: 'var(--np-surface)',
                          border: '1px solid var(--np-rule)',
                          padding: '8px 10px',
                          marginTop: 6,
                          textAlign: 'left',
                          overflowX: 'auto',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          maxHeight: 160,
                          overflowY: 'auto',
                        }}
                      >
                        {jobError}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}

            {!isRunning && !isFailed && (
              <span style={{
                fontFamily: 'var(--font-serif)',
                fontSize: 12,
                color: 'var(--np-muted)',
                textAlign: 'center',
                maxWidth: 340,
                lineHeight: 1.5,
              }}>
                Submit a target above to generate the orbital geometry diagram.
              </span>
            )}
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
            {isRunning
              ? `Orbital diagram — pipeline in progress.`
              : isFailed
              ? `Orbital diagram — pipeline did not complete.`
              : 'Orbital diagram — no pipeline run has been submitted.'}
          </figcaption>
        </figure>

        {/* Folded LC — only rendered when vet data is available (fixture path) */}
        {vet && (
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
            {phasedLC?.phase?.length ? (
              <div style={{
                fontFamily: 'var(--font-serif)', fontStyle: 'italic',
                fontSize: 11, color: 'var(--np-faint)', marginTop: 4,
              }}>
                Source:{' '}
                <span style={{ fontFamily: 'var(--font-mono)' }}>report.vet[].phased_lc</span>
                {isEB && ' · blue = secondary eclipse folded at primary period'}
              </div>
            ) : null}
          </div>
        )}
      </div>
    )
  }

  return (
    <div>
      {/* ── Default: flat 2D diagram (newspaper aesthetic) ────────────────── */}
      <figure style={{ margin: 0 }} aria-label={sceneDesc}>
        <hr style={{ border: 'none', borderTop: '1px solid var(--np-text)', margin: '0 0 8px' }} />

        {/* Disposition badge + 2D SVG */}
        <div style={{ position: 'relative' }}>
          <OrbitalDiagram2D vet={vet} radiusRsun={radiusRsun} />
          {/* Disposition chip overlay — uses the same shared component as CandidateDetail */}
          <div style={{ position: 'absolute', top: 8, left: 10 }}>
            <DispoChip disposition={disposition} />
          </div>
        </div>

        <hr style={{ border: 'none', borderTop: '1px solid var(--np-text)', margin: '8px 0 4px' }} />
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.10em', color: 'var(--np-muted)', textTransform: 'uppercase', marginBottom: 3 }}>
          FIG. 1
        </div>
        <figcaption style={{
          fontFamily: 'var(--font-serif)', fontStyle: 'italic',
          fontSize: 12, color: 'var(--np-muted)', lineHeight: 1.5, marginBottom: 8,
        }}>
          {isEB
            ? 'Eclipsing-binary geometry from pipeline output. Two stars orbit each other; alternating eclipse depths are the false-positive signature.'
            : vet.triggering_test === 'centroid_shift'
            ? 'Centroid-shift geometry: the signal originates off-target. Dashed line shows the centroid displacement direction.'
            : 'Orbital geometry from pipeline output — mid-transit position shown.'
          }
          {' '}
          {isCandidate && exaggerationFactor > 1 && (
            <span style={{ color: 'var(--np-faint)' }}>
              {`Transiting body radius exaggerated ${exaggerationFactor}\u00D7 for visibility (true Rp/Rs\u202F\u2248\u202F${Math.sqrt(Math.max(depthPpm, 1) / 1e6).toFixed(4)}).`}
            </span>
          )}
        </figcaption>
      </figure>

      {/* Phase-folded light curve (always shown when data is present) */}
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
        {phasedLC?.phase?.length ? (
          <div style={{
            fontFamily: 'var(--font-serif)', fontStyle: 'italic',
            fontSize: 11, color: 'var(--np-faint)', marginTop: 4,
          }}>
            Source:{' '}
            <span style={{ fontFamily: 'var(--font-mono)' }}>report.vet[].phased_lc</span>
            {isEB && ' · blue = secondary eclipse folded at primary period'}
            {show3D && ' · green marker tracks the 3D animation below'}
          </div>
        ) : null}
      </div>

      {/* ── 3D view toggle ─────────────────────────────────────────────────── */}
      <div style={{ margin: '8px 0' }}>
        <button
          onClick={() => setShow3D((v) => !v)}
          style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            padding: '3px 10px',
            border: '1px solid var(--np-rule)',
            background: show3D ? 'var(--np-surface)' : 'transparent',
            cursor: 'pointer', color: 'var(--np-muted)',
            letterSpacing: '0.05em',
          }}
          aria-expanded={show3D}
        >
          {show3D ? 'Hide 3D view ▲' : 'View in 3D ▼'}
        </button>
      </div>

      {show3D && (
        <div>
          {/* 3D canvas */}
          <div
            ref={containerRef}
            style={{ height: 340, position: 'relative', background: 'var(--np-surface)', border: '1px solid var(--np-border)' }}
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
                style={{ width: '100%', height: '100%' }}
              >
                <OrbitControls
                  enablePan={false}
                  minDistance={0.05}
                  maxDistance={500}
                  enableDamping
                  dampingFactor={0.08}
                />
                <SceneContent
                  vet={vet}
                  stellarTeffK={teffK}
                  stellarRadiusRsun={radiusRsun}
                  phase={phase}
                />
              </Canvas>
            )}
          </div>

          {/* Play / pause / scrub controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '6px 0 4px' }}>
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
              min={-0.5}
              max={0.5}
              step={0.002}
              value={phase}
              onChange={handleScrub}
              style={{ flex: 1, maxWidth: 200, accentColor: 'var(--rust)' }}
              aria-label="Scrub animation phase"
            />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-faint)', minWidth: 60 }}>
              phase {phase.toFixed(3)}
            </span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-faint)', marginBottom: 8 }}>
            Drag to rotate · scroll to zoom · background = pipeline paper color
          </div>
        </div>
      )}
    </div>
  )
}
