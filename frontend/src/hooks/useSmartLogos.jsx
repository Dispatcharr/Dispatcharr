import { useState, useEffect, useCallback, useMemo } from 'react';
import useLogosStore from '../store/logos';

/**
 * Hook for components that need to display all logos (like logo selection popovers)
 * Loads logos on-demand when the component is opened
 */
export const useLogoSelection = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);

  const logos = useLogosStore((s) => s.logos);
  const fetchLogos = useLogosStore((s) => s.fetchLogos); // Check if we have a reasonable number of logos loaded
  const hasEnoughLogos = Object.keys(logos).length > 0;

  const ensureLogosLoaded = useCallback(async () => {
    if (isLoading || (hasEnoughLogos && isInitialized)) {
      return;
    }

    setIsLoading(true);
    try {
      await fetchLogos();
      setIsInitialized(true);
    } catch (error) {
      console.error('Failed to load logos for selection:', error);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, hasEnoughLogos, isInitialized, fetchLogos]);

  return {
    logos,
    isLoading,
    ensureLogosLoaded,
    hasLogos: hasEnoughLogos,
  };
};

/**
 * Hook for channel forms that need channel logos
 */
export const useChannelLogoSelection = () => {
  const [isInitialized, setIsInitialized] = useState(false);
  const channelLogos = useLogosStore((s) => s.channelLogos);
  const hasLoadedChannelLogos = useLogosStore((s) => s.hasLoadedChannelLogos);
  const backgroundLoading = useLogosStore((s) => s.backgroundLoading);
  const fetchChannelAssignableLogos = useLogosStore(
    (s) => s.fetchChannelAssignableLogos
  );

  const hasLogos = Object.keys(channelLogos).length > 0;

  const ensureLogosLoaded = useCallback(async () => {
    if (backgroundLoading) {
      return;
    }

    if ((hasLoadedChannelLogos && hasLogos) || isInitialized) {
      return;
    }

    try {
      await fetchChannelAssignableLogos();
      setIsInitialized(true);
    } catch (error) {
      console.error('Failed to load channel logos:', error);
    }
  }, [
    backgroundLoading,
    hasLoadedChannelLogos,
    hasLogos,
    fetchChannelAssignableLogos,
    isInitialized,
  ]);

  return {
    logos: channelLogos,
    isLoading: backgroundLoading,
    ensureLogosLoaded,
    hasLogos,
  };
};

/**
 * Hook for components that need specific logos by IDs
 */
export const useLogosById = (logoIds = []) => {
  const [isLoading, setIsLoading] = useState(false);
  const [loadedIds, setLoadedIds] = useState(new Set());

  const logos = useLogosStore((s) => s.logos);
  const fetchLogosByIds = useLogosStore((s) => s.fetchLogosByIds);

  // Memoize missing IDs calculation to prevent infinite loops
  const missingIds = useMemo(() => {
    return logoIds.filter((id) => id && !logos[id] && !loadedIds.has(id));
  }, [logoIds, logos, loadedIds]);

  // Stringify logoIds to prevent array reference issues
  const logoIdsString = logoIds.join(',');

  useEffect(() => {
    if (missingIds.length > 0 && !isLoading) {
      setIsLoading(true);

      // Track that we're loading these IDs to prevent re-requests
      setLoadedIds((prev) => new Set([...prev, ...missingIds]));

      fetchLogosByIds(missingIds)
        .then(() => setIsLoading(false))
        .catch((error) => {
          console.error('Failed to load logos by IDs:', error);
          // Remove failed IDs from loaded set so they can be retried
          setLoadedIds((prev) => {
            const newSet = new Set(prev);
            missingIds.forEach((id) => newSet.delete(id));
            return newSet;
          });
          setIsLoading(false);
        });
    }
  }, [logoIdsString, missingIds, isLoading, fetchLogosByIds]);

  return {
    logos,
    isLoading,
    missingLogos: missingIds.length,
  };
};
