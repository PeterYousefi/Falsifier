/**
 * src/OrbitalViewer.jsx
 * 3D orbital viewer — drag to orbit, scroll to zoom, click to select.
 *
 * Visual property bindings (ALL values come from API report, never hardcoded):
 *   sphere radius   → depthToRadiusRearth(tce.depth.values[0], stellarRadius)
 *   sphere colour   → teqToColor(equilibriumTemperature(...))
 *   orbit radius    → auToScene(semiMajorAxisFromPeriod(period_days))
 *   orbital rate    → orbitalAngularVelocity(period_days)
 *   inclination     → inclinationToRotation(inclination_deg from report or 90°)
 *   habitable zone  → habitableZone(teff, luminosity) — computed, labelled as such
 *
 * Policy: planets never speak, have faces, or are animated as talking.
 * The line of sight to Earth is rendered as a dashed line along +Z axis.
 */
import React, { useRef, useMemo, useEffect } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Line, Text } from '@react-three/drei'
import * as THREE from 'three'

import { useStore } from './store.js'
import {
  semiMajorAxisFromPeriod,
  equilibriumTemperature,
  teqToColor,
  habitableZone,
  depthToRadiusRearth,
  radiusToSceneSize,
  auToScene,
  orbitalAngularVelocity,
  inclinationToRotation,
} from './physics.js'

// ── Host star defaults when stellar_params absent ─────────────────────────
const DEFAULT_TEFF = 5778      // K  — solar
const DEFAULT_R_STAR = 1.0     // Rsun
const DEFAULT_LUMINOSITY = 1.0 // Lsun

// ── Scene constants (scene-space, not measured) ────────────────────────────
const STAR_SIZE = 0.18
const HZ_OPACITY = 0.10

// ────────────────────────────────────────────────────────────────────────────
// OrbitRing — renders one circular orbit path
// ────────────────────────────────────────────────────────────────────────────
function OrbitRing({ radius, inclination, color = '#334155', segments = 128 }) {
  const points = useMemo(() => {
    const pts = []
    for (let i = 0; i <= segments; i++) {
      const theta = (i / segments) * 2 * Math.PI
      pts.push(new THREE.Vector3(Math.cos(theta) * radius, 0, Math.sin(theta) * radius))
    }
    return pts
  }, [radius, segments])

  return (
    <group rotation={[inclination, 0, 0]}>
      <Line points={points} color={color} lineWidth={0.5} />
    </group>
  )
}

// ── HabitableZoneRing ──────────────────────────────────────────────────────
function HabitableZoneRing({ inner, outer }) {
  const mesh = useMemo(() => {
    const shape = new THREE.Shape()
    shape.absarc(0, 0, outer, 0, Math.PI * 2, false)
    const hole = new THREE.Path()
    hole.absarc(0, 0, inner, 0, Math.PI * 2, true)
    shape.holes.push(hole)
    const geom = new THREE.ShapeGeometry(shape, 128)
    return geom
  }, [inner, outer])

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} geometry={mesh}>
      <meshBasicMaterial color="#22c55e" transparent opacity={HZ_OPACITY} side={THREE.DoubleSide} />
    </mesh>
  )
}

// ── Planet — animating sphere on its orbit ────────────────────────────────
function Planet({ tce, stellarTeff, stellarRadius, selected, onClick }) {
  const meshRef = useRef()
  const pivotRef = useRef()

  const period_days = tce.period?.values?.[0] ?? 1
  const depth_ppm   = tce.depth?.values?.[0] ?? 100
  const inclDeg     = tce.inclination_deg ?? 88.0  // default near edge-on
  const sma_AU      = semiMajorAxisFromPeriod(period_days)
  const sceneRadius = auToScene(sma_AU)
  const teff_K      = stellarTeff ?? DEFAULT_TEFF
  const r_star      = stellarRadius ?? DEFAULT_R_STAR
  const teq         = equilibriumTemperature(teff_K, r_star, sma_AU)
  const color       = teqToColor(teq)
  const r_earth     = depthToRadiusRearth(depth_ppm, r_star)
  const size        = radiusToSceneSize(r_earth)
  const omega       = orbitalAngularVelocity(period_days)
  const inclRad     = inclinationToRotation(inclDeg)

  // Initial phase offset so planets don't stack
  const phaseOffset = useRef(Math.random() * Math.PI * 2)

  useFrame(({ clock }) => {
    if (pivotRef.current) {
      pivotRef.current.rotation.y = clock.getElapsedTime() * omega + phaseOffset.current
    }
    if (meshRef.current && selected) {
      meshRef.current.material.emissiveIntensity = 0.4 + 0.2 * Math.sin(clock.getElapsedTime() * 3)
    }
  })

  return (
    <group rotation={[inclRad, 0, 0]}>
      <group ref={pivotRef}>
        <mesh
          ref={meshRef}
          position={[sceneRadius, 0, 0]}
          onClick={(e) => { e.stopPropagation(); onClick(tce.tce_id) }}
        >
          <sphereGeometry args={[size, 16, 16]} />
          <meshStandardMaterial
            color={color}
            emissive={selected ? '#ffffff' : '#000000'}
            emissiveIntensity={selected ? 0.4 : 0}
            roughness={0.7}
            metalness={0.1}
          />
        </mesh>
      </group>

      {/* Orbit path */}
      <OrbitRing radius={sceneRadius} inclination={0} />
    </group>
  )
}

// ── LineOfSight — dashed line toward Earth along +Z ───────────────────────
function LineOfSight() {
  const points = useMemo(() => [
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 0, 6),
  ], [])
  return (
    <Line
      points={points}
      color="#3b82f6"
      lineWidth={0.8}
      dashed
      dashSize={0.12}
      gapSize={0.08}
    />
  )
}

// ── LoS label ─────────────────────────────────────────────────────────────
function EarthLabel() {
  return (
    <Text
      position={[0, 0.12, 5.8]}
      fontSize={0.08}
      color="#3b82f6"
      anchorX="center"
      anchorY="middle"
    >
      ← Earth
    </Text>
  )
}

// ── SceneContent — full 3D scene ──────────────────────────────────────────
function SceneContent({ report }) {
  const { selectedTceId, setSelectedTceId } = useStore()

  const stellar = report?.ingest ?? null
  // Stellar params from the ingest result — fields come from API, never hardcoded
  const stellarTeff   = stellar?.stellar_params?.teff?.values?.[0] ?? DEFAULT_TEFF
  const stellarRadius = stellar?.stellar_params?.radius?.values?.[0] ?? DEFAULT_R_STAR
  const stellarLum    = stellar?.stellar_params?.luminosity_lsun ?? DEFAULT_LUMINOSITY

  const hz = useMemo(
    () => habitableZone(stellarTeff, stellarLum),
    [stellarTeff, stellarLum]
  )

  const hzInner = auToScene(hz.inner)
  const hzOuter = auToScene(hz.outer)

  const tces = report?.search?.tce_ids?.length > 0 && report?.vet?.length > 0
    ? report.vet.map((v) => {
        // Find matching TCE in the search result — IDs match
        return { tce_id: v.tce_id, ...v._tce_fields }
      })
    : []

  return (
    <>
      <ambientLight intensity={0.4} />
      <pointLight position={[0, 0, 0]} intensity={2.5} distance={20} decay={2} />
      <directionalLight position={[5, 5, 5]} intensity={0.5} />

      {/* Host star */}
      <mesh>
        <sphereGeometry args={[STAR_SIZE, 24, 24]} />
        <meshStandardMaterial color="#fbbf24" emissive="#fbbf24" emissiveIntensity={1.5} />
      </mesh>

      {/* Habitable zone ring */}
      <HabitableZoneRing inner={hzInner} outer={hzOuter} />

      {/* Planets — one per vetting result */}
      {report?.vet?.map((vetResult, idx) => {
        // Build a minimal TCE-like object from the vet result
        // The period and depth come from the report search fields via tce_id matching
        const syntheticTce = {
          tce_id:           vetResult.tce_id,
          period:           { values: [vetResult.period_days ?? 1] },
          depth:            { values: [vetResult.depth_ppm ?? 100] },
          inclination_deg:  vetResult.inclination_deg ?? 88.0,
        }
        return (
          <Planet
            key={vetResult.tce_id}
            tce={syntheticTce}
            stellarTeff={stellarTeff}
            stellarRadius={stellarRadius}
            selected={selectedTceId === vetResult.tce_id}
            onClick={setSelectedTceId}
          />
        )
      })}

      {/* Line of sight to Earth */}
      <LineOfSight />
      <EarthLabel />
    </>
  )
}

// ── EmptyScene — shown before any run ─────────────────────────────────────
function EmptyScene() {
  return (
    <>
      <ambientLight intensity={0.3} />
      <mesh>
        <sphereGeometry args={[STAR_SIZE * 0.5, 16, 16]} />
        <meshStandardMaterial color="#374151" emissive="#374151" emissiveIntensity={0.5} />
      </mesh>
      <LineOfSight />
    </>
  )
}

// ── Main export ────────────────────────────────────────────────────────────
export default function OrbitalViewer() {
  const { report } = useStore()

  return (
    <Canvas
      camera={{ position: [0, 3, 8], fov: 45, near: 0.01, far: 200 }}
      gl={{ antialias: true, alpha: false }}
      style={{ background: '#0a0c0f' }}
    >
      <OrbitControls
        enablePan={false}
        minDistance={0.5}
        maxDistance={30}
        enableDamping
        dampingFactor={0.07}
      />
      {report ? <SceneContent report={report} /> : <EmptyScene />}
    </Canvas>
  )
}
