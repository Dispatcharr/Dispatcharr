import { useEffect, useState } from 'react';
import API from '../api';

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
      const maxRetries = 5;
      const deadlineMs = 3 * 60 * 1000;
      const startTime = Date.now();
      let delay = 3000;

      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        if (cancelled || Date.now() - startTime > deadlineMs) break;

        try {
          const program = await API.getCurrentProgramForEpg(epgDataId);
          if (cancelled) return;

          if (program && program.parsing && attempt < maxRetries) {
            await new Promise((resolve) => setTimeout(resolve, delay));
            delay = Math.min(delay * 1.5, 15000);
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
            await new Promise((resolve) => setTimeout(resolve, delay));
            delay = Math.min(delay * 1.5, 15000);
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
