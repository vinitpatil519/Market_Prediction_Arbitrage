"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";
import type { Snapshot } from "./types";

export type ConnectionState = "connecting" | "live" | "retrying" | "offline";

/**
 * Subscribes to the engine's snapshot stream.
 *
 * The server sends whole snapshots rather than deltas, so a reconnect needs no
 * replay: the next frame is authoritative. Backoff is capped so a backend that
 * comes back after a restart is picked up within a few seconds.
 */
export function useStream() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [state, setState] = useState<ConnectionState>("connecting");
  const [lastFrameAt, setLastFrameAt] = useState<number | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  const connect = useCallback(() => {
    if (closedRef.current) return;
    setState(attemptRef.current === 0 ? "connecting" : "retrying");

    let socket: WebSocket;
    try {
      socket = new WebSocket(WS_URL);
    } catch {
      scheduleReconnect();
      return;
    }
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setState("live");
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "heartbeat") return;
        setSnapshot(payload as Snapshot);
        setLastFrameAt(Date.now());
      } catch {
        // A malformed frame is not worth tearing the socket down for.
      }
    };

    socket.onerror = () => socket.close();
    socket.onclose = () => {
      socketRef.current = null;
      if (!closedRef.current) scheduleReconnect();
    };

    function scheduleReconnect() {
      attemptRef.current += 1;
      setState(attemptRef.current > 6 ? "offline" : "retrying");
      const delay = Math.min(8000, 400 * 2 ** Math.min(attemptRef.current, 4));
      timerRef.current = setTimeout(connect, delay);
    }
  }, []);

  useEffect(() => {
    closedRef.current = false;
    connect();
    return () => {
      closedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  return { snapshot, state, lastFrameAt };
}
