import {
  AccountTree, AdminPanelSettings, Analytics, Assessment, Bolt, Build, Dashboard, DashboardCustomize, Engineering,
  FactCheck, History, Key, Map, Memory, Notifications, People, Psychology, Rule, Science, Sensors, Settings, ShowChart, Timeline,
  TrendingUp, WaterDrop,
} from '@mui/icons-material';
import type { NavGroup } from '@/types/navigation';

/** Navigation grouped by job (Ch. 3.3.1 operator / analyst / manager / admin views). */
export const NAV: NavGroup[] = [
  {
    label: 'Operate',
    items: [
      { label: 'Executive overview', path: '/dashboard/executive', icon: Dashboard, permission: 'kpis:read' },
      { label: 'Operations', path: '/dashboard/operations', icon: Sensors, permission: 'telemetry:read' },
      { label: 'Live telemetry', path: '/telemetry', icon: Timeline, permission: 'telemetry:read' },
      { label: 'Alert center', path: '/alerts', icon: Notifications, permission: 'alerts:read' },
      { label: 'Assets', path: '/assets', icon: AccountTree, permission: 'assets:read' },
      { label: 'Asset map', path: '/assets/map', icon: Map, permission: 'assets:read' },
    ],
  },
  {
    label: 'Maintain',
    items: [
      { label: 'Maintenance', path: '/dashboard/maintenance', icon: Engineering, permission: 'kpis:read' },
      { label: 'Work orders', path: '/work-orders', icon: Build, permission: 'work_orders:read' },
      { label: 'Rule manager', path: '/alerts/rules', icon: Rule, permission: 'alerts:rules' },
    ],
  },
  {
    label: 'Analyze',
    items: [
      { label: 'Energy', path: '/dashboard/energy', icon: Bolt, permission: 'kpis:read' },
      { label: 'Water quality', path: '/dashboard/quality', icon: WaterDrop, permission: 'kpis:read' },
      { label: 'KPI explorer', path: '/analytics/kpis', icon: Analytics, permission: 'kpis:read' },
      { label: 'Trend analysis', path: '/analytics/trends', icon: ShowChart, permission: 'telemetry:read' },
      { label: 'Optimization', path: '/optimization', icon: TrendingUp, permission: 'optimization:run' },
      { label: 'ML models', path: '/ml', icon: Psychology, permission: 'ml:read' },
      { label: 'My dashboards', path: '/dashboards', icon: DashboardCustomize, permission: 'dashboards:read' },
    ],
  },
  {
    label: 'Report',
    items: [
      { label: 'Compliance', path: '/compliance', icon: FactCheck, permission: 'compliance:read' },
      { label: 'Reports', path: '/reports', icon: Assessment, permission: 'reports:read' },
      { label: 'Report builder', path: '/reports/builder', icon: Science, permission: 'reports:generate' },
    ],
  },
  {
    label: 'Administer',
    items: [
      { label: 'Users', path: '/admin/users', icon: People, permission: 'users:manage' },
      { label: 'System', path: '/admin/system', icon: Memory, permission: 'admin:read' },
      { label: 'Configuration', path: '/admin/config', icon: Settings, permission: 'system:config' },
      { label: 'Audit log', path: '/admin/audit', icon: History, permission: 'audit:read' },
      { label: 'API keys', path: '/admin/api-keys', icon: Key, permission: 'api_keys:manage' },
    ],
  },
];

export const ADMIN_ICON = AdminPanelSettings;
