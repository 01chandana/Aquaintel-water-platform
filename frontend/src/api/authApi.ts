import type { Envelope } from '@/types/api';
import type { LoginResult, TokenPair, User } from '@/types/models';
import { baseApi, unwrap } from './baseApi';

export const authApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    login: b.mutation<LoginResult, { email: string; password: string }>({
      query: (body) => ({ url: '/auth/login', method: 'POST', body }),
      transformResponse: unwrap<LoginResult>,
    }),
    verifyMfa: b.mutation<LoginResult, { mfaToken: string; code: string }>({
      query: ({ mfaToken, code }) => ({ url: '/auth/mfa/verify', method: 'POST', body: { code }, headers: { Authorization: `Bearer ${mfaToken}` } }),
      transformResponse: unwrap<LoginResult>,
    }),
    setupMfa: b.mutation<{ secret: string; otpauth_uri: string; backup_codes: string[] }, void>({
      query: () => ({ url: '/auth/mfa/setup', method: 'POST' }),
      transformResponse: (r: Envelope<{ secret: string; otpauth_uri: string; backup_codes: string[] }>) => r.data,
    }),
    confirmMfa: b.mutation<unknown, string>({ query: (code) => ({ url: '/auth/mfa/verify', method: 'POST', body: { code } }), invalidatesTags: ['User'] }),
    logout: b.mutation<unknown, string | null>({ query: (refresh_token) => ({ url: '/auth/logout', method: 'POST', body: { refresh_token } }) }),
    forgotPassword: b.mutation<unknown, string>({ query: (email) => ({ url: '/auth/forgot-password', method: 'POST', body: { email } }) }),
    resetPassword: b.mutation<unknown, { token: string; new_password: string }>({
      query: (body) => ({ url: '/auth/reset-password', method: 'POST', body }),
    }),
    me: b.query<User, void>({ query: () => '/users/me', transformResponse: unwrap<User>, providesTags: ['User'] }),
    updateMe: b.mutation<User, Partial<User> & { current_password?: string; new_password?: string }>({
      query: (body) => ({ url: '/users/me', method: 'PUT', body }),
      transformResponse: unwrap<User>,
      invalidatesTags: ['User'],
    }),
  }),
});

export const {
  useLoginMutation, useVerifyMfaMutation, useSetupMfaMutation, useConfirmMfaMutation, useLogoutMutation,
  useForgotPasswordMutation, useResetPasswordMutation, useMeQuery, useUpdateMeMutation,
} = authApi;
export type { TokenPair };
