import type { SvgIconComponent } from '@mui/icons-material';

export interface NavItem {
  label: string;
  path: string;
  icon: SvgIconComponent;
  permission?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}
