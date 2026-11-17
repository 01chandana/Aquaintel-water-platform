import { lazy, type ReactNode } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { RequireAuth, RequirePermission } from '@/features/auth/RequireAuth';
import { ForbiddenPage, NotFoundPage } from '@/pages/StatusPages';

// Route-based code splitting with React.lazy + Suspense (Ch. 8.10)
const LoginPage = lazy(() => import('@/features/auth/LoginPage'));
const ProfilePage = lazy(() => import('@/features/auth/ProfilePage'));
const ForgotPasswordPage = lazy(() => import('@/features/auth/PasswordPages').then((m) => ({ default: m.ForgotPasswordPage })));
const ResetPasswordPage = lazy(() => import('@/features/auth/PasswordPages').then((m) => ({ default: m.ResetPasswordPage })));
const DashboardPage = lazy(() => import('@/features/dashboard/DashboardPage'));
const DashboardListPage = lazy(() => import('@/features/dashboard/CustomDashboards').then((m) => ({ default: m.DashboardListPage })));
const DashboardBuilderPage = lazy(() => import('@/features/dashboard/CustomDashboards').then((m) => ({ default: m.DashboardBuilderPage })));
const AssetsPage = lazy(() => import('@/features/assets/AssetsPage'));
const AssetDetailPage = lazy(() => import('@/features/assets/AssetDetailPage'));
const AssetMapPage = lazy(() => import('@/features/assets/AssetMapPage'));
const LiveTelemetryPage = lazy(() => import('@/features/telemetry/LiveTelemetryPage'));
const AlertCenterPage = lazy(() => import('@/features/alerts/AlertCenterPage'));
const AlertDetailPage = lazy(() => import('@/features/alerts/AlertDetailPage'));
const RuleManagerPage = lazy(() => import('@/features/alerts/RuleManagerPage'));
const KpiExplorerPage = lazy(() => import('@/features/analytics/KpiExplorerPage'));
const KpiDetailPage = lazy(() => import('@/features/analytics/KpiDetailPage'));
const TrendAnalysisPage = lazy(() => import('@/features/analytics/TrendAnalysisPage'));
const ReportsPage = lazy(() => import('@/features/reports/ReportsPage'));
const ReportBuilderPage = lazy(() => import('@/features/reports/ReportBuilderPage'));
const CompliancePage = lazy(() => import('@/features/reports/CompliancePage'));
const WorkOrdersPage = lazy(() => import('@/features/maintenance/WorkOrdersPage'));
const MlModelsPage = lazy(() => import('@/features/ml/MlModelsPage'));
const OptimizationPage = lazy(() => import('@/features/optimization/OptimizationPage'));
const UsersPage = lazy(() => import('@/features/admin/UsersPage'));
const SystemPage = lazy(() => import('@/features/admin/SystemPage'));
const ConfigPage = lazy(() => import('@/features/admin/ConfigPage'));
const AuditLogPage = lazy(() => import('@/features/admin/AuditLogPage'));
const ApiKeysPage = lazy(() => import('@/features/admin/ApiKeysPage'));

const guard = (permission: string, el: ReactNode) => <RequirePermission permission={permission}>{el}</RequirePermission>;

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/forgot-password', element: <ForgotPasswordPage /> },
  { path: '/reset-password', element: <ResetPasswordPage /> },
  {
    path: '/',
    element: <RequireAuth><AppShell /></RequireAuth>,
    children: [
      { index: true, element: <Navigate to="/dashboard/executive" replace /> },
      { path: 'dashboard/:view', element: guard('kpis:read', <DashboardPage />) },
      { path: 'dashboards', element: <DashboardListPage /> },
      { path: 'dashboards/:id', element: <DashboardBuilderPage /> },
      { path: 'assets', element: guard('assets:read', <AssetsPage />) },
      { path: 'assets/map', element: guard('assets:read', <AssetMapPage />) },
      { path: 'assets/:id', element: guard('assets:read', <AssetDetailPage />) },
      { path: 'telemetry', element: guard('telemetry:read', <LiveTelemetryPage />) },
      { path: 'alerts', element: guard('alerts:read', <AlertCenterPage />) },
      { path: 'alerts/rules', element: guard('alerts:rules', <RuleManagerPage />) },
      { path: 'alerts/:id', element: guard('alerts:read', <AlertDetailPage />) },
      { path: 'analytics/kpis', element: guard('kpis:read', <KpiExplorerPage />) },
      { path: 'analytics/kpis/:id', element: guard('kpis:read', <KpiDetailPage />) },
      { path: 'analytics/trends', element: guard('telemetry:read', <TrendAnalysisPage />) },
      { path: 'reports', element: guard('reports:read', <ReportsPage />) },
      { path: 'reports/builder', element: guard('reports:generate', <ReportBuilderPage />) },
      { path: 'compliance', element: guard('compliance:read', <CompliancePage />) },
      { path: 'work-orders', element: guard('work_orders:read', <WorkOrdersPage />) },
      { path: 'ml', element: guard('ml:read', <MlModelsPage />) },
      { path: 'optimization', element: guard('optimization:run', <OptimizationPage />) },
      { path: 'admin/users', element: guard('users:manage', <UsersPage />) },
      { path: 'admin/system', element: guard('admin:read', <SystemPage />) },
      { path: 'admin/config', element: guard('system:config', <ConfigPage />) },
      { path: 'admin/audit', element: guard('audit:read', <AuditLogPage />) },
      { path: 'admin/api-keys', element: guard('api_keys:manage', <ApiKeysPage />) },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'forbidden', element: <ForbiddenPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]);
