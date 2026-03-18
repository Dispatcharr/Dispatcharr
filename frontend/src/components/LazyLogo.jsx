import React, { useState, useEffect, useRef } from 'react';
import { Skeleton } from '@mantine/core';
import useLogosStore from '../store/logos';
import logo from '../images/logo.png'; // Default logo

// Global request queue to batch logo requests
const logoRequestQueue = new Set();
let logoRequestTimer = null;

const LazyLogo = ({
  logoId,
  alt = 'logo',
  style = { maxHeight: 18, maxWidth: 55 },
  fallbackSrc = logo,
  ...props
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const fetchAttempted = useRef(new Set());
  const isMountedRef = useRef(true);

  const logos = useLogosStore((s) => s.logos);
  const fetchLogosByIds = useLogosStore((s) => s.fetchLogosByIds);
  const allowLogoRendering = useLogosStore((s) => s.allowLogoRendering);

  // Determine the logo source
  const logoData = logoId && logos[logoId];
  const logoSrc = logoData?.cache_url || fallbackSrc;

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    // Don't start fetching until logo rendering is allowed
    if (!allowLogoRendering) return;

    // If we have a logoId but no logo data, add it to the batch request queue
    if (
      logoId &&
      !logoData &&
      !isLoading &&
      !hasError &&
      !fetchAttempted.current.has(logoId) &&
      isMountedRef.current
    ) {
      setIsLoading(true);
      fetchAttempted.current.add(logoId);
      logoRequestQueue.add(logoId);

      // Clear existing timer and set new one to batch requests
      if (logoRequestTimer) {
        clearTimeout(logoRequestTimer);
      }

      logoRequestTimer = setTimeout(async () => {
        if (logoRequestQueue.size > 0) {
          const idsToFetch = Array.from(logoRequestQueue);
          logoRequestQueue.clear();

          try {
            await fetchLogosByIds(idsToFetch);
          } catch (error) {
            console.warn(`Failed to load logos:`, error);
            // Mark failed IDs so they can be retried
            idsToFetch.forEach((id) => {
              if (fetchAttempted.current.has(id)) {
                fetchAttempted.current.delete(id);
              }
            });
          }
        }

        // Update loading state for all components
        if (isMountedRef.current) {
          setIsLoading(false);
        }
      }, 100); // Batch requests for 100ms
    }

    // If we now have the logo data, stop loading
    if (logoData && isLoading && isMountedRef.current) {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logoId, fetchLogosByIds, logoData, allowLogoRendering]);

  // Reset error state when logoId changes
  useEffect(() => {
    if (logoId) {
      setHasError(false);
    }
  }, [logoId]);

  // Show skeleton if:
  // 1. Logo rendering is not allowed yet, OR
  // 2. We don't have logo data yet (regardless of loading state)
  if (logoId && (!allowLogoRendering || !logoData)) {
    return (
      <Skeleton
        height={style.maxHeight || 18}
        width={style.maxWidth || 55}
        style={{ ...style, borderRadius: 4 }}
      />
    );
  }

  // Show image (will use fallback if logo fails to load)
  return (
    <img
      src={logoSrc}
      alt={alt}
      style={style}
      onError={(e) => {
        if (!hasError) {
          setHasError(true);
          e.target.src = fallbackSrc;
        }
      }}
      {...props}
    />
  );
};

export default LazyLogo;
