/**
 * src/data/types.ts
 * Canonical TypeScript types mirroring the Python pipeline contracts.
 * These types are derived from falsifier/api/models.py and
 * falsifier/pipeline/contracts/*.py — shape mismatches here are compile errors.
 */

export type JobStatus = 'queued' | 'running' | 'done' | 'failed'
export type VettingTestOutcome = 'PASS' | 'FAIL' | 'FLAG' | 'INCONCLUSIVE'
export type VettingTestName =
  | 'odd_even_depth'
  | 'secondary_eclipse'
  | 'centroid_shift'
  | 'transit_shape'
  | 'stellar_density'
  | 'gaia_ruwe'
  | 'systematics_coincidence'
export type Disposition =
  | 'candidate'
  | 'candidate_with_caveats'
  | 'false_positive'
  | 'ambiguous'
export type ModuleStatusValue = 'wired' | 'aspirational'

export interface UnitedArray {
  values: number[]
  unit: string
}

export interface VettingTestResult {
  test_name: VettingTestName
  outcome: VettingTestOutcome
  metric_value: number | null
  metric_unit: string | null
  reason: string
}

export interface PhasedLC {
  phase: number[]
  flux: number[]
  /** Secondary (EB companion) flux array — present only for EB false positives */
  flux_secondary?: number[]
  /** Primary eclipse depth in ppm — present only for EB false positives */
  primary_depth_ppm?: number
  /** Secondary eclipse depth in ppm — present only for EB false positives */
  secondary_depth_ppm?: number
}

export interface VettingTestResultSummary {
  test_name: string
  outcome: string
  metric_value: number | null
  metric_unit: string | null
  reason: string
}

export interface VetResult {
  tce_id: string
  disposition: Disposition
  triggering_test: VettingTestName | null
  triggering_reason: string | null
  wall_time_seconds: number
  test_results?: VettingTestResultSummary[]
  period_days?: number | null
  depth_ppm?: number | null
  duration_hours?: number | null
  epoch_bkjd?: number | null
  inclination_deg?: number | null
  phased_lc?: PhasedLC | null
}

export interface ClassifyResult {
  tce_id: string
  probability: number
  probability_uncertainty: number
  model_version: string
}

export interface IngestResult {
  host_star_id: string
  n_segments: number
  has_stellar_params: boolean
  code_version: string
  input_hash: string
  wall_time_seconds: number
}

export interface DetrendResult {
  host_star_id: string
  n_segments: number
  detrending_method: string
  wall_time_seconds: number
}

export interface SearchResult {
  host_star_id: string
  n_tces: number
  tls_version: string
  wall_time_seconds: number
  tce_ids: string[]
}

/** Legacy shape from fixture JSON (nested teff.values[], radius.values[]) */
export interface StellarParamsLegacy {
  teff: UnitedArray
  radius: UnitedArray
  luminosity_lsun: number
}

/** New flat shape from API (StellarParamsSummary in models.py) */
export interface StellarParamsSummary {
  teff_K: number
  radius_rsun: number
  luminosity_lsun: number | null
}

export type StellarParams = StellarParamsLegacy | StellarParamsSummary

/** Type guard: new flat shape */
export function isStellarParamsSummary(sp: StellarParams): sp is StellarParamsSummary {
  return 'teff_K' in sp
}

export interface DetectionReport {
  job_id: string
  target_id: string
  pipeline_run_id: string
  started_at: string
  finished_at: string
  ingest: IngestResult | null
  detrend: DetrendResult | null
  search: SearchResult | null
  vet: VetResult[]
  classify: ClassifyResult[]
  non_claims: string[]
  stellar_params?: StellarParams | null
}

export interface JobRecord {
  job_id: string
  status: JobStatus
  request: {
    target_id: string
    mission: string
    author: string
    cadence: string
    sectors: number[] | null
    run_classify: boolean
  }
  pipeline_run_id: string
  started_at: string | null
  finished_at: string | null
  report: DetectionReport | null
  error: string | null
  events: StageEvent[]
}

export interface StageEvent {
  ts?: string
  event: 'stage_start' | 'stage_done' | 'stage_error' | 'job_done' | 'job_failed'
  stage: string
  status: 'ok' | 'error' | 'skipped'
  detail: string
  artifact_path: string | null
  elapsed_seconds: number | null
}

export interface ModuleStatus {
  module: string
  status: ModuleStatusValue
  note: string
}

export interface DataVersionEntry {
  name: string
  source_doi: string
  access_date: string
  row_count: number | null
  description: string
}

export interface ProvenanceReport {
  falsifier_version: string
  data_versions: DataVersionEntry[]
  modules: ModuleStatus[]
  non_claims: string[]
  golden_manifest_entry_count: number
}

export interface ChatToolCall {
  tool: string
  args: Record<string, unknown>
  result: Record<string, unknown>
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  tool_calls?: ChatToolCall[]
  sources?: string[]
  guardian_verdict?: {
    safe: boolean
    risk_label: string
    model_used: string
    confidence: number | null
  }
  offline_mode?: boolean
}

export interface ChatFixture {
  job_id: string
  tce_id: string
  messages: ChatMessage[]
}

export interface CalibrationBin {
  bin_center: number
  fraction_positive: number
  n_samples: number
}

export interface TrainingMetrics {
  fold: string
  n_samples: number
  auc_roc: number
  brier_score: number
  ece: number
  precision_at_50: number
  recall_at_50: number
  calibration_bins: CalibrationBin[]
}

export interface TrainingFixture {
  session: {
    labeled_set_name: string
    labeled_set_doi: string
    n_rows: number
    n_host_stars: number
    min_rows_threshold: number
    min_host_stars_threshold: number
    leakage_check: {
      passed: boolean
      detail: string
    }
  }
  session_metrics: TrainingMetrics
  baseline_metrics: TrainingMetrics
}
