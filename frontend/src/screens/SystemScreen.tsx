/**
 * src/screens/SystemScreen.tsx
 * Landing page + investigation view.
 * Newspaper layout: headline question, plain prose, three-step strip,
 * prominent example button, search input, worked verdict preview.
 * Orbital 3D view as a bordered figure-inset with caption.
 * All visual properties driven from data layer — no scientific literals.
 */
import React, { useRef, useMemo, useState, useEffect, useCallback } from 'react'
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
  starSceneSize,
  starColor,
} from '../physics'
import type { VetResult } from '../data/types'
import { DispoChip } from './CandidateDetail'
import { dataSource, FixtureDataSource } from '../data/DataSource'

/** True when running against committed fixtures (no live backend). */
const IS_DEMO_MODE = dataSource instanceof FixtureDataSource
/** The one fixture target that demo mode can actually show results for. */
const FIXTURE_TARGET_ID = 'KIC 11904151'

// Host-star visual defaults when stellar_params absent.
// These constants are fallback display values, not scientific claims.
const STAR_SCENE_SIZE_DEFAULT = 0.18
const HZ_OPACITY_DEFAULT      = 0.09

// ── Deterministic phase seed ──────────────────────────────────────────────
// Maps a tce_id string to a stable phase offset in [0, 2π).
// This replaces Math.random() in Planet.phase so the scene is reproducible
// and correctly rebuilds when the active job_id changes.
function _hashPhase(tce_id: string): number {
  let h = 0
  for (let i = 0; i < tce_id.length; i++) {
    h = (Math.imul(31, h) + tce_id.charCodeAt(i)) | 0
  }
  // Map unsigned 32-bit range to [0, 2π)
  return ((h >>> 0) / 0xFFFFFFFF) * Math.PI * 2
}

// ── Example targets across missions ─────────────────────────────────────
const EXAMPLE_TARGETS = [
  { id: 'KIC 11904151', mission: 'Kepler',  cadence: 'long',  label: 'Kepler-10b host',            gloss: 'KIC 11904151 — a star in NASA\'s Kepler Input Catalogue, hosting the confirmed planet Kepler-10b' },
  { id: 'TIC 150428135', mission: 'TESS',   cadence: 'long',  label: 'TOI-700 (TESS)',              gloss: 'TOI-700 — a star observed by NASA\'s TESS satellite, hosting planet candidates in its habitable zone' },
  { id: 'TIC 200322593', mission: 'TESS',   cadence: 'long',  label: 'TRAPPIST-1 (TESS)',          gloss: 'TRAPPIST-1 — an ultra-cool dwarf star hosting seven confirmed planets, observed by NASA\'s TESS satellite' },
  { id: 'KIC 6965293',   mission: 'Kepler', cadence: 'long',  label: 'KIC 6965293 (Kepler EB)',    gloss: 'KIC 6965293 — a star in the Kepler Input Catalogue; its signal is an eclipsing binary (not a planet)' },
]

// ── Orbit ring ────────────────────────────────────────────────────────────
function OrbitRing({ radius }: { radius: number }) {
  const pts = useMemo(() => {
    const a: THREE.Vector3[] = []
    for (let i = 0; i <= 128; i++) {
      const t = (i / 128) * Math.PI * 2
      a.push(new THREE.Vector3(Math.cos(t) * radius, 0, Math.sin(t) * radius))
    }
    return a
  }, [radius])
  return <Line points={pts} color="#8A8880" lineWidth={0.4} />
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
      <meshBasicMaterial color="#2D6A2D" transparent opacity={HZ_OPACITY_DEFAULT} side={THREE.DoubleSide} />
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
  // Deterministic phase offset derived from tce_id so the scene is reproducible
  // and rebuilds correctly when a new job produces a different tce_id.
  // Using Math.random() here was a bug: same tce_id → stale phase; different
  // job, same tce_id → still stale.  The hash gives stable, unique offsets.
  const phase   = useMemo(() => _hashPhase(vet.tce_id), [vet.tce_id])

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
      <Line points={pts} color="#993C1D" lineWidth={0.8} dashed dashSize={0.12} gapSize={0.08} />
      <Text position={[0, 0.12, 5.8]} fontSize={0.07} color="#993C1D" anchorX="center" anchorY="middle">
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
  // Star visual properties derived from stellar_params — not hardcoded.
  const starSize  = useMemo(() => starSceneSize(stellarRadius), [stellarRadius])
  const starHex   = useMemo(() => starColor(stellarTeff), [stellarTeff])

  return (
    <>
      <ambientLight intensity={0.6} />
      <pointLight position={[0, 0, 0]} intensity={2.0} distance={20} decay={2} />
      <directionalLight position={[5, 5, 5]} intensity={0.4} />
      <mesh>
        <sphereGeometry args={[starSize, 24, 24]} />
        <meshStandardMaterial color={starHex} emissive={starHex} emissiveIntensity={1.2} />
      </mesh>
      <Text position={[0, starSize + 0.07, 0]} fontSize={0.06} color="#5A5850" anchorX="center">
        {'host star'}
      </Text>
      <HZRing inner={hzIn} outer={hzOut} />
      <Text position={[hzIn + (hzOut - hzIn) / 2, 0.06, 0]} fontSize={0.055} color="#2D6A2D" anchorX="center">
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
        <p style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: 'var(--np-muted)', fontSize: 14 }}>
          No candidates yet. Run a target above to begin.
        </p>
      </div>
    )
  }
  return (
    <div className="orbital-fallback" role="list" aria-label="TCE list (non-3D)">
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--np-muted)', marginBottom: 10, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
        Non-3D list · colour = T<sub>eq</sub> · orbit radius = semi-major axis
      </p>
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
            className={`orbital-fallback-row${active ? ' active' : ''}`}
            onClick={() => setSelectedTceId(v.tce_id)}
            role="listitem"
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

// ── Target search form ─────────────────────────────────────────────────────
function TargetForm({ defaultTarget, defaultMission, defaultCadence }: {
  defaultTarget?: string
  defaultMission?: string
  defaultCadence?: string
}) {
  const { targetId, setTargetId, isSubmitting, jobStatus, submitJob } = useStore()
  const [mission, setMission] = useState(defaultMission ?? 'Kepler')
  const [cadence, setCadence] = useState(defaultCadence ?? 'long')
  const [demoNotice, setDemoNotice] = useState<string | null>(null)
  const busy = isSubmitting || jobStatus === 'running' || jobStatus === 'queued'

  useEffect(() => {
    if (defaultTarget) setTargetId(defaultTarget)
    if (defaultMission) setMission(defaultMission)
    if (defaultCadence) setCadence(defaultCadence)
  }, [defaultTarget, defaultMission, defaultCadence])

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    const id = targetId.trim()
    if (!id) return
    if (IS_DEMO_MODE && id !== FIXTURE_TARGET_ID) {
      // In demo mode there is no backend. Running any target other than the
      // committed fixture would silently return KIC 11904151 data, which is
      // misleading. Show an inline notice and do not run.
      setDemoNotice(
        `Demo mode — live catalogue lookup requires the pipeline backend. ` +
        `Only ${FIXTURE_TARGET_ID} has a committed fixture. ` +
        `Use "Run the Kepler-10b example →" to see the full pipeline output.`
      )
      return
    }
    setDemoNotice(null)
    submitJob(id, mission, cadence)
  }, [targetId, mission, cadence, submitJob])

  return (
    <div>
      <form
        className="search-row"
        style={{ margin: '16px 0' }}
        onSubmit={handleSubmit}
      >
        <input
          value={targetId}
          onChange={(e) => { setTargetId(e.target.value); setDemoNotice(null) }}
          placeholder={IS_DEMO_MODE ? 'Demo mode — only KIC 11904151 available' : 'e.g. KIC 11904151 · TIC 150428135 · TIC 200322593'}
          disabled={busy}
          aria-label="Target catalogue identifier"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}
        />
        <select value={mission} onChange={(e) => setMission(e.target.value)} disabled={busy || IS_DEMO_MODE} aria-label="Mission">
          <option>Kepler</option>
          <option>K2</option>
          <option>TESS</option>
        </select>
        <select value={cadence} onChange={(e) => setCadence(e.target.value)} disabled={busy || IS_DEMO_MODE} aria-label="Cadence">
          <option value="long">long cadence</option>
          <option value="short">short cadence</option>
        </select>
        <button type="submit" className="btn-primary" disabled={busy || !targetId.trim()}>
          {busy ? <><span className="spinner" aria-label="Running" /> Running…</> : 'Run'}
        </button>
      </form>
      {demoNotice && (
        <div role="alert" aria-live="assertive" style={{
          marginTop: 4, padding: '8px 12px',
          background: 'var(--np-surface)',
          border: '1px solid var(--np-rule)',
          borderLeft: '3px solid var(--warn)',
          fontFamily: 'var(--font-serif)', fontSize: 13,
          color: 'var(--np-muted)', lineHeight: 1.55,
        }}>
          <strong style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--warn)', letterSpacing: '0.06em' }}>DEMO MODE</strong>
          {' '}{demoNotice}
        </div>
      )}
    </div>
  )
}

// ── Verdict preview (worked example from fixture) ─────────────────────────
function VerdictPreview() {
  const { report, setActiveScreen } = useStore()
  if (!report) return null

  const vet = report.vet?.[0]
  if (!vet) return null

  const allPass = vet.test_results?.every((t) => t.outcome === 'PASS')
  const headline = vet.disposition === 'candidate'
    ? `${report.target_id} — candidate planet survives all ${vet.test_results?.length ?? 0} challenges`
    : vet.disposition === 'false_positive'
      ? `${report.target_id} — rejected: ${vet.triggering_reason ?? 'see vetting report'}`
      : `${report.target_id} — ${vet.disposition.replace(/_/g, ' ')}`

  return (
    <div className="verdict-card">
      <div className="section-label">Worked verdict — fixture: {report.target_id}</div>
      <h2 style={{ fontFamily: 'var(--font-head)', fontSize: 20, marginBottom: 8 }}>{headline}</h2>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <DispoChip disposition={vet.disposition} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--np-muted)' }}>
          Period: {vet.period_days != null ? vet.period_days.toFixed(4) + ' d' : '—'}
          {' · '}
          Depth: {vet.depth_ppm != null ? vet.depth_ppm.toFixed(0) + ' ppm' : '—'}
        </span>
      </div>
      <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', lineHeight: 1.6, marginBottom: 12 }}>
        {allPass
          ? 'Every automated challenge returned negative: dip depths match across odd and even events, no secondary eclipse detected, the brightness centroid stays fixed, and the transit profile matches a limb-darkened planet. The stellar density inferred from transit geometry is consistent with the spectroscopic measurement.'
          : `One or more automated challenges raised a flag. The triggering test was ${vet.triggering_test ?? 'unknown'}.`
        }
      </p>
      <button
        className="btn-secondary"
        onClick={() => setActiveScreen('detail')}
        aria-label="View full report"
      >
        Read the full report →
      </button>
    </div>
  )
}

// ── Landing page content ──────────────────────────────────────────────────
function LandingContent() {
  const { setTargetId, submitJob, setActiveScreen, jobStatus, isSubmitting } = useStore()
  const [tooltipIdx, setTooltipIdx] = useState<number | null>(null)

  const runExample = () => {
    const ex = EXAMPLE_TARGETS[0]
    setTargetId(ex.id)
    submitJob(ex.id, ex.mission, ex.cadence)
    setActiveScreen('detail')
  }

  const busy = isSubmitting || jobStatus === 'running' || jobStatus === 'queued'

  return (
    <div className="page-body">
      {/* Article dateline + headline */}
      <hr className="rule-double" />
      <div className="article-dateline" style={{ marginTop: 16 }}>
        NO. 001 · KEPLER · K2 · TESS · LONG CADENCE
      </div>
      <h1 style={{ textAlign: 'center', fontSize: 'clamp(28px, 5vw, 48px)', marginBottom: 8 }}>
        Is that a planet, or something pretending to be one?
      </h1>
      <p className="standfirst" style={{ textAlign: 'center', borderLeft: 'none', paddingLeft: 0 }}>
        Seven automated challenges. Every false positive fingerprint tested in sequence.
        Nothing is hidden.
      </p>
      <hr className="rule-hair" />

      {/* Two-column opening prose with drop cap */}
      <div className="article-columns prose-drop" style={{ marginTop: 20 }}>
        <p>
          Every so often, a star dims by a tiny fraction — perhaps one part in ten thousand —
          and then brightens again. It looks exactly like something passing in front of it.
          It might be a planet. It might also be a companion star whose orbit carries it into
          our line of sight, or a systematic error baked into the spacecraft's sensors, or
          scattered light from a brighter neighbour. The signal alone cannot tell you which.
        </p>
        <p>
          <em>Falsifier</em> runs the dimming event through seven independent challenges,
          each designed to expose a specific kind of impersonator: eclipsing-binary dips
          come in pairs of unequal depth; contaminating stars shift the brightness centroid;
          instrumental artefacts align with spacecraft roll manoeuvres. A real planet
          fails none of these tests. Anything that fails even one is flagged — the harder
          the challenge, the more confident the rejection.
        </p>
        <p>
          The tool covers observations from NASA's Kepler telescope
          (a space observatory that watched a fixed field of 150,000 stars for four years),
          its second mission K2, and the newer TESS satellite (which scans the entire sky
          in 27-day segments). You can investigate a catalogue target by identifier or
          upload your own light curve.
        </p>
        <p>
          A calibrated ranking score is computed alongside the vetting result,
          but that number is a <em>sorting signal only</em> — it is not a detection claim.
          Disposition is determined exclusively by the seven vetting tests.
          This tool is not a biosignature detector; no exoplanet biosignature has ever been confirmed.
        </p>
      </div>

      {/* I. THE SEVEN CHALLENGES */}
      <hr className="rule-hair" style={{ marginTop: 24 }} />
      <div className="section-label" style={{ marginTop: 20, textAlign: 'center' }}>I. How it works</div>
      <div className="how-strip">
        <div className="how-step">
          <div className="how-step-num">I</div>
          <div className="how-step-title">Fetch</div>
          <div className="how-step-body">
            Light curve data are pulled from the Kepler or TESS archive by catalogue ID,
            detrended to remove stellar variability, and segmented for analysis.
          </div>
        </div>
        <div className="how-step">
          <div className="how-step-num">II</div>
          <div className="how-step-title">Search</div>
          <div className="how-step-body">
            The Transit Least Squares algorithm folds the detrended curve at all plausible
            periods to identify periodic dimming events above a signal-to-noise threshold.
          </div>
        </div>
        <div className="how-step">
          <div className="how-step-num">III</div>
          <div className="how-step-title">Challenge</div>
          <div className="how-step-body">
            Seven automated tests probe each event for the fingerprints of false positives.
            Every result is reported with its measured metric and threshold — nothing is hidden.
          </div>
        </div>
      </div>

      {/* III. BEGIN */}
      <hr className="rule-double" style={{ marginTop: 28 }} />
      <div className="section-label" style={{ marginBottom: 14 }}>III. Begin</div>

      {/* Fixture-mode notice */}
      <div style={{
        background: 'var(--np-surface)',
        border: '1px solid var(--np-rule)',
        borderLeft: '3px solid var(--warn)',
        padding: '10px 14px',
        fontFamily: 'var(--font-serif)',
        fontSize: 13,
        color: 'var(--np-muted)',
        lineHeight: 1.6,
        marginBottom: 18,
      }} role="note">
        <strong style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--warn)', letterSpacing: '0.06em' }}>
          DEMO MODE — NO BACKEND DEPLOYED
        </strong>
        <br />
        All runs replay the committed Kepler-10b fixture (KIC 11904151). Entering any catalogue ID
        produces the same fixture result — this is by design for a frontend-only deployment.
        The pipeline backend is not required to explore every screen.
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, margin: '0 0 24px' }}>
        <div>
          <button
            className="btn-primary"
            onClick={runExample}
            disabled={busy}
            aria-label="Run the Kepler-10b example"
            style={{ fontSize: 16, padding: '13px 28px' }}
          >
            {busy
              ? <><span className="spinner" /> Running…</>
              : 'Run the Kepler-10b example →'
            }
          </button>
          <span style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--np-muted)', marginLeft: 14 }}>
            Kepler-10b is a confirmed hot rocky planet — every challenge passes.
          </span>
        </div>

        <div>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--np-muted)', marginBottom: 8 }}>
            Or enter any catalogue identifier:
          </div>
          <TargetForm />
        </div>

        <div>
          <div className="section-label" style={{ marginBottom: 8 }}>Example targets</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {EXAMPLE_TARGETS
              // In demo mode only show the fixture target — others silently
              // return the same fixture data, which is more confusing than helpful.
              .filter((t) => !IS_DEMO_MODE || t.id === FIXTURE_TARGET_ID)
              .map((t, i) => (
              <div key={t.id} style={{ position: 'relative', display: 'inline-block' }}>
                <button
                  className="target-chip"
                  onClick={() => { setTargetId(t.id); submitJob(t.id, t.mission, t.cadence) }}
                  onMouseEnter={() => setTooltipIdx(i)}
                  onMouseLeave={() => setTooltipIdx(null)}
                  onFocus={() => setTooltipIdx(i)}
                  onBlur={() => setTooltipIdx(null)}
                  aria-describedby={`chip-tip-${i}`}
                  disabled={busy}
                >
                  {t.label}
                </button>
                {tooltipIdx === i && (
                  <div
                    id={`chip-tip-${i}`}
                    role="tooltip"
                    style={{
                      position: 'absolute', top: '100%', left: 0, zIndex: 50,
                      background: 'var(--np-text)', color: 'var(--np-paper)',
                      fontFamily: 'var(--font-serif)', fontSize: 12,
                      padding: '6px 10px', borderRadius: 'var(--r)',
                      whiteSpace: 'normal', maxWidth: 280, lineHeight: 1.5,
                      marginTop: 4, pointerEvents: 'none',
                    }}
                  >
                    {t.gloss}
                  </div>
                )}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            <a href="#upload" onClick={(e) => { e.preventDefault(); useStore.getState().setActiveScreen('upload') }}
               style={{ fontFamily: 'var(--font-serif)', fontSize: 14 }}>
              Have your own observations? Upload a light curve →
            </a>
          </div>
        </div>
      </div>

      {/* Worked verdict preview */}
      <VerdictPreview />
    </div>
  )
}

// ── Orbital figure (used after running a job) ─────────────────────────────
function OrbitalFigure() {
  const { report, jobStatus } = useStore()
  const [use3D, setUse3D] = useState(true)

  // Reset view toggle to 3D whenever a new job report arrives so the orbital
  // scene is always shown first (fixes: user toggled to list view on job A,
  // then job B completed — they would see job B's data in list view only).
  useEffect(() => {
    setUse3D(true)
  }, [report?.job_id])

  const vets          = report?.vet ?? []
  const stellar       = (report as any)?.stellar_params
  const stellarTeff   = stellar?.teff?.values?.[0]   ?? 5778
  const stellarRadius = stellar?.radius?.values?.[0] ?? 1.0
  const lumLsun       = stellar?.luminosity_lsun     ?? 1.0

  if (!report) return null

  return (
    <div className="page-body" style={{ paddingTop: 0 }}>
      <hr className="rule-hair" />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div className="section-label" style={{ marginBottom: 0 }}>
          Orbital system — {report.target_id}
          {jobStatus && <span className={`job-status-badge ${jobStatus}`} style={{ marginLeft: 10 }}>{jobStatus}</span>}
        </div>
        <button
          className="btn-secondary"
          style={{ fontSize: 12, padding: '4px 12px' }}
          onClick={() => setUse3D((v) => !v)}
          title={use3D ? 'Switch to list (non-3D)' : 'Switch to 3D view'}
          aria-label={use3D ? 'Switch to list view' : 'Switch to 3D view'}
        >
          {use3D ? 'List view' : '3D view'}
        </button>
      </div>

      {use3D ? (
        <figure className="figure-inset">
          <hr className="figure-inset-rule-top" />
          <div className="figure-inset-plot" style={{ height: 320, position: 'relative' }}>
            {/* key on Canvas forces full teardown + remount when job changes,
                ensuring Three.js internal geometry/material state is rebuilt
                from the new report rather than mutating the old scene objects. */}
            <Canvas
              key={report.job_id}
              camera={{ position: [0, 3, 8], fov: 45, near: 0.01, far: 200 }}
              gl={{ antialias: true, alpha: false }}
              style={{ background: '#F9F6EE', width: '100%', height: '100%' }}
            >
              <OrbitControls enablePan={false} minDistance={0.5} maxDistance={30} enableDamping dampingFactor={0.07} />
              {vets.length > 0
                ? <SceneContent vets={vets} stellarTeff={stellarTeff} stellarRadius={stellarRadius} lumLsun={lumLsun} />
                : (
                  <>
                    <ambientLight intensity={0.4} />
                    <mesh>
                      <sphereGeometry args={[STAR_SCENE_SIZE_DEFAULT * 0.6, 16, 16]} />
                      <meshStandardMaterial color="#B4B2A9" emissive="#B4B2A9" emissiveIntensity={0.4} />
                    </mesh>
                  </>
                )
              }
            </Canvas>
          </div>
          <hr className="figure-inset-rule-bottom" />
          <div className="figure-label">FIG. 1</div>
          <figcaption>
            Orbital diagram computed from pipeline output. Sphere radius encodes R_p from transit depth and host-star radius;
            colour encodes equilibrium temperature T<sub>eq</sub> (visual only). Green ring = habitable zone (Kopparapu 2013).
            Dashed red line = line of sight toward Earth. Drag to rotate; scroll to zoom.
          </figcaption>
        </figure>
      ) : (
        <div style={{ border: '1px solid var(--np-rule)', padding: '12px 16px', background: 'var(--np-surface)', marginBottom: 16 }}>
          <FallbackList vets={vets} stellarTeff={stellarTeff} stellarRadius={stellarRadius} />
        </div>
      )}
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────
export default function SystemScreen() {
  return (
    <div className="screen" style={{ overflowY: 'auto' }}>
      <LandingContent />
      <OrbitalFigure />
    </div>
  )
}
