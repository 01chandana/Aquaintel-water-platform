import { WaterDrop } from '@mui/icons-material';
import { Box, Drawer, List, ListItemButton, ListItemIcon, ListItemText, ListSubheader, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material';
import { NavLink, useLocation } from 'react-router-dom';
import { usePermissions } from '@/hooks/usePermissions';
import { useAppDispatch, useAppSelector } from '@/store';
import { toggleSidebar } from '@/store/uiSlice';
import { tokens } from '@/theme/palette';
import { NAV } from './navigation';

export const SIDEBAR_WIDTH = 236;
export const SIDEBAR_MINI = 60;

/** Collapsible sidebar with mini variant; temporary drawer on narrow screens (Ch. 8.8). */
export function Sidebar() {
  const collapsed = useAppSelector((s) => s.ui.sidebarCollapsed);
  const dispatch = useAppDispatch();
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down('md'));
  const { can } = usePermissions();
  const { pathname } = useLocation();
  const mini = collapsed && !mobile;
  const width = mini ? SIDEBAR_MINI : SIDEBAR_WIDTH;

  const content = (
    <Box component="nav" aria-label="Main navigation" sx={{ width, overflowX: 'hidden', transition: 'width 150ms' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25, px: 2, height: 56 }}>
        <WaterDrop sx={{ color: tokens.brand }} />
        {!mini && <Typography variant="subtitle1" sx={{ fontWeight: 700, letterSpacing: '-0.01em' }}>AquaIntel</Typography>}
      </Box>
      {NAV.map((group) => {
        const items = group.items.filter((i) => !i.permission || can(i.permission));
        if (!items.length) return null;
        return (
          <List key={group.label} dense subheader={!mini ? <ListSubheader sx={{ bgcolor: 'transparent', lineHeight: '30px', fontSize: 12 }}>{group.label}</ListSubheader> : undefined}>
            {items.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.path || (item.path !== '/alerts' && item.path !== '/assets' && pathname.startsWith(`${item.path}/`));
              const btn = (
                <ListItemButton component={NavLink} to={item.path} selected={active} aria-current={active ? 'page' : undefined}
                  onClick={() => mobile && dispatch(toggleSidebar())}
                  sx={{ mx: 1, borderRadius: 1, minHeight: 34, '&.Mui-selected': { bgcolor: 'action.selected', borderLeft: `2px solid ${tokens.brand}` } }}>
                  <ListItemIcon sx={{ minWidth: 34 }}><Icon fontSize="small" /></ListItemIcon>
                  {!mini && <ListItemText primary={item.label} primaryTypographyProps={{ variant: 'body2' }} />}
                </ListItemButton>
              );
              return mini ? <Tooltip key={item.path} title={item.label} placement="right">{btn}</Tooltip> : <Box key={item.path}>{btn}</Box>;
            })}
          </List>
        );
      })}
    </Box>
  );

  return mobile ? (
    <Drawer variant="temporary" open={!collapsed} onClose={() => dispatch(toggleSidebar())} ModalProps={{ keepMounted: true }}>{content}</Drawer>
  ) : (
    <Drawer variant="permanent" sx={{ width, flexShrink: 0, '& .MuiDrawer-paper': { width, transition: 'width 150ms' } }}>{content}</Drawer>
  );
}
