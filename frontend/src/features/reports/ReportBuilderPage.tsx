import { DragIndicator } from '@mui/icons-material';
import { Box, Button, Checkbox, Grid, List, ListItem, ListItemIcon, ListItemText, MenuItem, TextField, Typography } from '@mui/material';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useGenerateReportMutation, usePreviewReportMutation, useSectionsQuery } from '@/api/reportApi';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, Loading } from '@/components/common/States';
import { REPORT_TYPES, SECTION_LABELS } from '@/utils/constants';

/** Drag-and-drop report creation with live preview (Ch. 8.5.4 Report Builder). */
export default function ReportBuilderPage() {
  const nav = useNavigate();
  const { data: sections } = useSectionsQuery();
  const [type, setType] = useState('custom');
  const [name, setName] = useState('Weekly operations pack');
  const [order, setOrder] = useState<string[]>([]);
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [drag, setDrag] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [preview, previewState] = usePreviewReportMutation();
  const [generate] = useGenerateReportMutation();

  useEffect(() => {
    if (!sections) return;
    const defaults = sections.types[type] ?? [];
    setOrder([...defaults, ...sections.all.filter((s) => !defaults.includes(s))]);
    setEnabled(new Set(defaults));
  }, [sections, type]);

  const chosen = order.filter((s) => enabled.has(s));
  const req = { report_type: type, name, sections: chosen, format: 'html' as const, start: new Date(Date.now() - days * 86400_000).toISOString(), end: new Date().toISOString() };
  const move = (target: string) => {
    if (!drag || drag === target) return;
    const next = order.filter((x) => x !== drag);
    next.splice(next.indexOf(target), 0, drag);
    setOrder(next);
  };
  if (!sections) return <Loading />;
  return (
    <>
      <PageHeader title="Report builder" description="Choose sections, drag them into order, preview, then generate as PDF or Excel." />
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Panel title="Content">
            <Box sx={{ display: 'grid', gap: 1.5, mb: 2 }}>
              <TextField size="small" label="Title" value={name} onChange={(e) => setName(e.target.value)} />
              <TextField size="small" select label="Start from" value={type} onChange={(e) => setType(e.target.value)}>
                {Object.entries(REPORT_TYPES).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
              </TextField>
              <TextField size="small" select label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {[1, 7, 30].map((d) => <MenuItem key={d} value={d}>Last {d} day{d > 1 ? 's' : ''}</MenuItem>)}
              </TextField>
            </Box>
            <Typography variant="subtitle2">Sections</Typography>
            <List dense>
              {order.map((s) => (
                <ListItem key={s} draggable onDragStart={() => setDrag(s)} onDragOver={(e) => { e.preventDefault(); move(s); }} onDragEnd={() => setDrag(null)}
                  sx={{ border: 1, borderColor: 'divider', borderRadius: 1, mb: 0.5, opacity: drag === s ? 0.5 : 1, cursor: 'grab' }}
                  secondaryAction={<Checkbox edge="end" checked={enabled.has(s)} inputProps={{ 'aria-label': `Include ${SECTION_LABELS[s] ?? s}` }}
                    onChange={() => { const n = new Set(enabled); if (n.has(s)) n.delete(s); else n.add(s); setEnabled(n); }} />}>
                  <ListItemIcon sx={{ minWidth: 30 }}><DragIndicator fontSize="small" /></ListItemIcon>
                  <ListItemText primary={SECTION_LABELS[s] ?? s} />
                </ListItem>
              ))}
            </List>
            <Box sx={{ display: 'flex', gap: 1, mt: 1, flexWrap: 'wrap' }}>
              <Button variant="outlined" disabled={!chosen.length || previewState.isLoading} onClick={() => preview(req)}>Preview</Button>
              <Button variant="contained" disabled={!chosen.length} onClick={async () => { await generate({ ...req, format: 'pdf' }); nav('/reports'); }}>Generate PDF</Button>
              <Button disabled={!chosen.length} onClick={async () => { await generate({ ...req, format: 'excel' }); nav('/reports'); }}>Generate Excel</Button>
            </Box>
          </Panel>
        </Grid>
        <Grid item xs={12} md={8}>
          <Panel title="Preview">
            {previewState.isLoading ? <Loading label="Building preview" /> : previewState.data ? (
              <Box component="iframe" title="Report preview" srcDoc={previewState.data} sandbox="" sx={{ width: '100%', height: '72vh', border: 0, bgcolor: '#fff', borderRadius: 1 }} />
            ) : <EmptyState title="No preview yet" hint="Pick sections on the left, then select Preview." />}
          </Panel>
        </Grid>
      </Grid>
    </>
  );
}
