import React, { useCallback, useRef } from 'react';
import ChannelsTable from '../components/tables/ChannelsTable';
import StreamsTable from '../components/tables/StreamsTable';
import { Box } from '@mantine/core';
import { Allotment } from 'allotment';
import { USER_LEVELS } from '../constants';
import useAuthStore from '../store/auth';
import useLogosStore from '../store/logos';
import useBrowserStorage from '../hooks/useBrowserStorage';
import ErrorBoundary from '../components/ErrorBoundary';

const PageContent = () => {
  const authUser = useAuthStore((s) => s.user);
  const fetchChannelAssignableLogos = useLogosStore(
    (s) => s.fetchChannelAssignableLogos
  );
  const enableLogoRendering = useLogosStore((s) => s.enableLogoRendering);

  const channelsReady = useRef(false);
  const streamsReady = useRef(false);
  const logosTriggered = useRef(false);

  const [allotmentSizes, setAllotmentSizes] = useBrowserStorage(
    'channels-splitter-sizes',
    [60, 40]
  );

  // Only load logos when BOTH tables are ready
  const tryLoadLogos = useCallback(() => {
    if (
      channelsReady.current &&
      streamsReady.current &&
      !logosTriggered.current
    ) {
      logosTriggered.current = true;
      // Use requestAnimationFrame to defer logo loading until after browser paint
      // This ensures EPG column is fully rendered before logos start loading
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          enableLogoRendering();
          fetchChannelAssignableLogos();
        });
      });
    }
  }, [fetchChannelAssignableLogos, enableLogoRendering]);

  const handleChannelsReady = useCallback(() => {
    channelsReady.current = true;
    tryLoadLogos();
  }, [tryLoadLogos]);

  const handleStreamsReady = useCallback(() => {
    streamsReady.current = true;
    tryLoadLogos();
  }, [tryLoadLogos]);

  const handleSplitChange = (sizes) => {
    setAllotmentSizes(sizes);
  };

  const handleResize = (sizes) => {
    setAllotmentSizes(sizes);
  };

  if (!authUser.id) return <></>;

  if (authUser.user_level <= USER_LEVELS.STANDARD) {
    handleStreamsReady();
    return (
      <Box
        id="channels-container"
        h="100%"
        style={{ minHeight: 0, overflow: 'hidden', padding: 10 }}
      >
        <ChannelsTable onReady={handleChannelsReady} />
      </Box>
    );
  }

  return (
    <Box
      id="channels-container"
      h="100%"
      w="100%"
      display="flex"
      style={{ minHeight: 0, overflowX: 'auto', overflowY: 'hidden' }}
    >
      <Allotment
        defaultSizes={allotmentSizes}
        h={'100%'}
        w={'100%'}
        miw={'625px'}
        className="custom-allotment"
        minSize={100}
        onChange={handleSplitChange}
        onResize={handleResize}
      >
        <Box
          p={10}
          h="100%"
          miw="100px"
          style={{ minHeight: 0, overflowX: 'auto', overflowY: 'hidden' }}
        >
          <Box h="100%" miw="625px" style={{ minHeight: 0 }}>
            <ChannelsTable onReady={handleChannelsReady} />
          </Box>
        </Box>
        <Box
          p={10}
          h="100%"
          miw="100px"
          style={{ minHeight: 0, overflowX: 'auto', overflowY: 'hidden' }}
        >
          <Box h="100%" miw="625px" style={{ minHeight: 0 }}>
            <StreamsTable onReady={handleStreamsReady} />
          </Box>
        </Box>
      </Allotment>
    </Box>
  );
};

const ChannelsPage = () => {
  return (
    <ErrorBoundary inline>
      <PageContent />
    </ErrorBoundary>
  );
};

export default ChannelsPage;
