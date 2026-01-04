import React, { useEffect, useCallback, useState } from 'react';
import { Box, Tabs, Flex, Text, TabsList, TabsTab } from '@mantine/core';
import useLogosStore from '../store/logos';
import useVODLogosStore from '../store/vodLogos';
import LogosTable from '../components/tables/LogosTable';
import VODLogosTable from '../components/tables/VODLogosTable';
import { showNotification } from '../utils/notificationUtils.js';

const LogosPage = () => {
  const logos = useLogosStore(s => s.logos);
  const totalCount = useVODLogosStore(s => s.totalCount);
  const [activeTab, setActiveTab] = useState('channel');
  const logoCount = activeTab === 'channel'
    ? Object.keys(logos).length
    : totalCount;

  const loadChannelLogos = useCallback(async () => {
    try {
      // Only fetch all logos if we haven't loaded them yet
      if (useLogosStore.getState().needsAllLogos()) {
        await useLogosStore.getState().fetchAllLogos();
      }
    } catch (err) {
      showNotification({
        title: 'Error',
        message: 'Failed to load channel logos',
        color: 'red',
      });
      console.error('Failed to load channel logos:', err);
    }
  }, []);

  useEffect(() => {
    // Always load channel logos on mount
    loadChannelLogos();
  }, [loadChannelLogos]);

  return (
    <Box>
      {/* Header with title and tabs */}
      <Box
        style={{ justifyContent: 'center' }}
        display={'flex'}
        p={'10px 0'}
      >
        <Flex
          style={{
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
          w={'100%'}
          maw={'1200px'}
          pb={10}
        >
          <Flex gap={8} align="center">
            <Text
              ff={'Inter, sans-serif'}
              fz={'20px'}
              fw={500}
              lh={1}
              c='white'
              mb={0}
              lts={'-0.3px'}
            >
              Logos
            </Text>
            <Text size="sm" c="dimmed">
              ({logoCount} {logoCount !== 1 ? 'logos' : 'logo'})
            </Text>
          </Flex>

          <Tabs value={activeTab} onChange={setActiveTab} variant="pills">
            <TabsList>
              <TabsTab value="channel">Channel Logos</TabsTab>
              <TabsTab value="vod">VOD Logos</TabsTab>
            </TabsList>
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
