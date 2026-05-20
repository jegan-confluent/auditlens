"use client";

import { useEffect, useState } from "react";
import { getSystemStatus, isAbortError } from "../api";
import type { SystemStatus } from "../types";

// Shared 30-s heartbeat for `/system/status`. Multiple consumers on the
// same route (events page banner + pipeline-lag banner) used to spawn
// independent setInterval polls, doubling the request rate against the
// API for the same data. This hook collapses them into a single timer
// driven by a module-level subscriber set: the first useSystemStatus()
// mount starts the interval, the last unmount tears it down.
//
// Behavior contract:
//   - Returns { status, loading, error } — `status` survives transient
//     failures (kept at the last successful value) so the UI doesn't
//     flicker on a single bad poll. `error` carries the latest failure
//     for components that want to react to it.
//   - Same 30 s cadence as the two prior implementations; same data.
//   - Calling the hook multiple times across components is cheap —
//     subscribers share the cached value.

const POLL_INTERVAL_MS = 30_000;

type Listener = () => void;

let _status: SystemStatus | null = null;
let _loading = false;
let _error: Error | null = null;
const _listeners: Set<Listener> = new Set();
let _timer: ReturnType<typeof setInterval> | null = null;
let _currentController: AbortController | null = null;

async function _fetchOnce(): Promise<void> {
  // Abort any in-flight request so a slow response can't clobber a newer
  // one. The next interval tick or unmount creates a fresh controller.
  _currentController?.abort();
  const controller = new AbortController();
  _currentController = controller;
  _loading = true;
  _notify();
  try {
    const fresh = await getSystemStatus(controller.signal);
    if (controller.signal.aborted) return;
    _status = fresh;
    _error = null;
  } catch (err) {
    if (isAbortError(err)) return;
    _error = err instanceof Error ? err : new Error(String(err));
    // Intentionally keep _status at its last successful value — same
    // "silent miss" behavior the events page used to have. Components
    // that want to react to the failure can read `error`.
  } finally {
    if (_currentController === controller) {
      _loading = false;
      _currentController = null;
      _notify();
    }
  }
}

function _notify(): void {
  for (const l of _listeners) l();
}

function _start(): void {
  if (_timer !== null) return;
  // Fire one immediate fetch so the first subscriber doesn't wait 30 s
  // for data.
  void _fetchOnce();
  _timer = setInterval(() => {
    void _fetchOnce();
  }, POLL_INTERVAL_MS);
}

function _stop(): void {
  if (_timer !== null) {
    clearInterval(_timer);
    _timer = null;
  }
  _currentController?.abort();
  _currentController = null;
  // Cache stays around so a remount within the same session sees the
  // last value immediately. The next subscriber will trigger a fresh
  // poll via _start().
}

export interface SystemStatusHandle {
  status: SystemStatus | null;
  loading: boolean;
  error: Error | null;
}

export function useSystemStatus(): SystemStatusHandle {
  // Force re-render on each notify via a tick counter — cheaper than
  // mirroring the three fields into local state.
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener: Listener = () => setTick((c) => c + 1);
    _listeners.add(listener);
    if (_listeners.size === 1) _start();
    return () => {
      _listeners.delete(listener);
      if (_listeners.size === 0) _stop();
    };
  }, []);
  return { status: _status, loading: _loading, error: _error };
}
