import React, { useEffect, useCallback, useState } from 'react';
import { Box, Tabs, Flex, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import useLogosStore from '../store/logos';
import useVODLogosStore from '../store/vodLogos';
import LogosTable from '../components/tables/LogosTable';
import VODLogosTable from '../components/tables/VODLogosTable';

const LogosPage = () => {
  const { fetchAllLogos, needsAllLogos, logos } = useLogosStore();
  const { totalCount } = useVODLogosStore();
  const [activeTab, setActiveTab] = useState('channel');

  const channelLogosCount = Object.keys(logos).length;
  const vodLogosCount = totalCount;

  const loadChannelLogos = useCallback(async () => {
    try {
      // Only fetch all logos if we haven't loaded them yet
      if (needsAllLogos()) {
        await fetchAllLogos();
      }
    } catch (err) {
      notifications.show({
        title: 'Error',
        message: 'Failed to load channel logos',
        color: 'red',
      });
      console.error('Failed to load channel logos:', err);
    }
  }, [fetchAllLogos, needsAllLogos]);

  useEffect(() => {
    // Always load channel logos on mount
    loadChannelLogos();
  }, [loadChannelLogos]);

  return (
    <Box>
      {/* Header with title and tabs */}
      <Box
        style={{
          display: 'flex',
          justifyContent: 'center',
          padding: '10px 0',
        }}
      >
        <Flex
          style={{
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            maxWidth: '1200px',
            paddingBottom: 10,
          }}
        >
          <Flex gap={8} align="center">
            <Text
              style={{
                fontFamily: 'Inter, sans-serif',
                fontWeight: 500,
                fontSize: '20px',
                lineHeight: 1,
                letterSpacing: '-0.3px',
                color: 'gray.6',
                marginBottom: 0,
              }}
            >
              Logos
            </Text>
            <Text size="sm" c="dimmed">
              ({activeTab === 'channel' ? channelLogosCount : vodLogosCount}{' '}
              logo
              {(activeTab === 'channel' ? channelLogosCount : vodLogosCount) !==
              1
                ? 's'
                : ''}
              )
            </Text>
          </Flex>

          <Tabs value={activeTab} onChange={setActiveTab} variant="pills">
            <Tabs.List>
              <Tabs.Tab value="channel">Channel Logos</Tabs.Tab>
              <Tabs.Tab value="vod">VOD Logos</Tabs.Tab>
            </Tabs.List>
          </Tabs>
        </Flex>
      </Box>

      {/* Content based on active tab */}
      {activeTab === 'channel' && <LogosTable />}
      {activeTab === 'vod' && <VODLogosTable />}
    </Box>
  );
};

export default LogosPage;
