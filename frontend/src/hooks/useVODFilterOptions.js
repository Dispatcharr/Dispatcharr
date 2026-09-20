import { useEffect, useState } from 'react';
import API from '../api';

const EMPTY_OPTIONS = Object.freeze({
  audio_languages: [],
  subtitle_languages: [],
  resolutions: [],
  container_extensions: [],
  video_features: [],
});

const useVODFilterOptions = ({
  enabled = true,
  type = 'all',
  m3uAccount = '',
  category = '',
} = {}) => {
  const [options, setOptions] = useState(EMPTY_OPTIONS);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setOptions(EMPTY_OPTIONS);
      setLoading(false);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    API.getVODFilterOptions({
      type,
      m3u_account: m3uAccount,
      category,
    })
      .then((response) => {
        if (cancelled) return;
        setOptions({
          ...EMPTY_OPTIONS,
          ...(response || {}),
        });
      })
      .catch(() => {
        if (!cancelled) setOptions(EMPTY_OPTIONS);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [category, enabled, m3uAccount, type]);

  return { options, loading };
};

export default useVODFilterOptions;
