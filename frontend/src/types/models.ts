export type Role = 'viewer' | 'operator' | 'technician' | 'engineer' | 'data_scientist' | 'admin' | 'super_admin';

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  mfa_enabled: boolean;
  asset_scopes: string[];
  phone?: string | null;
  last_login?: string | null;
  created_at: string;
  permissions?: string[];
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface LoginResult {
  mfa_required: boolean;
  mfa_token?: string | null;
  tokens?: TokenPair | null;
  user?: User | null;
}

export interface AssetType {
  id: string;
  name: string;
  category: string;
  criticality: number;
  description?: string | null;
}

export interface Asset {
  id: string;
  external_id: string;
  name: string;
  asset_type_id: string;
  asset_type?: AssetType | null;
  parent_id: string | null;
  path: string;
  location: { type: 'Point'; coordinates: [number, number] } | null;
  metadata: Record<string, unknown> | null;
  status: 'active' | 'inactive' | 'maintenance';
  commissioned_at?: string | null;
  warranty_until?: string | null;
  created_at: string;
  tags?: Tag[];
}

export interface AssetNode extends Asset {
  children: AssetNode[];
  open_alerts: number;
}

export interface Tag {
  id: string;
  asset_id: string;
  external_id: string;
  name: string;
  parameter: string;
  unit: string;
  min_valid: number | null;
  max_valid: number | null;
  design_value: number | null;
  source_protocol: string;
}

export interface LatestValue {
  tag_id: string;
  tag?: string | null;
  asset_id?: string | null;
  parameter?: string | null;
  unit?: string | null;
  time: string;
  value: number;
  quality: number;
  status: 'good' | 'suspect' | 'bad' | string;
}

export interface TelemetryPoint {
  time: string;
  tag_id: string;
  value: number;
  quality?: number;
  status?: string;
}

export interface AggregatePoint {
  bucket: string;
  tag_id: string;
  avg_value: number | null;
  min_value: number | null;
  max_value: number | null;
  count: number;
}

export type AlertStatus = 'triggered' | 'acknowledged' | 'investigating' | 'escalated' | 'resolved' | 'closed';

export interface AlertEvent {
  id: string;
  from_status: string | null;
  to_status: string;
  actor: string | null;
  note: string | null;
  created_at: string;
}

export interface Rule {
  id: string;
  name: string;
  description: string | null;
  asset_id: string | null;
  tag_id: string | null;
  rule_type: 'threshold' | 'rate' | 'deviation' | 'composite' | 'predictive';
  severity: 'critical' | 'major' | 'minor' | 'warning' | 'info';
  condition: Record<string, unknown>;
  escalation_minutes: number;
  enabled: boolean;
  cooldown_minutes: number;
  created_at: string;
}

export interface Alert {
  id: string;
  rule_id: string | null;
  asset_id: string | null;
  tag_id: string | null;
  incident_id: string | null;
  severity: Rule['severity'];
  status: AlertStatus;
  title: string;
  message: string | null;
  source: string;
  trigger_value: number | null;
  threshold_value: number | null;
  fault_code: string | null;
  escalation_level: number;
  occurrence_count: number;
  suppressed: boolean;
  created_at: string;
  updated_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  asset_name?: string | null;
  asset_path?: string | null;
  events?: AlertEvent[];
  rule?: Rule | null;
  related_telemetry?: TelemetryPoint[];
}

export interface KpiDefinition {
  id: string;
  code: string;
  number: number | null;
  name: string;
  formula: string;
  unit: string;
  category: string;
  threshold_warning: number | null;
  threshold_critical: number | null;
  aggregation_type: string;
  description: string | null;
  higher_is_better: boolean;
  target: number | null;
  visualization: string | null;
  alert_condition: string | null;
  scope: string;
  is_builtin: boolean;
}

export interface KpiCurrent {
  kpi: KpiDefinition;
  asset_id: string | null;
  value: number | null;
  status: 'normal' | 'warning' | 'critical' | 'no_data';
  time: string | null;
  previous_value: number | null;
  trend_pct: number | null;
  sparkline?: number[];
}

export interface KpiValue {
  time: string;
  asset_id: string;
  value: number;
  normalized_value: number | null;
  status: string;
}

export interface Widget {
  id: string;
  widget_type: string;
  title: string;
  config: Record<string, unknown>;
  position_index: number;
  width: number;
}

export interface Dashboard {
  id: string;
  owner_id: string | null;
  name: string;
  description: string | null;
  is_template: boolean;
  is_shared: boolean;
  version: number;
  widgets: Widget[];
  updated_at: string;
}

export interface Report {
  id: string;
  name: string;
  report_type: string;
  format: 'pdf' | 'excel' | 'html';
  status: 'pending' | 'running' | 'completed' | 'failed';
  file_size: number | null;
  due_at: string | null;
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface ReportSchedule {
  id: string;
  name: string;
  report_type: string;
  format: string;
  cron: string;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  recipients: string[];
}

export interface WorkOrder {
  id: string;
  number: string;
  asset_id: string;
  asset_name?: string | null;
  alert_id: string | null;
  title: string;
  description: string | null;
  wo_type: 'corrective' | 'preventive' | 'predictive' | 'inspection' | 'audit_finding';
  priority: 'low' | 'medium' | 'high' | 'urgent';
  status: 'open' | 'assigned' | 'in_progress' | 'completed' | 'cancelled';
  assigned_to: string | null;
  due_date: string | null;
  started_at: string | null;
  completed_at: string | null;
  labor_hours: number | null;
  cost: number | null;
  failure_code: string | null;
  created_at: string;
}

export interface MlModel {
  id: string;
  name: string;
  model_type: string;
  version: string;
  stage: 'none' | 'staging' | 'production' | 'archived';
  metrics: Record<string, number | null>;
  params: Record<string, unknown>;
  features: string[];
  acceptance: { passed: boolean; checks: Record<string, { value: number | null; passed: boolean }> } | null;
  training_window: { start: string; end: string; rows: number } | null;
  created_by: string | null;
  approved_by: string | null;
  deployed_at: string | null;
  created_at: string;
}

export interface OptimizationPlan {
  id: string;
  name: string;
  schedule_type: 'pump' | 'dosing';
  status: string;
  solver_status: string | null;
  horizon_hours: number;
  inputs: Record<string, unknown>;
  plan: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  estimated_cost: number | null;
  baseline_cost: number | null;
  savings_pct: number | null;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  actor: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  source_ip: string | null;
  details: Record<string, unknown> | null;
  hash: string;
  prev_hash: string;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  permissions: string[];
  asset_scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked: boolean;
  created_at: string;
  api_key?: string;
}
