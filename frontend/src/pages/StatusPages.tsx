import { Box, Button, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';

function StatusPage({ code, title, body }: { code: string; title: string; body: string }) {
  return (
    <Box sx={{ py: 10, textAlign: 'center' }}>
      <Typography variant="body2" color="text.secondary">{code}</Typography>
      <Typography variant="h1" sx={{ mt: 1 }}>{title}</Typography>
      <Typography color="text.secondary" sx={{ mt: 1, mb: 3 }}>{body}</Typography>
      <Button component={RouterLink} to="/dashboard/executive" variant="outlined">Go to overview</Button>
    </Box>
  );
}

export const NotFoundPage = () => <StatusPage code="404" title="Page not found" body="Check the address, or use the navigation to find what you need." />;
export const ForbiddenPage = () => <StatusPage code="403" title="You don't have access to this page" body="Ask an administrator to grant your role the required permission." />;
