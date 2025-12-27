import React, { useCallback, useRef } from 'react';
import ChannelsTable from '../components/tables/ChannelsTable';
import StreamsTable from '../components/tables/StreamsTable';
import { Box } from '@mantine/core';
import { Allotment } from 'allotment';
import { USER_LEVELS } from '../constants';
import useAuthStore from '../store/auth';
import useLogosStore from '../store/logos';
import useLocalStorage from '../hooks/useLocalStorage';
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

  const [allotmentSizes, setAllotmentSizes] = useLocalStorage(
    'channels-splitter-sizes',
    [50, 50]
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
    return (
      <Box style={{ padding: 10 }}>
        <ChannelsTable onReady={handleChannelsReady} />
      </Box>
    );
  }

  return (
    <Box h={'100vh'} w={'100%'} display={'flex'} style={{ overflowX: 'auto' }}>
      <Allotment
        defaultSizes={allotmentSizes}
        h={'100%'}
        w={'100%'}
        miw={'600px'}
        className="custom-allotment"
        minSize={100}
        onChange={handleSplitChange}
        onResize={handleResize}
      >
        <Box p={10} miw={'100px'} style={{ overflowX: 'auto' }}>
          <Box miw={'600px'}>
            <ChannelsTable onReady={handleChannelsReady} />
          </Box>
        </Box>
        <Box p={10} miw={'100px'} style={{ overflowX: 'auto' }}>
          <Box miw={'600px'}>
            <StreamsTable onReady={handleStreamsReady} />
          </Box>
        </Box>
      </Allotment>
    </Box>
  );
};

const ChannelsPage = () => {
  return (
    <ErrorBoundary>
      <PageContent />
    </ErrorBoundary>
  );
};

export default ChannelsPage;
