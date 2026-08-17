/**
 * src/screens/SystemScreen.tsx
 * System browse: Three.js orbital view + non-3D fallback list.
 * All visual properties driven by measured values from the data layer.
 */
import React, { useRef, useMemo, useState, useEffect } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Line, Text } from '@react-three/drei'
import * as THREE from 'three'
import { useStore } from '../store'
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
} from '../physics'
import type { VetResult } from '../data/types'
import { VETTING_TEST_ORDER, TEST_LABELS, VetBadge, DispoChip, Row, PhaseLCPlot } from './CandidateDetail'

// ── Host-star visual defaults when stellar_params absent ──────────────────
const DEFAULT_TEFF     = 5778
const DEFAULT_R_STAR   = 1.0
const DEFAULT_LUM      = 1.0
const STAR_SCENE_SIZE  = 0.18
const HZ_OPACITY       = 0.09

// ── Orbit ring ────────────────────────────────────────────────────────────
function OrbitRing({ radius }: { radius: number }) {
  const pts = useMemo(() => {
    const a: THREE.Vector3[] = []
    for (let i = 0; i <= 128; i++) {
      const t = (i / 128) * 2 * Math.PI
      a.push(new THREE.Vector3(Math.cos(t) * radius, 0, Math.sin(t) * radius))
    }
    return a
  }, [radius])
  return <Line points={pts} color="#334155" lineWidth={0.4} />
}

// ── Habitable zone ring ───────────────────────────────────────────────────
function HZRing({ inner, outer }: { inner: number; outer: number }) {
  const geom = useMemo(() => {
    const shape = new THREE.Shape()
    shape.absarc(0, 0, outer, 0, Math.PI * 2, false)
    const hole = new THREE.Path()
    hole.absarc(0, 0, inner, 0, Math.PI * 2, true)
    shape.holes.push(hole)
    return new THREE.ShapeGeometry(shape, 128)
  }, [inner, outer])
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} geometry={geom}>
      <meshBasicMaterial color="#22c55e" transparent opacity={HZ_OPACITY} side={THREE.DoubleSide} />
    </mesh>
  )
}

// ── Planet sphere ─────────────────────────────────────────────────────────
function Planet({
  vet,
  stellarTeff,
  stellarRadius,
  selected,
  onClick,
}: {
  vet: VetResult
  stellarTeff: number
  stellarRadius: number
  selected: boolean
  onClick: (id: string) => void
}) {
  const pivotRef = useRef<THREE.Group>(null!)
  const meshRef  = useRef<THREE.Mesh>(null!)

  const period  = vet.period_days  ?? 1
  const depth   = vet.depth_ppm    ?? 100
  const inclDeg = vet.inclination_deg ?? 88
  const sma     = semiMajorAxisFromPeriod(period)
  const sr      = auToScene(sma)
  const teq     = equilibriumTemperature(stellarTeff, stellarRadius, sma)
  const color   = teqToColor(teq)
  const rearth  = depthToRadiusRearth(depth, stellarRadius)
  const size    = radiusToSceneSize(rearth)
  const omega   = orbitalAngularVelocity(period)
  const inclRad = inclinationToRotation(inclDeg)
  const phase   = useMemo(() => Math.random() * Math.PI * 2, [vet.tce_id])

  useFrame(({ clock }) => {
    if (pivotRef.current)
      pivotRef.current.rotation.y = clock.getElapsedTime() * omega + phase
    if (meshRef.current && selected) {
      const mat = meshRef.current.material as THREE.MeshStandardMaterial
      mat.emissiveIntensity = 0.35 + 0.18 * Math.sin(clock.getElapsedTime() * 3)
    }
  })

  return (
    <group rotation={[inclRad, 0, 0]}>
      <group ref={pivotRef}>
        <mesh
          ref={meshRef}
          position={[sr, 0, 0]}
          onClick={(e) => { e.stopPropagation(); onClick(vet.tce_id) }}
        >
          <sphereGeometry args={[size, 16, 16]} />
          <meshStandardMaterial
            color={color}
            emissive={selected ? '#ffffff' : '#000000'}
            emissiveIntensity={selected ? 0.35 : 0}
            roughness={0.7}
            metalness={0.1}
          />
        </mesh>
      </group>
      <OrbitRing radius={sr} />
    </group>
  )
}

// ── Line of sight toward Earth ────────────────────────────────────────────
function LineOfSight() {
  const pts = useMemo(() => [
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 0, 6),
  ], [])
  return (
    <>
      <Line points={pts} color="#3b82f6" lineWidth={0.8} dashed dashSize={0.12} gapSize={0.08} />
      <Text position={[0, 0.12, 5.8]} fontSize={0.07} color="#3b82f6" anchorX="center" anchorY="middle">
        {'← Earth'}
      </Text>
    </>
  )
}

// ── Full 3D scene ─────────────────────────────────────────────────────────
function SceneContent({ vets, stellarTeff, stellarRadius, lumLsun }: {
  vets: VetResult[]
  stellarTeff: number
  stellarRadius: number
  lumLsun: number
}) {
  const { selectedTceId, setSelectedTceId } = useStore()
  const hz = useMemo(() => habitableZone(stellarTeff, lumLsun), [stellarTeff, lumLsun])
  const hzIn  = auToScene(hz.inner)
  const hzOut = auToScene(hz.outer)

  return (
    <>
      <ambientLight intensity={0.4} />
      <pointLight position={[0, 0, 0]} intensity={2.5} distance={20} decay={2} />
      <directionalLight position={[5, 5, 5]} intensity={0.5} />
      <mesh>
        <sphereGeometry args={[STAR_SCENE_SIZE, 24, 24]} />
        <meshStandardMaterial color="#fbbf24" emissive="#fbbf24" emissiveIntensity={1.5} />
      </mesh>
      <Text position={[0, STAR_SCENE_SIZE + 0.07, 0]} fontSize={0.06} color="#9ca3af" anchorX="center">
        {'host star'}
      </Text>
      <HZRing inner={hzIn} outer={hzOut} />
      <Text position={[hzIn + (hzOut - hzIn) / 2, 0.06, 0]} fontSize={0.055} color="#22c55e" anchorX="center">
        {'HZ (computed)'}
      </Text>
      {vets.map((v) => (
        <Planet
          key={v.tce_id}
          vet={v}
          stellarTeff={stellarTeff}
          stellarRadius={stellarRadius}
          selected={selectedTceId === v.tce_id}
          onClick={setSelectedTceId}
        />
      ))}
      <LineOfSight />
    </>
  )
}

// ── Non-3D fallback list ──────────────────────────────────────────────────
function FallbackList({ vets, stellarTeff, stellarRadius }: {
  vets: VetResult[]
  stellarTeff: number
  stellarRadius: number
}) {
  const { selectedTceId, setSelectedTceId } = useStore()
  if (!vets.length) {
    return (
      <div className="orbital-fallback">
        <div className="no-data">No TCEs — submit a target to begin.</div>
      </div>
    )
  }
  return (
    <div className="orbital-fallback" role="list" aria-label="TCE list (non-3D fallback)">
      <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--muted)' }}>
        Non-3D list · colour = T<sub>eq</sub> · orbit radius = semi-major axis
      </div>
      {vets.map((v) => {
        const period = v.period_days ?? 1
        const depth  = v.depth_ppm  ?? 100
        const sma    = semiMajorAxisFromPeriod(period)
        const teq    = equilibriumTemperature(stellarTeff, stellarRadius, sma)
        const color  = teqToColor(teq)
        const rearth = depthToRadiusRearth(depth, stellarRadius)
        const active = selectedTceId === v.tce_id
        return (
          <button
            key={v.tce_id}
            className="orbital-fallback-row"
            style={{
              width: '100%', textAlign: 'left',
              background: active ? 'var(--highlight)' : 'transparent',
              border: active ? '1px solid var(--accent)' : '1px solid transparent',
              borderRadius: 'var(--r)', cursor: 'pointer',
            }}
            onClick={() => setSelectedTceId(v.tce_id)}
            aria-pressed={active}
          >
            <span className="fallback-swatch" style={{ background: color }} aria-hidden />
            <span className="fallback-tce-id">{v.tce_id}</span>
            <span className="fallback-fields">
              <span className="fallback-field">
                <span className="f-label">period</span>
                <span className="f-value">{period.toFixed(4)} d</span>
              </span>
              <span className="fallback-field">
                <span className="f-label">depth</span>
                <span className="f-value">{depth.toFixed(0)} ppm</span>
              </span>
              <span className="fallback-field">
                <span className="f-label">R_p (approx)</span>
                <span className="f-value">{rearth.toFixed(1)} R⊕</span>
              </span>
              <span className="fallback-field">
                <span className="f-label">T_eq (visual)</span>
                <span className="f-value">{teq.toFixed(0)} K</span>
              </span>
              <span className="fallback-field">
                <span className="f-label">disposition</span>
                <span className="f-value">{v.disposition}</span>
              </span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ── TargetForm ────────────────────────────────────────────────────────────
function TargetForm() {
  const { targetId, setTargetId, isSubmitting, jobStatus, submitJob } = useStore()
  const [mission, setMission] = useState('Kepler')
  const [cadence, setCadence] = useState('long')
  const busy = isSubmitting || jobStatus === 'running' || jobStatus === 'queued'

  return (
    <form
      className="search-bar"
      onSubmit={(e) => {
        e.preventDefault()
        if (targetId.trim()) submitJob(targetId.trim(), mission, cadence)
      }}
    >
      <input
        value={targetId}
        onChange={(e) => setTargetId(e.target.value)}
        placeholder="KIC 11904151 / TIC 261136679"
        disabled={busy}
        aria-label="Target identifier"
      />
      <select value={mission} onChange={(e) => setMission(e.target.value)} disabled={busy} aria-label="Mission">
        <option>Kepler</option>
        <option>K2</option>
        <option>TESS</option>
      </select>
      <select value={cadence} onChange={(e) => setCadence(e.target.value)} disabled={busy} aria-label="Cadence">
        <option value="long">long</option>
        <option value="short">short</option>
      </select>
      <button type="submit" disabled={busy || !targetId.trim()}>
        {busy ? <span className="spinner" aria-label="Running" /> : 'Run'}
      </button>
    </form>
  )
}

// ── Inline detail panel (right column of system view) ─────────────────────
function DetailPanel() {
  const { report, selectedTceId, highlightedPanel } = useStore()

  const vetResult = useMemo(() => {
    if (!report?.vet?.length) return null
    if (selectedTceId) return report.vet.find((v) => v.tce_id === selectedTceId) ?? report.vet[0]
    return report.vet[0]
  }, [report, selectedTceId])

  const classifyResult = useMemo(() => {
    if (!report?.classify?.length || !vetResult) return null
    return report.classify.find((c) => c.tce_id === vetResult.tce_id) ?? null
  }, [report, vetResult])

  if (!report) {
    return (
      <div className="panel panel--detail">
        <div className="panel-header">Detail <span className="tag">no target</span></div>
        <div className="no-data">
          Run a detection job to<br />see TCE detail and vetting rows.
        </div>
      </div>
    )
  }

  const hl = (s: string) => highlightedPanel === s

  return (
    <div className="panel panel--detail">
      <div className="panel-header">
        Detail <span className="tag">{report.target_id}</span>
        {report.ingest?.host_star_id && (
          <span className="tag" style={{ color: 'var(--accent)' }}>{report.ingest.host_star_id}</span>
        )}
      </div>

      <div className={`detail-section${hl('ingest') ? ' highlighted' : ''}`}>
        <h3>Target</h3>
        <Row label="Host star"      value={report.ingest?.host_star_id}    source="ingest.host_star_id" />
        <Row label="Segments"       value={report.ingest?.n_segments}       source="ingest.n_segments" />
        <Row label="Stellar params" value={report.ingest?.has_stellar_params ? 'yes' : 'no'} source="ingest.has_stellar_params" />
        <Row label="Code version"   value={report.ingest?.code_version}    source="ingest.code_version" />
        <Row label="Ingest time"    value={report.ingest?.wall_time_seconds != null ? `${report.ingest.wall_time_seconds.toFixed(2)} s` : null} source="ingest.wall_time_seconds" />
      </div>

      <div className={`detail-section${hl('search') ? ' highlighted' : ''}`}>
        <h3>Search</h3>
        <Row label="TCEs"        value={report.search?.n_tces ?? 0}  source="search.n_tces" />
        <Row label="TLS version" value={report.search?.tls_version}  source="search.tls_version" />
        <Row label="Search time" value={report.search?.wall_time_seconds != null ? `${report.search.wall_time_seconds.toFixed(2)} s` : null} source="search.wall_time_seconds" />
      </div>

      <div className={`detail-section${hl('lc') ? ' highlighted' : ''}`}>
        <h3>Phase-folded LC</h3>
        <PhaseLCPlot phasedData={vetResult?.phased_lc ?? null} />
      </div>

      {vetResult && (
        <div className={`detail-section${hl('vet') ? ' highlighted' : ''}`}>
          <h3>Vetting <DispoChip disposition={vetResult.disposition} /></h3>
          {VETTING_TEST_ORDER.map((name) => {
            const r = vetResult.test_results?.find((t) => t.test_name === name)
            return (
              <div
                key={name}
                className={`vet-row${vetResult.triggering_test === name ? ' triggering' : ''}`}
              >
                <VetBadge outcome={r?.outcome ?? 'INCONCLUSIVE'} />
                <span className="vet-name">{TEST_LABELS[name]}</span>
                {r?.metric_value != null && (
                  <span className="vet-metric">
                    {r.metric_value.toFixed(3)}{r.metric_unit ? ` ${r.metric_unit}` : ''}
                  </span>
                )}
                <span className="vet-reason">{r?.reason ?? '—'}</span>
              </div>
            )
          })}
        </div>
      )}

      {classifyResult && (
        <div className={`detail-section${hl('classify') ? ' highlighted' : ''}`}>
          <h3>Classify
            <span style={{ color: 'var(--warn)', fontWeight: 400, textTransform: 'none', fontSize: 10 }}>
              {' '}ranking — not a verdict
            </span>
          </h3>
          <Row label="Probability"   value={`${(classifyResult.probability * 100).toFixed(1)} %`}             source="classify.probability" />
          <Row label="± uncertainty" value={`${(classifyResult.probability_uncertainty * 100).toFixed(1)} %`} source="classify.probability_uncertainty" />
          <Row label="Model version" value={classifyResult.model_version} source="classify.model_version" />
          <div style={{ marginTop: 5, fontSize: 10, color: 'var(--muted)', lineHeight: 1.5 }}>
            Disposition is determined exclusively by the vet stage.
          </div>
        </div>
      )}

      {report.non_claims?.length > 0 && (
        <div className="detail-section" style={{ fontSize: 10, color: 'var(--muted)', lineHeight: 1.6 }}>
          <h3>Non-claims</h3>
          {report.non_claims.map((c, i) => <div key={i}>— {c}</div>)}
        </div>
      )}

      <div className="detail-section">
        <h3>Download</h3>
        <button className="dl-btn" onClick={() => dlJson(report, `report_${report.job_id}.json`)}>
          ↓ Full report (JSON)
        </button>
        {report.vet?.length > 0 && (
          <button className="dl-btn" onClick={() => dlJson(report.vet, `vet_${report.job_id}.json`)}>
            ↓ Vetting results (JSON)
          </button>
        )}
      </div>
    </div>
  )
}

function dlJson(obj: unknown, name: string) {
  const b = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  const u = URL.createObjectURL(b)
  const a = document.createElement('a')
  a.href = u; a.download = name; a.click()
  URL.revokeObjectURL(u)
}

// ── Inline console (bottom strip of system view) ──────────────────────────
function InlineConsole() {
  const { consoleLines } = useStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [consoleLines])

  return (
    <div className="panel panel--console">
      <div className="panel-header">
        Console <span className="tag">real calls</span>
        <span className="spacer" />
        <span style={{ fontSize: 10 }}>{consoleLines.length} entries</span>
      </div>
      <div className="console-inner">
        {consoleLines.length === 0 && (
          <div style={{ color: 'var(--muted)', padding: '6px 0' }}>No API calls yet.</div>
        )}
        {consoleLines.map((line, i) => {
          const isOk  = line.status === 200 || line.status === 202 || line.status === '✓' || (typeof line.status === 'number' && line.status < 400)
          const isErr = line.status === 'ERR' || line.status === '✗' || (typeof line.status === 'number' && line.status >= 400)
          return (
            <div key={i} className="console-line">
              <span className="con-ts">{line.ts}</span>
              <span className="con-method" style={{ color: line.method === 'SSE' ? 'var(--warn)' : 'var(--accent)' }}>{line.method}</span>
              <span className="con-url">{line.url}</span>
              <span className={`con-status${isOk ? ' ok' : isErr ? ' err' : ''}`}>
                {line.pending ? '…' : line.status ?? ''}
              </span>
              <span className="con-ms">{line.ms != null ? `${line.ms}ms` : ''}</span>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────
export default function SystemScreen() {
  const { report, jobStatus } = useStore()
  const [use3D, setUse3D] = useState(true)

  const vets          = report?.vet ?? []
  const stellar       = (report as any)?.stellar_params
  const stellarTeff   = stellar?.teff?.values?.[0]   ?? DEFAULT_TEFF
  const stellarRadius = stellar?.radius?.values?.[0] ?? DEFAULT_R_STAR
  const lumLsun       = stellar?.luminosity_lsun     ?? DEFAULT_LUM

  return (
    <div className="screen" style={{ overflow: 'hidden' }}>
      <div className="system-layout">
        {/* Viewer */}
        <div className="panel panel--viewer">
          <div className="panel-header">
            Orbital system
            <span className="tag">Three.js · drag / scroll / click</span>
            <span style={{ marginLeft: 4, fontSize: 10, color: 'var(--muted)' }}>
              sphere=R_p &ensp; colour=T<sub>eq</sub> &ensp; orbit=P
            </span>
            <span className="spacer" />
            {jobStatus && <span className={`job-status-badge ${jobStatus}`}>{jobStatus}</span>}
            <button
              style={{
                background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--r)',
                color: 'var(--muted)', cursor: 'pointer', fontSize: 10, padding: '1px 7px', marginLeft: 6,
              }}
              onClick={() => setUse3D((v) => !v)}
              title={use3D ? 'Switch to list (non-3D)' : 'Switch to 3D view'}
              aria-label={use3D ? 'Switch to list view' : 'Switch to 3D view'}
            >
              {use3D ? 'list view' : '3D view'}
            </button>
          </div>

          <TargetForm />

          {use3D ? (
            <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
              <Canvas
                camera={{ position: [0, 3, 8], fov: 45, near: 0.01, far: 200 }}
                gl={{ antialias: true, alpha: false }}
                style={{ background: '#0a0c0f', width: '100%', height: '100%' }}
              >
                <OrbitControls enablePan={false} minDistance={0.5} maxDistance={30} enableDamping dampingFactor={0.07} />
                {vets.length > 0
                  ? <SceneContent vets={vets} stellarTeff={stellarTeff} stellarRadius={stellarRadius} lumLsun={lumLsun} />
                  : (
                    <>
                      <ambientLight intensity={0.3} />
                      <mesh>
                        <sphereGeometry args={[STAR_SCENE_SIZE * 0.5, 16, 16]} />
                        <meshStandardMaterial color="#374151" emissive="#374151" emissiveIntensity={0.5} />
                      </mesh>
                    </>
                  )
                }
              </Canvas>
              {/* Non-claim overlay */}
              <div className="non-claim-banner">
                Not a biosignature detector · No exoplanet biosignature has ever been confirmed
              </div>
              {/* Visual encoding legend */}
              <div style={{
                position: 'absolute', top: 6, right: 8,
                background: 'rgba(10,12,15,0.82)', border: '1px solid var(--border)',
                borderRadius: 'var(--r)', fontSize: 10, color: 'var(--muted)',
                padding: '5px 8px', lineHeight: 1.7,
              }}>
                <div style={{ color: 'var(--text)', marginBottom: 2, fontSize: 10 }}>Visual encodings</div>
                <div>sphere radius → R_p from depth + R_star</div>
                <div>colour → T_eq (visual only)</div>
                <div>orbit radius → a from Kepler III</div>
                <div>orbit rate → period</div>
                <div>inclination → transit geometry</div>
                <div style={{ color: '#22c55e' }}>green ring → HZ (Kopparapu+2013)</div>
              </div>
            </div>
          ) : (
            <FallbackList vets={vets} stellarTeff={stellarTeff} stellarRadius={stellarRadius} />
          )}
        </div>

        {/* Right detail column */}
        <DetailPanel />

        {/* Bottom console strip */}
        <InlineConsole />
      </div>
    </div>
  )
}
