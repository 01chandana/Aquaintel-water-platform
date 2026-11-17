import { useEffect, useRef } from 'react';
import { alertApi } from '@/api/alertApi';
import { useAppDispatch, useAppSelector } from '@/store';
import { liveAlertReceived, telemetryTick, wsStatusChanged } from '@/store/uiSlice';
import type { LatestValue } from '@/types/models';

type Listener = (points: LatestValue[]) => void;
const telemetryListeners = new Set<Listener>();

/** Subscribe a component to live telemetry pushed over the dashboard WebSocket. */
export function onTelemetry(listener: Listener): () => void {
  telemetryListeners.add(listener);
  return () => telemetryListeners.delete(listener);
}

/**
 * Single app-wide WebSocket (Ch. 8.7): live telemetry push, alert notifications with
 * cache invalidation, exponential-backoff reconnect and screen-reader announcements.
 */
export function useWebSocket(): void {
  const token = useAppSelector((s) => s.auth.accessToken);
  const dispatch = useAppDispatch();
  const retry = useRef(0);

  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    let lastTick = 0;

    const connect = () => {
      dispatch(wsStatusChanged('connecting'));
      const base = import.meta.env.VITE_WS_URL ?? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
      ws = new WebSocket(`${base}?token=${encodeURIComponent(token)}`);
      ws.onopen = () => {
        retry.current = 0;
        dispatch(wsStatusChanged('open'));
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as { type: string; data: unknown };
        if (msg.type === 'telemetry') {
          const pts = msg.data as LatestValue[];
          telemetryListeners.forEach((l) => l(pts));
          if (Date.now() - lastTick > 2000) {
            lastTick = Date.now();
            dispatch(telemetryTick(new Date().toISOString()));
          }
        } else if (msg.type === 'alert' || msg.type === 'alert_update') {
          const a = msg.data as { alert_id: string; title?: string; severity: string; status: string; asset_id?: string | null };
          if (msg.type === 'alert') {
            dispatch(liveAlertReceived({ alert_id: a.alert_id, title: a.title ?? '', severity: a.severity, status: a.status, asset_id: a.asset_id ?? null }));
            announce(`New ${a.severity} alert: ${a.title}`);
          }
          dispatch(alertApi.util.invalidateTags(['Alert', 'AssetTree']));
        }
      };
      ws.onclose = (ev) => {
        dispatch(wsStatusChanged('closed'));
        if (closed || ev.code === 4401) return;
        const delay = Math.min(30_000, 1000 * 2 ** retry.current++);
        timer = setTimeout(connect, delay);
      };
    };
    connect();
    const ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ action: 'ping' })), 25_000);
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(ping);
      ws?.close();
    };
  }, [token, dispatch]);
}

function announce(text: string): void {
  const region = document.getElementById('live-region');
  if (region) region.textContent = text; // ARIA live region (Ch. 8.9 screen reader announcements)
}
