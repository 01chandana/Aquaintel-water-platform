import { ChevronRight, ExpandMore } from '@mui/icons-material';
import { Badge, Box, IconButton, Typography } from '@mui/material';
import { useState } from 'react';
import { StatusDot } from '@/components/common/Chips';
import type { AssetNode } from '@/types/models';

interface Props {
  nodes: AssetNode[];
  selectedId?: string;
  onSelect: (n: AssetNode) => void;
  filter?: string;
}

function matches(n: AssetNode, f: string): boolean {
  return n.name.toLowerCase().includes(f) || n.external_id.includes(f) || n.children.some((c) => matches(c, f));
}

/** Keyboard-navigable hierarchy with rolled-up open-alert counts per node. */
export function AssetTree({ nodes, selectedId, onSelect, filter = '' }: Props) {
  const f = filter.trim().toLowerCase();
  return (
    <Box role="tree" aria-label="Asset hierarchy">
      {nodes.filter((n) => !f || matches(n, f)).map((n) => <TreeNode key={n.id} node={n} depth={0} selectedId={selectedId} onSelect={onSelect} filter={f} />)}
    </Box>
  );
}

function TreeNode({ node, depth, selectedId, onSelect, filter }: { node: AssetNode; depth: number; selectedId?: string; onSelect: (n: AssetNode) => void; filter: string }) {
  const [open, setOpen] = useState(depth < 1 || !!filter);
  const kids = node.children.filter((c) => !filter || matches(c, filter));
  const selected = node.id === selectedId;
  return (
    <Box role="treeitem" aria-expanded={kids.length ? open : undefined} aria-selected={selected}>
      <Box onClick={() => onSelect(node)} tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onSelect(node);
          if (e.key === 'ArrowRight') setOpen(true);
          if (e.key === 'ArrowLeft') setOpen(false);
        }}
        sx={{ display: 'flex', alignItems: 'center', gap: 0.75, pl: depth * 2, pr: 1, py: 0.4, borderRadius: 1, cursor: 'pointer',
          bgcolor: selected ? 'action.selected' : undefined, '&:hover': { bgcolor: 'action.hover' } }}>
        <IconButton size="small" aria-label={open ? 'Collapse' : 'Expand'} sx={{ visibility: kids.length ? 'visible' : 'hidden', p: 0.25 }}
          onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
          {open ? <ExpandMore fontSize="small" /> : <ChevronRight fontSize="small" />}
        </IconButton>
        <StatusDot status={node.open_alerts > 0 ? 'critical' : node.status === 'maintenance' ? 'warning' : 'normal'} />
        <Typography variant="body2" noWrap sx={{ flex: 1 }}>{node.name}</Typography>
        {node.open_alerts > 0 && <Badge badgeContent={node.open_alerts} color="error" sx={{ mr: 1.5 }} />}
      </Box>
      {open && kids.map((c) => <TreeNode key={c.id} node={c} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} filter={filter} />)}
    </Box>
  );
}
