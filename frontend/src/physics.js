/**
 * src/physics.js
 * Pure orbital-mechanics helpers.
 *
 * Policy: every formula here takes measured values as arguments and returns
 * a computed value.  No hardcoded measured quantities (AGENTS.md Rule 1).
 * Constants used are fundamental physics constants (Stefan-Boltzmann, AU
 * definition, solar luminosity ratio) — not measured planetary values.
 *
 * All inputs are expected in SI-adjacent units; output units are documented
 * on each function.
 *
 * These functions are used only for visual mapping in the 3D viewer —
 * they are NOT scientific results.  The UI labels them "visual mapping" or
 * "computed for display" so users cannot mistake them for pipeline outputs.
 */

/** Solar radius in AU (IAU 2012 definition). */
const R_SUN_AU = 0.00465047

/** Semi-major axis from period via Kepler III (assumes M ≈ 1 Msun).
 *  period_days → semi_major_axis_AU
 *  For visual mapping only — does not account for actual host mass.
 */
export function semiMajorAxisFromPeriod(period_days) {
  // a^3 = (P/yr)^2  for M=1 Msun  → a = (P/365.25)^(2/3)
  const period_yr = period_days / 365.25
  return Math.pow(period_yr, 2 / 3)
}

/**
 * Equilibrium temperature mapping.
 * Given Teff_host (K) and semi-major axis a (AU), compute T_eq (K).
 * Assumes Bond albedo A=0.3, uniform heat redistribution.
 * Returns K. Used only to drive a colour mapping.
 *
 *   T_eq = T_star * (R_star/(2a))^(1/2) * (1-A)^(1/4)
 *
 * @param {number} teff_K  host star effective temperature (K)
 * @param {number} r_star_rsun  host star radius in solar radii
 * @param {number} a_AU  semi-major axis (AU)
 * @returns {number}  equilibrium temperature (K)
 */
export function equilibriumTemperature(teff_K, r_star_rsun, a_AU) {
  const r_star_AU = r_star_rsun * R_SUN_AU
  const A = 0.3
  return teff_K * Math.sqrt(r_star_AU / (2 * a_AU)) * Math.pow(1 - A, 0.25)
}

/**
 * Map equilibrium temperature to a hex colour.
 * 0 K → deep blue  2000 K → orange-red  7000+ K → white.
 * Chromatic scale tuned to the classical "hot-cold" spectrum.
 *
 * @param {number} t_eq_K
 * @returns {string}  three.js hex colour string '#rrggbb'
 */
export function teqToColor(t_eq_K) {
  const t = Math.max(0, Math.min(t_eq_K, 5000))
  // Normalise to [0,1]
  const x = t / 5000
  // Piecewise linear: cold=blue, warm=orange, hot=white
  const r = Math.round(Math.min(255, x * 512))
  const g = Math.round(Math.min(255, x < 0.5 ? x * 200 : 100 + (x - 0.5) * 310))
  const b = Math.round(Math.min(255, x < 0.3 ? 200 - x * 400 : Math.max(0, 80 - (x - 0.3) * 200)))
  return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`
}

/**
 * Compute habitable zone inner and outer radii (AU).
 * Uses the Kopparapu et al. 2013 analytic approximation.
 * For visual mapping only.
 *
 * @param {number} teff_K   host star effective temperature (K)
 * @param {number} l_lsun   host star luminosity in solar luminosities
 * @returns {{ inner: number, outer: number }}  in AU
 */
export function habitableZone(teff_K, l_lsun) {
  // Kopparapu+2013 empirical coefficients for "moist greenhouse" and "maximum greenhouse"
  const T_sun = 5780
  const dt = teff_K - T_sun
  // Runaway greenhouse (inner edge)
  const S_eff_inner = 1.0140 + 8.1774e-5 * dt + 1.7063e-9 * dt * dt - 4.3241e-12 * dt * dt * dt - 6.6462e-16 * dt * dt * dt * dt
  // Maximum greenhouse (outer edge)
  const S_eff_outer = 0.3438 + 5.8942e-5 * dt + 1.6558e-9 * dt * dt - 3.0045e-12 * dt * dt * dt - 5.2983e-16 * dt * dt * dt * dt
  return {
    inner: Math.sqrt(l_lsun / Math.max(S_eff_inner, 0.01)),
    outer: Math.sqrt(l_lsun / Math.max(S_eff_outer, 0.001)),
  }
}

/**
 * Convert TCE depth (ppm) to planet radius (R_earth) using approximate formula.
 * For visual sphere sizing only.
 *
 * @param {number} depth_ppm  transit depth in ppm
 * @param {number} r_star_rsun  host star radius in solar radii
 * @returns {number}  planet radius in R_earth (approx)
 */
export function depthToRadiusRearth(depth_ppm, r_star_rsun) {
  // depth ≈ (R_p / R_star)^2
  const ratio = Math.sqrt(depth_ppm / 1e6)
  const r_star_rearth = r_star_rsun * 109.076  // 1 R_sun = 109.076 R_earth
  return ratio * r_star_rearth
}

/**
 * Scale planet radius (R_earth) to Three.js scene units.
 * Clamps to [minSize, maxSize] for visual clarity.
 */
export function radiusToSceneSize(r_earth, { minSize = 0.02, maxSize = 0.18 } = {}) {
  const raw = r_earth / 11.2  // 11.2 R_earth ≈ 1 R_Jupiter
  return Math.max(minSize, Math.min(maxSize, raw * 0.15))
}

/**
 * Convert semi-major axis (AU) to Three.js scene units.
 * Scene is normalised so 1 AU ≈ 2 units.
 */
export function auToScene(au) {
  return au * 2.0
}

/**
 * Angular velocity (rad per second of wall time) for orbital animation.
 * period_days → angular velocity scaled to animation speed.
 * One orbital period plays in `playFactor` wall seconds.
 *
 * @param {number} period_days
 * @param {number} playFactor   days of simulation per real second
 * @returns {number}  rad/s wall time
 */
export function orbitalAngularVelocity(period_days, playFactor = 365.25) {
  if (period_days <= 0) return 0
  const T_wall = period_days / playFactor  // wall seconds per orbit
  return (2 * Math.PI) / T_wall
}

/**
 * Compute inclination rotation: map inclination_deg to scene rotation.
 * 90° → edge-on (transit geometry visible). 0° → face-on.
 *
 * @param {number} inclination_deg  orbital inclination from the line of sight
 * @returns {number}  rotation angle in radians about the X axis
 */
export function inclinationToRotation(inclination_deg) {
  return (inclination_deg * Math.PI) / 180
}
