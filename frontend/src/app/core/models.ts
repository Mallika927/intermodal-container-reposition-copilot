/**
 * TypeScript mirrors of backend/app/data/models.py and
 * backend/app/agent/schemas.py. Field names are kept snake_case to match
 * the JSON wire format exactly — do not rename.
 */

export type EquipmentType = '53FT-DRY' | '40FT-DRY' | '53FT-REEFER';

export type Severity = 'critical' | 'warning' | 'ok' | 'surplus';

export type Priority = 'HIGH' | 'MEDIUM' | 'LOW';

export type RecommendationStatus = 'pending' | 'approved' | 'modified' | 'rejected' | 'expired';

export type DecisionAction = 'approved' | 'modified' | 'rejected';

export interface ImbalanceEntry {
  terminal: string;
  equipment_type: EquipmentType;
  on_hand: number;
  inbound_empties_72h: number;
  demand_72h: number;
  projected_balance: number;
  severity: Severity;
}

export interface ImbalanceReport {
  computed_at: string;
  no_show_rate: number;
  entries: ImbalanceEntry[];
}

export interface CandidateOption {
  option_id: string;
  origin: string;
  dest: string;
  equipment_type: EquipmentType;
  units: number;
  feasible_slots_72h: number;
  slots_needing_projection: number;
  cost_usd: number;
  revenue_protected_usd: number;
  storage_savings_usd: number;
  net_usd: number;
  origin_floor_breach: boolean;
  note: string | null;
}

export interface ExecutionLeg {
  train_id: string;
  units: number;
  confidence: number;
}

export interface RejectedAlternative {
  option_id: string;
  summary: string;
  rejected_because: string;
}

export interface Recommendation {
  id: string;
  created_ts: string;
  lane_id: string;
  equipment_type: EquipmentType;
  units: number;
  priority: Priority;
  execution_legs: ExecutionLeg[];
  cost_usd: number;
  revenue_protected_usd: number;
  net_benefit_usd: number;
  reasoning_summary: string;
  risks: string[];
  alternatives_considered: RejectedAlternative[];
  source_option_id: string;
  status: RecommendationStatus;
  expires_at: string;
}

export interface PlannerDecision {
  id: string;
  recommendation_id: string;
  action: DecisionAction;
  modified_units: number | null;
  reason: string | null;
  decided_ts: string;
}

export interface TraceEntry {
  type: string;
  [key: string]: unknown;
}

export interface CycleResult {
  cycle_id: string;
  started_ts: string;
  completed_ts: string;
  recommendations: Recommendation[];
  no_action_rationale: string | null;
  trace: TraceEntry[];
  replay: boolean;
}
