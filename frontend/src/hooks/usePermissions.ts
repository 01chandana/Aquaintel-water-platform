import { useAppSelector } from '@/store';

/** Permission checks mirror the backend RBAC matrix (Table 17.1); the server remains the authority. */
export function usePermissions() {
  const user = useAppSelector((s) => s.auth.user);
  const perms = new Set(user?.permissions ?? []);
  return {
    user,
    role: user?.role,
    can: (...required: string[]) => required.every((p) => perms.has(p)),
  };
}
