import { useCallback, useRef, useState } from 'react';
import API from '../api.js';

const CACHE_MS = 15 * 60 * 1000;

// Session-local summaries are shared by Configure and Preview. Actual provider
// payloads remain in the backend cache and are reused by regex checks/imports.
export default function useLiveCategoryContent(playlist) {
  const [summaries, setSummaries] = useState({});
  const cache = useRef(new Map());
  const pending = useRef(new Map());
  const prefix = `${playlist.id}:${playlist.account_type}:${playlist.updated_at || ''}`;

  const remember = useCallback(
    (groupId, response) => {
      if (!Number.isFinite(response?.count)) return null;
      const key = `${prefix}:${groupId}`;
      const summary = {
        count: response.count,
        source: response.content_source || 'imported',
        checkedAt: Date.now(),
        loading: false,
        error: null,
      };
      cache.current.set(key, summary);
      setSummaries((current) => ({ ...current, [key]: summary }));
      return summary;
    },
    [prefix]
  );

  const ensure = useCallback(
    (groupId, force = false) => {
      const key = `${prefix}:${groupId}`;
      const saved = cache.current.get(key);
      if (!force && saved && Date.now() - saved.checkedAt < CACHE_MS) {
        return Promise.resolve(saved);
      }
      if (pending.current.has(key)) return pending.current.get(key);
      setSummaries((current) => ({
        ...current,
        [key]: { ...current[key], loading: true, error: null },
      }));
      const request = Promise.resolve().then(async () => {
        try {
          let response = await API.getM3UGroupContent(
            playlist.id,
            'live',
            groupId,
            1,
            50,
            ''
          );
          if (
            playlist.account_type === 'XC' &&
            response.count === 0 &&
            response.can_load_provider &&
            response.content_source !== 'provider'
          ) {
            response = await API.loadM3UGroupContent(
              playlist.id,
              'live',
              groupId
            );
          }
          return remember(groupId, response);
        } catch (error) {
          setSummaries((current) => ({
            ...current,
            [key]: {
              ...current[key],
              loading: false,
              error: 'Could not load category content. Retry to try again.',
            },
          }));
          throw error;
        } finally {
          pending.current.delete(key);
        }
      });
      pending.current.set(key, request);
      return request;
    },
    [playlist.id, playlist.account_type, prefix, remember]
  );

  return {
    summaries,
    keyFor: (groupId) => `${prefix}:${groupId}`,
    ensure,
    remember,
  };
}
