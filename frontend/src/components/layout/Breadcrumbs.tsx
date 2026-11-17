import { Breadcrumbs as MuiBreadcrumbs, Link, Typography } from '@mui/material';
import { Link as RouterLink, useLocation } from 'react-router-dom';

const LABELS: Record<string, string> = {
  dashboard: 'Dashboards', executive: 'Executive', operations: 'Operations', energy: 'Energy', quality: 'Water quality',
  maintenance: 'Maintenance', assets: 'Assets', map: 'Map', telemetry: 'Live telemetry', alerts: 'Alerts', rules: 'Rule manager',
  analytics: 'Analytics', kpis: 'KPI explorer', trends: 'Trend analysis', reports: 'Reports', builder: 'Report builder',
  compliance: 'Compliance', 'work-orders': 'Work orders', ml: 'ML models', optimization: 'Optimization', admin: 'Admin',
  users: 'Users', system: 'System', config: 'Configuration', audit: 'Audit log', 'api-keys': 'API keys', dashboards: 'My dashboards',
  profile: 'Profile',
};

export function Breadcrumbs() {
  const parts = useLocation().pathname.split('/').filter(Boolean);
  return (
    <MuiBreadcrumbs aria-label="Breadcrumb" sx={{ fontSize: 13 }}>
      {parts.map((p, i) => {
        const to = `/${parts.slice(0, i + 1).join('/')}`;
        const label = LABELS[p] ?? (p.length > 20 ? 'Detail' : p);
        return i === parts.length - 1 || !LABELS[p]
          ? <Typography key={to} color="text.primary" sx={{ fontSize: 13 }}>{label}</Typography>
          : <Link key={to} component={RouterLink} to={to} underline="hover" color="inherit">{label}</Link>;
      })}
    </MuiBreadcrumbs>
  );
}
