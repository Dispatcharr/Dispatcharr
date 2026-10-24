import { useEffect, useState } from 'react';
import API from '../api.js';
import usePlaylistsStore from '../store/playlists';

export const EMPTY_CATEGORY_PREVIEW_HINT =
  'No imported entries. Enable this category, save and run a refresh before previewing.';

const useCategoryPreviewAvailability = (accountId, isOpen) => {
  const [availability, setAvailability] = useState(null);
  const [hint, setHint] = useState('Checking imported content…');
  const timings = usePlaylistsStore(
    (s) =>
      s.playlists.find((p) => p.id === accountId)?.custom_properties
        ?.refresh_timings
  );

  useEffect(() => {
    if (!isOpen || !accountId) return undefined;
    let cancelled = false;
    setAvailability(null);
    setHint('Checking imported content…');
    API.getM3UGroupContentAvailability(accountId)
      .then((result) => {
        if (cancelled) return;
        setAvailability(
          Object.fromEntries(
            ['live', 'movie', 'series'].map((scope) => [
              scope,
              new Set(result[scope]),
            ])
          )
        );
        setHint(EMPTY_CATEGORY_PREVIEW_HINT);
      })
      .catch(() => {
        if (!cancelled)
          setHint(
            'Imported content could not be checked. Reopen Categories to retry.'
          );
      });
    return () => {
      cancelled = true;
    };
  }, [
    accountId,
    isOpen,
    timings?.live_completed_at,
    timings?.vod_completed_at,
  ]);

  return { availability, hint };
};

export default useCategoryPreviewAvailability;
