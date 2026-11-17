import { useAppSelector } from '@/store';

/**
 * Polling interval for non-critical data (Ch. 8.7 "RTK Query polling"). While the WebSocket
 * is healthy, polling slows down because pushes keep the view fresh.
 */
export function usePolling(fastMs = 15_000, slowMs = 60_000): number {
  const ws = useAppSelector((s) => s.ui.wsStatus);
  return ws === 'open' ? slowMs : fastMs;
}
