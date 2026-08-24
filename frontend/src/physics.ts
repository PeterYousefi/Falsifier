/**
 * src/physics.ts
 * Pure orbital-mechanics helpers for visual display only.
 *
 * Policy (AGENTS.md Rule 1): every function takes measured values as
 * arguments and returns a computed result. No hardcoded measured quantities.
 * Constants here are fundamental physics / IAU definitions, not measured
 * planetary values. All outputs are labelled "visual only" or "computed for
 * display" in the UI — they are not scientific results.
 */

/** IAU 2012 solar radius in AU */
const R_SUN_AU = 0.00465047

/**
 * Semi-major axis (AU) from orbital period via Kepler III.
 * Assumes host mass ≈ 1 M☉ — for visual mapping only.
 * period_days → semi_major_axis_AU
 */
export function semiMajorAxisFromPeriod(period_days: number): number {
  const period_yr = period_days / 365.25
  return Math.pow(period_yr, 2 / 3)
}

/**
 * Equilibrium temperature (K) for visual colour mapping.
 * Assumes Bond albedo A=0.3, uniform heat redistribution.
 * T_eq = T_star × √(R_star / (2a)) × (1−A)^(1/4)
 *
 * @param teff_K       host star Teff (K)  — from stellar_params
 * @param r_star_rsun  host star radius (Rsun) — from stellar_params
 * @param a_AU         semi-major axis (AU) — from Kepler III
 */
export function equilibriumTemperature(
  teff_K: number,
  r_star_rsun: number,
  a_AU: number,
): number {
  const r_star_AU = r_star_rsun * R_SUN_AU
  const A = 0.3
  return teff_K * Math.sqrt(r_star_AU / (2 * a_AU)) * Math.pow(1 - A, 0.25)
}

/**
 * Map equilibrium temperature to a hex colour string.
 * Cold → blue; warm → orange; hot → white.
 * For visual display only.
 */
export function teqToColor(t_eq_K: number): string {
  const t = Math.max(0, Math.min(t_eq_K, 5000))
  const x = t / 5000
  const r = Math.round(Math.min(255, x * 512))
  const g = Math.round(Math.min(255, x < 0.5 ? x * 200 : 100 + (x - 0.5) * 310))
  const b = Math.round(Math.min(255, x < 0.3 ? 200 - x * 400 : Math.max(0, 80 - (x - 0.3) * 200)))
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}

/**
 * Habitable zone inner and outer radii (AU) via Kopparapu+2013 analytic fit.
 * For visual display only.
 *
 * @param teff_K  host star Teff (K)
 * @param l_lsun  host star luminosity (Lsun)
 */
export function habitableZone(
  teff_K: number,
  l_lsun: number,
): { inner: number; outer: number } {
  const T_sun = 5780
  const dt = teff_K - T_sun
  const dt2 = dt * dt
  const dt3 = dt2 * dt
  const dt4 = dt3 * dt
  // Runaway greenhouse inner edge (moist greenhouse)
  const S_in  = 1.0140 + 8.1774e-5 * dt + 1.7063e-9 * dt2 - 4.3241e-12 * dt3 - 6.6462e-16 * dt4
  // Maximum greenhouse outer edge
  const S_out = 0.3438 + 5.8942e-5 * dt + 1.6558e-9 * dt2 - 3.0045e-12 * dt3 - 5.2983e-16 * dt4
  return {
    inner: Math.sqrt(l_lsun / Math.max(S_in,  0.01)),
    outer: Math.sqrt(l_lsun / Math.max(S_out, 0.001)),
  }
}

/**
 * Approximate planet radius (R_earth) from transit depth and stellar radius.
 * depth ≈ (R_p / R_star)² — for visual sphere sizing only.
 *
 * @param depth_ppm    transit depth (ppm)  — from TCE
 * @param r_star_rsun  host star radius (Rsun) — from stellar_params
 */
export function depthToRadiusRearth(depth_ppm: number, r_star_rsun: number): number {
  const ratio = Math.sqrt(depth_ppm / 1e6)
  const r_star_rearth = r_star_rsun * 109.076   // 1 Rsun = 109.076 Rearth
  return ratio * r_star_rearth
}

/**
 * Scale planet radius (R_earth) to Three.js scene units.
 * Clamps to [minSize, maxSize] for visual clarity.
 */
export function radiusToSceneSize(
  r_earth: number,
  { minSize = 0.02, maxSize = 0.18 } = {},
): number {
  const raw = r_earth / 11.2  // 11.2 Rearth ≈ 1 Rjupiter
  return Math.max(minSize, Math.min(maxSize, raw * 0.15))
}

/**
 * Convert semi-major axis (AU) to Three.js scene units.
 * Normalised: 1 AU ≈ 2 scene units.
 */
export function auToScene(au: number): number {
  return au * 2.0
}

/**
 * Dimensionless orbital distance a/R* from stellar mean density.
 *
 * Derivation (Seager & Mallén-Ornelas 2003, eq. 9):
 *   a³ = G M* / (4π²) × P²
 *   a/R* = [ G ρ* / (3π) × P² ]^(1/3)
 *
 * In SI, with P in seconds:
 *   G = 6.674e-11 m³ kg⁻¹ s⁻²
 *   ρ_sun (mean) = 1408 kg m⁻³
 *
 * Collecting constants into one scalar K with P in days:
 *   K = G × ρ_sun × (86400 s/day)² / (3π)
 *     = 6.674e-11 × 1408 × 7.4649e9 / 9.4248
 *     ≈ 74.39  (dimensionless per [ρ/ρ☉])
 *
 * Verify: P=0.8375d, ρ*=1.07ρ☉ → a/R* = (74.39×1.07×0.7014)^(1/3) ≈ 3.83
 * Literature value: 3.72 (Batalha et al. 2011). Agreement within 3%.
 *
 * @param period_days      orbital period (days)
 * @param density_rho_sun  mean stellar density in solar units (ρ☉)
 */
export function aOverRstar(period_days: number, density_rho_sun: number): number {
  // K = G × ρ_sun × (86400)² / (3π), dimensionless per unit solar density
  const K = 74.39
  return Math.cbrt(K * Math.max(density_rho_sun, 1e-6) * period_days * period_days)
}

/**
 * Canonical phase-to-position mapping used by ALL consumers
 * (3D scene, SVG marker, slider display, animation loop).
 *
 * Convention: phase ∈ [-0.5, +0.5].
 *   phase = 0 → mid-transit (planet directly between observer and star)
 *   phase = ±0.5 → secondary eclipse position
 *
 * Returns (x, z) in orbit-plane scene units.
 *   x is the East-West axis (0 at conjunction).
 *   z points toward the observer.
 *   At phase=0: x=0, z=+orbitR  (planet in front of star, closest to observer).
 *   At phase=±0.25: x=±orbitR, z=0 (quadrature, clear of stellar disk).
 *   At phase=±0.5: x=0, z=-orbitR (planet behind star, secondary eclipse).
 *
 * @param phase    dimensionless orbital phase, wrapped to [-0.5, +0.5]
 * @param orbitR   orbital radius in scene units (from auToScene)
 */
export function phaseToPosition(phase: number, orbitR: number): { x: number; z: number } {
  const theta = phase * 2 * Math.PI  // radians: 0 at mid-transit
  return {
    x: Math.sin(theta) * orbitR,   // 0 at transit/secondary, ±1 at quadrature
    z: Math.cos(theta) * orbitR,   // +orbitR at mid-transit (z toward observer)
  }
}

/**
 * Wrap an arbitrary phase value (in any units consistent with [-0.5, +0.5])
 * back into the [-0.5, +0.5] range.
 */
export function wrapPhase(phase: number): number {
  const p = ((phase % 1) + 1.5) % 1 - 0.5
  return p
}

/**
 * Orbital angular velocity (rad/s wall time) for animation.
 *
 * @param period_days  orbital period (days) — from TCE
 * @param playFactor   simulation days per real second (default = 1 Earth year per second)
 */
export function orbitalAngularVelocity(period_days: number, playFactor = 365.25): number {
  if (period_days <= 0) return 0
  const T_wall = period_days / playFactor
  return (2 * Math.PI) / T_wall
}

/**
 * Map orbital inclination (degrees) to scene rotation angle (radians).
 * 90° → edge-on (transit geometry). 0° → face-on.
 *
 * @param inclination_deg  inclination from line of sight (degrees) — from TCE
 */
export function inclinationToRotation(inclination_deg: number): number {
  return (inclination_deg * Math.PI) / 180
}

/**
 * Host-star sphere radius in Three.js scene units.
 * Scaled proportionally to stellar radius so the visual changes when
 * stellar_params change between jobs.  Clamped for scene legibility.
 *
 * @param r_star_rsun  host star radius (Rsun) — from stellar_params
 */
export function starSceneSize(
  r_star_rsun: number,
  { minSize = 0.08, maxSize = 0.40 } = {},
): number {
  // Reference: 1 Rsun → 0.18 scene units (matching the previous constant)
  const raw = r_star_rsun * 0.18
  return Math.max(minSize, Math.min(maxSize, raw))
}

/**
 * Host-star sphere colour as a hex string, derived from stellar Teff.
 * Follows a simplified blackbody colour ramp: cool red/orange → solar
 * yellow → blue-white for hot stars.  For visual display only.
 *
 * @param teff_K  host star effective temperature (K) — from stellar_params
 */
export function starColor(teff_K: number): string {
  // Map Teff range [2000 K (M-dwarf) … 30 000 K (O-type)] to [0, 1]
  const t = Math.max(0, Math.min(1, (teff_K - 2000) / 28000))
  // Red channel: peaks at mid-range (solar-type), falls at hot blue-white end
  const r = Math.round(t < 0.5 ? 200 + t * 110 : 255 - (t - 0.5) * 400)
  // Green channel: low at cool end, peaks near solar, fades at very hot
  const g = Math.round(t < 0.3 ? t * 500 : t < 0.6 ? 150 - (t - 0.3) * 100 : 120 + (t - 0.6) * 200)
  // Blue channel: negligible at cool end, rises steeply for hot stars
  const b = Math.round(t < 0.4 ? 0 : (t - 0.4) * 425)
  const clamp = (v: number) => Math.max(0, Math.min(255, v))
  return `#${clamp(r).toString(16).padStart(2, '0')}${clamp(g).toString(16).padStart(2, '0')}${clamp(b).toString(16).padStart(2, '0')}`
}
