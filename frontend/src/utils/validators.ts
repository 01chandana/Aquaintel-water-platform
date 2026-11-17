import { z } from 'zod';

/** Zod schemas shared by forms (Ch. 8.2 React Hook Form + Zod). Mirror backend Pydantic rules. */
export const passwordSchema = z
  .string()
  .min(10, 'Use at least 10 characters')
  .regex(/[A-Z]/, 'Include an uppercase letter')
  .regex(/\d/, 'Include a digit');

export const loginSchema = z.object({
  email: z.email('Enter a valid email address'),
  password: z.string().min(1, 'Enter your password'),
});

export const ruleSchema = z
  .object({
    name: z.string().min(3, 'Name needs at least 3 characters'),
    rule_type: z.enum(['threshold', 'rate', 'deviation']),
    severity: z.enum(['critical', 'major', 'minor', 'warning', 'info']),
    tag_id: z.string().uuid('Choose a tag'),
    operator: z.string(),
    value: z.coerce.number().optional(),
    low: z.coerce.number().optional(),
    high: z.coerce.number().optional(),
    sustained_seconds: z.coerce.number().min(0).default(0),
    hysteresis: z.coerce.number().min(0).default(0),
    window_seconds: z.coerce.number().min(10).default(300),
    max_change_pct: z.coerce.number().optional(),
    direction: z.enum(['rise', 'drop', 'any']).default('any'),
    n_sigma: z.coerce.number().positive().default(3),
    cooldown_minutes: z.coerce.number().min(0).max(1440).default(15),
  })
  .superRefine((v, ctx) => {
    if (v.rule_type === 'threshold') {
      const range = v.operator === 'outside_range' || v.operator === 'inside_range';
      if (range && (v.low === undefined || v.high === undefined)) ctx.addIssue({ code: 'custom', path: ['low'], message: 'Range needs low and high' });
      if (!range && v.value === undefined) ctx.addIssue({ code: 'custom', path: ['value'], message: 'Enter a threshold' });
    }
    if (v.rule_type === 'rate' && v.max_change_pct === undefined) ctx.addIssue({ code: 'custom', path: ['max_change_pct'], message: 'Enter the change limit' });
  });

export type RuleForm = z.output<typeof ruleSchema>;
/** What the form fields hold before coercion (numbers arrive as strings from <input>) */
export type RuleFormInput = z.input<typeof ruleSchema>;

export const userSchema = z.object({
  email: z.email('Enter a valid email address'),
  display_name: z.string().min(1, 'Enter a name'),
  password: passwordSchema,
  role: z.enum(['viewer', 'operator', 'technician', 'engineer', 'data_scientist', 'admin', 'super_admin']),
  asset_scopes: z.string().optional(),
});

export const completeWorkOrderSchema = z.object({
  resolution_notes: z.string().min(3, 'Describe what was done'),
  labor_hours: z.coerce.number().min(0),
  cost: z.coerce.number().min(0).optional(),
  failure_code: z.string().optional(),
});
