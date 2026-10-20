import { useCallback, useEffect, useRef, useState } from 'react';

export function useWebSocket(url: string, token: string | null) {
  const [messages, setMessages] = useState<any[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!token) return;
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${window.location.host}${url}`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token }));
    };
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        setMessages((prev) => [...prev.slice(-49), data]);
      } catch {}
    };
    ws.onclose = () => setTimeout(() => wsRef.current?.close(), 3000);

    return () => ws.close();
  }, [url, token]);

  const send = useCallback((payload: any) => {
    wsRef.current?.send(JSON.stringify(payload));
  }, []);

  return { messages, send };
}
