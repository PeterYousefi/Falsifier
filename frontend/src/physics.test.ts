/**
 * src/physics.test.ts
 * Regression tests for the orbital-scene physics helpers.
 *
 * All functions under test are pure — no DOM, no React, no network.
 *
 * Tests assert that computed scene properties (sphere radius, colour,
 * orbital radius, habitable-zone edges) change in value when the
 * underlying DetectionReport/stellar_params change, so the orbital
 * view cannot silently freeze.
 *
 * These tests use two synthetic "jobs":
 *   jobA — fixture-like: solar-type star + short-period hot rocky planet
 *   jobB — different star + longer-period cool sub-Neptune
 *
 * Every asserted value must differ between jobA and jobB so that a
 * component using these helpers provably renders a different scene.
 */

import { describe, it, expect } from 'vitest'
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
} from './physics'

// ---------------------------------------------------------------------------
// Synthetic job fixtures — values are illustrative, not measured results.
// They are chosen to be clearly different so scene-prop assertions are
// unambiguous.  No scientific claim is made; these are for regression only.
// ---------------------------------------------------------------------------

const jobA = {
  // Solar-type G-star
  stellarTeff: 5778,
  stellarRadius: 1.0,
  lumLsun: 1.0,
  // Short-period hot rocky planet
  period_days: 0.84,
  depth_ppm: 154,
  inclination_deg: 88.7,
}

const jobB = {
  // Cool K-dwarf
  stellarTeff: 4200,
  stellarRadius: 0.7,
  lumLsun: 0.3,
  // Longer-period cool sub-Neptune
  period_days: 14.3,
  depth_ppm: 2800,
  inclination_deg: 72.0,
}

// ---------------------------------------------------------------------------
// semiMajorAxisFromPeriod
// ---------------------------------------------------------------------------

describe('semiMajorAxisFromPeriod', () => {
  it('returns larger semi-major axis for longer period', () => {
    const smaA = semiMajorAxisFromPeriod(jobA.period_days)
    const smaB = semiMajorAxisFromPeriod(jobB.period_days)
    expect(smaB).toBeGreaterThan(smaA)
  })

  it('1 year → 1 AU (Kepler III identity)', () => {
    expect(semiMajorAxisFromPeriod(365.25)).toBeCloseTo(1.0, 3)
  })
})

// ---------------------------------------------------------------------------
// equilibriumTemperature
// ---------------------------------------------------------------------------

describe('equilibriumTemperature', () => {
  it('returns different Teq for different star/orbit combinations', () => {
    const smaA = semiMajorAxisFromPeriod(jobA.period_days)
    const smaB = semiMajorAxisFromPeriod(jobB.period_days)
    const teqA = equilibriumTemperature(jobA.stellarTeff, jobA.stellarRadius, smaA)
    const teqB = equilibriumTemperature(jobB.stellarTeff, jobB.stellarRadius, smaB)
    expect(teqA).not.toBeCloseTo(teqB, 0)
  })

  it('closer orbit → higher Teq for same star', () => {
    const smaClose = semiMajorAxisFromPeriod(1)
    const smaFar   = semiMajorAxisFromPeriod(365)
    const teqClose = equilibriumTemperature(5778, 1.0, smaClose)
    const teqFar   = equilibriumTemperature(5778, 1.0, smaFar)
    expect(teqClose).toBeGreaterThan(teqFar)
  })
})

// ---------------------------------------------------------------------------
// teqToColor
// ---------------------------------------------------------------------------

describe('teqToColor', () => {
  it('returns a valid hex string', () => {
    expect(teqToColor(500)).toMatch(/^#[0-9a-f]{6}$/)
    expect(teqToColor(2000)).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('color differs between jobA and jobB planet Teq', () => {
    const smaA = semiMajorAxisFromPeriod(jobA.period_days)
    const smaB = semiMajorAxisFromPeriod(jobB.period_days)
    const teqA = equilibriumTemperature(jobA.stellarTeff, jobA.stellarRadius, smaA)
    const teqB = equilibriumTemperature(jobB.stellarTeff, jobB.stellarRadius, smaB)
    // Regression: different jobs → different planet colours in scene
    expect(teqToColor(teqA)).not.toBe(teqToColor(teqB))
  })
})

// ---------------------------------------------------------------------------
// depthToRadiusRearth + radiusToSceneSize
// ---------------------------------------------------------------------------

describe('depthToRadiusRearth', () => {
  it('deeper transit → larger planet radius', () => {
    const rA = depthToRadiusRearth(jobA.depth_ppm, jobA.stellarRadius)
    const rB = depthToRadiusRearth(jobB.depth_ppm, jobB.stellarRadius)
    // jobB has much deeper transit (2800 vs 154 ppm)
    expect(rB).toBeGreaterThan(rA)
  })
})

describe('radiusToSceneSize', () => {
  it('larger planet → larger scene sphere (up to clamp)', () => {
    const rA = depthToRadiusRearth(jobA.depth_ppm, jobA.stellarRadius)
    const rB = depthToRadiusRearth(jobB.depth_ppm, jobB.stellarRadius)
    const sA = radiusToSceneSize(rA)
    const sB = radiusToSceneSize(rB)
    // Regression: different depth → different sphere size in scene
    expect(sB).toBeGreaterThan(sA)
  })

  it('output is within [minSize, maxSize]', () => {
    for (const r of [0.1, 1, 5, 20, 100]) {
      const s = radiusToSceneSize(r)
      expect(s).toBeGreaterThanOrEqual(0.02)
      expect(s).toBeLessThanOrEqual(0.18)
    }
  })
})

// ---------------------------------------------------------------------------
// auToScene
// ---------------------------------------------------------------------------

describe('auToScene', () => {
  it('orbital radius in scene units differs between jobA and jobB', () => {
    const smaA = semiMajorAxisFromPeriod(jobA.period_days)
    const smaB = semiMajorAxisFromPeriod(jobB.period_days)
    // Regression: different period → different orbital radius in scene
    expect(auToScene(smaA)).not.toBeCloseTo(auToScene(smaB), 2)
  })
})

// ---------------------------------------------------------------------------
// orbitalAngularVelocity
// ---------------------------------------------------------------------------

describe('orbitalAngularVelocity', () => {
  it('shorter period → faster angular velocity', () => {
    const omA = orbitalAngularVelocity(jobA.period_days)
    const omB = orbitalAngularVelocity(jobB.period_days)
    expect(omA).toBeGreaterThan(omB)
  })
})

// ---------------------------------------------------------------------------
// inclinationToRotation
// ---------------------------------------------------------------------------

describe('inclinationToRotation', () => {
  it('90 degrees → π/2 radians', () => {
    expect(inclinationToRotation(90)).toBeCloseTo(Math.PI / 2, 5)
  })

  it('different inclination → different rotation', () => {
    expect(inclinationToRotation(jobA.inclination_deg)).not.toBeCloseTo(
      inclinationToRotation(jobB.inclination_deg), 2,
    )
  })
})

// ---------------------------------------------------------------------------
// starSceneSize — new function (regression for BUG 2 fix)
// ---------------------------------------------------------------------------

describe('starSceneSize', () => {
  it('larger star → larger scene size', () => {
    expect(starSceneSize(jobA.stellarRadius)).toBeGreaterThan(starSceneSize(jobB.stellarRadius))
  })

  it('1 Rsun → 0.18 scene units (reference value)', () => {
    expect(starSceneSize(1.0)).toBeCloseTo(0.18, 4)
  })

  it('output is within [minSize, maxSize]', () => {
    for (const r of [0.01, 0.1, 1, 5, 100]) {
      const s = starSceneSize(r)
      expect(s).toBeGreaterThanOrEqual(0.08)
      expect(s).toBeLessThanOrEqual(0.40)
    }
  })

  it('scene size differs between jobA and jobB stars', () => {
    // Regression: different stellarRadius → different star sphere in scene
    expect(starSceneSize(jobA.stellarRadius)).not.toBeCloseTo(starSceneSize(jobB.stellarRadius), 3)
  })
})

// ---------------------------------------------------------------------------
// starColor — new function (regression for BUG 3 fix)
// ---------------------------------------------------------------------------

describe('starColor', () => {
  it('returns a valid hex string', () => {
    expect(starColor(5778)).toMatch(/^#[0-9a-f]{6}$/)
    expect(starColor(3000)).toMatch(/^#[0-9a-f]{6}$/)
    expect(starColor(10000)).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('color differs between jobA and jobB stars', () => {
    // Regression: different stellarTeff → different star color in scene
    expect(starColor(jobA.stellarTeff)).not.toBe(starColor(jobB.stellarTeff))
  })

  it('cool star (3000 K) has less blue than very hot star (25000 K)', () => {
    // At 3000 K t≈0.036: blue channel is zero (below the 0.4 threshold).
    // At 25000 K t≈0.821: blue channel is (0.821-0.4)*425 ≈ 179.
    const coolHex = starColor(3000)
    const hotHex  = starColor(25000)
    const coolR = parseInt(coolHex.slice(1, 3), 16)
    const hotR  = parseInt(hotHex.slice(1, 3), 16)
    const coolB = parseInt(coolHex.slice(5, 7), 16)
    const hotB  = parseInt(hotHex.slice(5, 7), 16)
    expect(hotB).toBeGreaterThan(coolB)   // hot  → more blue
    expect(coolR).toBeGreaterThanOrEqual(hotR) // cool → same or more red (not yet on declining side at 3000 K)
  })
})

// ---------------------------------------------------------------------------
// Full scene-props integration: two different DetectionReports produce
// different scene parameters across every visual channel.
//
// This is the core regression test for the "scene never changes" bug.
// If any of these assertions fail after a refactor, the orbital view
// will silently freeze on the previous job's appearance.
// ---------------------------------------------------------------------------

describe('scene props differ between different DetectionReport inputs', () => {
  const smaA = semiMajorAxisFromPeriod(jobA.period_days)
  const smaB = semiMajorAxisFromPeriod(jobB.period_days)

  const sceneA = {
    orbitRadius:  auToScene(smaA),
    planetSize:   radiusToSceneSize(depthToRadiusRearth(jobA.depth_ppm, jobA.stellarRadius)),
    planetColor:  teqToColor(equilibriumTemperature(jobA.stellarTeff, jobA.stellarRadius, smaA)),
    starSize:     starSceneSize(jobA.stellarRadius),
    starHex:      starColor(jobA.stellarTeff),
    omega:        orbitalAngularVelocity(jobA.period_days),
    inclRad:      inclinationToRotation(jobA.inclination_deg),
    hzInner:      habitableZone(jobA.stellarTeff, jobA.lumLsun).inner,
    hzOuter:      habitableZone(jobA.stellarTeff, jobA.lumLsun).outer,
  }

  const sceneB = {
    orbitRadius:  auToScene(smaB),
    planetSize:   radiusToSceneSize(depthToRadiusRearth(jobB.depth_ppm, jobB.stellarRadius)),
    planetColor:  teqToColor(equilibriumTemperature(jobB.stellarTeff, jobB.stellarRadius, smaB)),
    starSize:     starSceneSize(jobB.stellarRadius),
    starHex:      starColor(jobB.stellarTeff),
    omega:        orbitalAngularVelocity(jobB.period_days),
    inclRad:      inclinationToRotation(jobB.inclination_deg),
    hzInner:      habitableZone(jobB.stellarTeff, jobB.lumLsun).inner,
    hzOuter:      habitableZone(jobB.stellarTeff, jobB.lumLsun).outer,
  }

  it('orbit radius differs', () => {
    expect(sceneA.orbitRadius).not.toBeCloseTo(sceneB.orbitRadius, 2)
  })
  it('planet sphere size differs', () => {
    expect(sceneA.planetSize).not.toBeCloseTo(sceneB.planetSize, 4)
  })
  it('planet color differs', () => {
    expect(sceneA.planetColor).not.toBe(sceneB.planetColor)
  })
  it('star sphere size differs', () => {
    expect(sceneA.starSize).not.toBeCloseTo(sceneB.starSize, 3)
  })
  it('star color differs', () => {
    expect(sceneA.starHex).not.toBe(sceneB.starHex)
  })
  it('angular velocity differs', () => {
    expect(sceneA.omega).not.toBeCloseTo(sceneB.omega, 3)
  })
  it('inclination rotation differs', () => {
    expect(sceneA.inclRad).not.toBeCloseTo(sceneB.inclRad, 3)
  })
  it('habitable zone inner edge differs', () => {
    expect(sceneA.hzInner).not.toBeCloseTo(sceneB.hzInner, 2)
  })
  it('habitable zone outer edge differs', () => {
    expect(sceneA.hzOuter).not.toBeCloseTo(sceneB.hzOuter, 2)
  })
})
