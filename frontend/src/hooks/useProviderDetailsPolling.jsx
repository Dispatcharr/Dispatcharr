import { useCallback, useEffect, useRef, useState } from 'react';

export default function useProviderDetailsPolling({
  opened,
  id,
  relationId,
  details,
  load,
  onResult,
}) {
  const attempts = useRef(0);
  const generation = useRef(0);
  const [retrying, setRetrying] = useState(false);
  useEffect(() => {
    attempts.current = 0;
    generation.current += 1;
    setRetrying(false);
    return () => {
      generation.current += 1;
    };
  }, [opened, id, relationId]);
  useEffect(() => {
    if (
      !opened ||
      !id ||
      details?.refresh_status !== 'pending' ||
      attempts.current >= 40
    )
      return undefined;
    let cancelled = false;
    const timer = setTimeout(async () => {
      attempts.current += 1;
      try {
        const value = await load(id, relationId, { background: true });
        if (!cancelled && value)
          onResult(
            value.refresh_status === 'pending' && attempts.current >= 40
              ? { ...value, refresh_status: 'failed' }
              : value
          );
      } catch {
        attempts.current = 40;
        if (!cancelled) onResult({ ...details, refresh_status: 'failed' });
      }
    }, 1500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [opened, id, relationId, details, load, onResult]);
  const retry = useCallback(async () => {
    if (!opened || !id || retrying) return;
    const current = generation.current;
    setRetrying(true);
    attempts.current = 0;
    try {
      const value = await load(id, relationId, {
        background: true,
        forceRefresh: true,
      });
      if (current === generation.current && value) onResult(value);
    } catch {
      // Keep the imported details and the retry action available.
      return;
    } finally {
      if (current === generation.current) setRetrying(false);
    }
  }, [opened, id, relationId, retrying, load, onResult]);
  return { retry, retrying };
}
