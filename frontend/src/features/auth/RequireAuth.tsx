import { LinearProgress } from '@mui/material';
import { useEffect, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useMeQuery } from '@/api/authApi';
import { useAppDispatch, useAppSelector } from '@/store';
import { userLoaded } from '@/store/authSlice';

/** Protected route guard (roadmap week 3). Loads the profile + permissions once per session. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAppSelector((s) => s.auth.accessToken);
  const storedUser = useAppSelector((s) => s.auth.user);
  const location = useLocation();
  const dispatch = useAppDispatch();
  const { data, isLoading } = useMeQuery(undefined, { skip: !token });
  useEffect(() => {
    if (data) dispatch(userLoaded(data));
  }, [data, dispatch]);
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  // Wait until the profile (with permissions) is in the store so permission guards never see a stale/empty user.
  if ((isLoading && !data) || !storedUser || (data && storedUser.id !== data.id)) return <LinearProgress aria-label="Loading profile" />;
  return <>{children}</>;
}

export function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const perms = useAppSelector((s) => s.auth.user?.permissions ?? []);
  if (!perms.includes(permission)) return <Navigate to="/forbidden" replace />;
  return <>{children}</>;
}
