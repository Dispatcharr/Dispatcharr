import { useEffect, useState } from 'react';
import API from '../api';
import { computeBackoffDelay } from '../utils/backoff';

const getCurrentProgramForEpg = (epgId) => {
  return API.getCurrentProgramForEpg(epgId);
};

const EPG_PREVIEW_BACKOFF = {
  initialMs: 3000,
  maxMs: 15000,
  factor: 1.5,
  jitter: 0,
};

export const useEpgPreview = (epgDataId) => {
  const [currentProgram, setCurrentProgram] = useState(null);
  const [isLoadingProgram, setIsLoadingProgram] = useState(false);
  const [hasFetchedProgram, setHasFetchedProgram] = useState(false);

  useEffect(() => {
    if (!epgDataId || epgDataId === '0' || epgDataId === '') {
      setCurrentProgram(null);
      setIsLoadingProgram(false);
      setHasFetchedProgram(false);
      return;
    }

    let cancelled = false;
    setIsLoadingProgram(true);
    setHasFetchedProgram(false);

    const fetchWithRetry = async () => {
      const maxRetries = 20;
      const deadlineMs = 3 * 60 * 1000;
      const startTime = Date.now();

      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        if (cancelled || Date.now() - startTime > deadlineMs) break;

        try {
          const program = await getCurrentProgramForEpg(epgDataId);
          if (cancelled) return;

          if (program && program.parsing && attempt < maxRetries) {
            const delay = computeBackoffDelay(attempt, EPG_PREVIEW_BACKOFF);
            await new Promise((resolve) => setTimeout(resolve, delay));
            continue;
          }

          if (!cancelled) {
            setCurrentProgram(program && !program.parsing ? program : null);
            setIsLoadingProgram(false);
            setHasFetchedProgram(true);
          }
          return;
        } catch (error) {
          if (!cancelled) {
            console.error('Failed to fetch current program:', error);
          }
          if (attempt < maxRetries) {
            const delay = computeBackoffDelay(attempt, EPG_PREVIEW_BACKOFF);
            await new Promise((resolve) => setTimeout(resolve, delay));
          }
        }
      }

      if (!cancelled) {
        setCurrentProgram(null);
        setIsLoadingProgram(false);
        setHasFetchedProgram(true);
      }
    };

    fetchWithRetry();

    return () => {
      cancelled = true;
    };
  }, [epgDataId]);

  return { currentProgram, isLoadingProgram, hasFetchedProgram };
};
