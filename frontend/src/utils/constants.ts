export const SEVERITIES = ['critical', 'major', 'minor', 'warning', 'info'] as const;
export const ALERT_STATUSES = ['triggered', 'acknowledged', 'investigating', 'escalated', 'resolved', 'closed'] as const;
export const OPEN_STATUSES = ['triggered', 'acknowledged', 'investigating', 'escalated'];
export const KPI_CATEGORIES = ['operational', 'quality', 'energy', 'maintenance', 'compliance', 'financial'] as const;
export const REPORT_TYPES: Record<string, string> = {
  shift_handover: 'Shift handover',
  compliance_daily: 'Daily compliance',
  compliance_monthly: 'Monthly compliance',
  kpi_summary: 'KPI summary',
  alert_summary: 'Alert summary',
  asset_performance: 'Asset performance benchmark',
  custom: 'Custom',
};
export const SECTION_LABELS: Record<string, string> = {
  summary: 'Summary', kpi_summary: 'KPI summary', alerts: 'Alert timeline', alert_stats: 'Alert analytics',
  equipment_status: 'Equipment status', work_orders: 'Work orders', compliance: 'Regulatory compliance',
  exceedances: 'Exceedances', kpi_compliance: 'Compliance KPIs', benchmark: 'Asset benchmarking',
};
export const ROLE_LABELS: Record<string, string> = {
  viewer: 'Viewer', operator: 'Operator', technician: 'Technician', engineer: 'Engineer',
  data_scientist: 'Data scientist', admin: 'Admin', super_admin: 'Super admin',
};
export const MODEL_LABELS: Record<string, string> = {
  pump_failure: 'Pump failure prediction', demand_forecast: 'Water demand forecast', anomaly_detection: 'Anomaly detection',
  chlorine_decay: 'Chlorine decay', energy_optimization: 'Energy optimization',
};
