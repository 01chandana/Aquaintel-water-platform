import { DarkMode, LightMode, Logout, Menu as MenuIcon, Notifications } from '@mui/icons-material';
import { AppBar, Box, Button, IconButton, Menu, MenuItem, Select, Toolbar, Tooltip, Typography } from '@mui/material';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAlertsQuery } from '@/api/alertApi';
import { useAssetTreeQuery } from '@/api/assetApi';
import { useLogoutMutation } from '@/api/authApi';
import { baseApi } from '@/api/baseApi';
import { usePolling } from '@/hooks/usePolling';
import { useAppDispatch, useAppSelector } from '@/store';
import { loggedOut } from '@/store/authSlice';
import { siteSelected, toggleSidebar, toggleTheme } from '@/store/uiSlice';
import { tokens } from '@/theme/palette';
import { ROLE_LABELS } from '@/utils/constants';
import { localZoneLabel, timeAgo } from '@/utils/formatDate';
import { Breadcrumbs } from './Breadcrumbs';

/** Top bar: site selector, live-link status, alarm summary (counts by severity) and account menu. */
export function Header() {
  const dispatch = useAppDispatch();
  const nav = useNavigate();
  const { user, refreshToken } = useAppSelector((s) => s.auth);
  const { themeMode, siteId, wsStatus, lastTelemetryAt } = useAppSelector((s) => s.ui);
  const { data: tree } = useAssetTreeQuery();
  const poll = usePolling(20_000, 60_000);
  const crit = useAlertsQuery({ open_only: true, severity: 'critical', per_page: 1 }, { pollingInterval: poll });
  const major = useAlertsQuery({ open_only: true, severity: 'major', per_page: 1 }, { pollingInterval: poll });
  const [logout] = useLogoutMutation();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const nCrit = crit.data?.meta.total ?? 0;
  const nMajor = major.data?.meta.total ?? 0;
  // an alarm summary that failed to load must never read as "0 critical": say it is unknown instead
  const countsUnknown = crit.isError || major.isError;
  const link = { open: 'Live', connecting: 'Connecting', closed: 'Offline' }[wsStatus];
  const zone = localZoneLabel();

  const signOut = async () => {
    await logout(refreshToken).unwrap().catch(() => undefined);
    dispatch(loggedOut());
    dispatch(baseApi.util.resetApiState());
    nav('/login');
  };

  return (
    <AppBar position="sticky" color="inherit">
      <Toolbar variant="dense" sx={{ gap: 1.5, minHeight: 56 }}>
        <IconButton edge="start" aria-label="Toggle navigation" onClick={() => dispatch(toggleSidebar())}><MenuIcon /></IconButton>
        <Box sx={{ flex: 1, minWidth: 0, display: { xs: 'none', sm: 'block' } }}><Breadcrumbs /></Box>
        <Select size="small" value={siteId ?? ''} displayEmpty onChange={(e) => dispatch(siteSelected(e.target.value || null))}
          inputProps={{ 'aria-label': 'Site' }} sx={{ minWidth: 190, fontSize: 13 }}>
          <MenuItem value="">All sites</MenuItem>
          {(tree ?? []).map((s) => <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>)}
        </Select>
        <Tooltip title={lastTelemetryAt ? `Last telemetry ${timeAgo(lastTelemetryAt)}` : 'No live telemetry received yet'}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, color: 'text.secondary', fontSize: 12 }} aria-label={`Real-time link: ${link}`}>
            <Box sx={{ width: 7, height: 7, borderRadius: '50%', bgcolor: wsStatus === 'open' ? tokens.brand : wsStatus === 'connecting' ? tokens.alarm.minor : tokens.alarm.critical }} />
            {link}
          </Box>
        </Tooltip>
        <Tooltip title="Times on every screen are shown in this time zone">
          <Box component="span" sx={{ color: 'text.secondary', fontSize: 12, display: { xs: 'none', md: 'inline' } }}>
            {zone}
          </Box>
        </Tooltip>
        <Button size="small" color="inherit" onClick={() => nav('/alerts?open_only=true')} startIcon={<Notifications fontSize="small" />}
          aria-label={countsUnknown ? 'Alert counts unavailable' : `${nCrit} critical and ${nMajor} major open alerts`}
          sx={{ color: countsUnknown ? tokens.alarm.minor : nCrit ? tokens.alarm.critical : nMajor ? tokens.alarm.major : 'text.secondary', fontWeight: 600 }}>
          {countsUnknown ? 'Alert counts unavailable' : `${nCrit} critical · ${nMajor} major`}
        </Button>
        <IconButton aria-label="Toggle colour theme" onClick={() => dispatch(toggleTheme())}>
          {themeMode === 'dark' ? <LightMode fontSize="small" /> : <DarkMode fontSize="small" />}
        </IconButton>
        <Button color="inherit" onClick={(e) => setAnchor(e.currentTarget)} sx={{ textAlign: 'left', lineHeight: 1.2 }} aria-haspopup="menu">
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{user?.display_name}</Typography>
            <Typography variant="caption" color="text.secondary">{ROLE_LABELS[user?.role ?? ''] ?? user?.role}</Typography>
          </Box>
        </Button>
        <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
          <MenuItem onClick={() => { setAnchor(null); nav('/profile'); }}>Profile & security</MenuItem>
          <MenuItem onClick={signOut}><Logout fontSize="small" sx={{ mr: 1 }} /> Sign out</MenuItem>
        </Menu>
      </Toolbar>
    </AppBar>
  );
}
