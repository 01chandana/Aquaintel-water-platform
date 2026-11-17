import { Alert as MuiAlert, Box, Button, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useSystemConfigQuery, useUpdateConfigMutation } from '@/api/operationsApi';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { errorMessage, Loading } from '@/components/common/States';
import { formatDateTime } from '@/utils/formatDate';

export default function ConfigPage() {
  const { data } = useSystemConfigQuery();
  const [save, { error, isSuccess }] = useUpdateConfigMutation();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [parseError, setParseError] = useState<string | null>(null);
  if (!data) return <Loading />;
  return (
    <>
      <PageHeader title="Configuration" description="Runtime settings used by the KPI engine, alerting and optimization. Every change is written to the audit log." />
      {(error || parseError) && <MuiAlert severity="error" sx={{ mb: 2 }}>{parseError ?? errorMessage(error)}</MuiAlert>}
      {isSuccess && <MuiAlert severity="success" sx={{ mb: 2 }}>Configuration saved.</MuiAlert>}
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' } }}>
        {data.map((c) => {
          const text = drafts[c.key] ?? JSON.stringify(c.value, null, 2);
          return (
            <Panel key={c.key} title={c.key} subtitle={c.description}>
              <TextField multiline minRows={2} maxRows={10} value={text} disabled={c.readonly} onChange={(e) => setDrafts({ ...drafts, [c.key]: e.target.value })}
                inputProps={{ 'aria-label': c.key, style: { fontFamily: 'monospace', fontSize: 12 } }} />
              <Box sx={{ display: 'flex', alignItems: 'center', mt: 1 }}>
                <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>{c.readonly ? 'Set by environment variables' : c.updated_at ? `Updated ${formatDateTime(c.updated_at)}` : 'Default value'}</Typography>
                {!c.readonly && drafts[c.key] !== undefined && (
                  <Button size="small" variant="contained" onClick={() => {
                    try { setParseError(null); save({ [c.key]: JSON.parse(drafts[c.key]) }); const { [c.key]: _, ...rest } = drafts; void _; setDrafts(rest); }
                    catch { setParseError(`${c.key}: value must be valid JSON`); }
                  }}>Save</Button>
                )}
              </Box>
            </Panel>
          );
        })}
      </Box>
    </>
  );
}
