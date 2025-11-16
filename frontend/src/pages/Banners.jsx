import React, { useEffect, useCallback, useState } from 'react';
import { Box, Tabs, Flex, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import useBannersStore from '../store/banners';
import useVODBannersStore from '../store/vodBanners';
import BannersTable from '../components/tables/BannersTable';
import VODBannersTable from '../components/tables/VODBannersTable';

const BannersPage = () => {
  const { fetchAllBanners, needsAllBanners, banners } = useBannersStore();
  const { totalCount } = useVODBannersStore();
  const [activeTab, setActiveTab] = useState('channel');

  const channelBannersCount = Object.keys(banners).length;
  const vodBannersCount = totalCount;

  const loadChannelBanners = useCallback(async () => {
    try {
      // Only fetch all banners if we haven't loaded them yet
      if (needsAllBanners()) {
        await fetchAllBanners();
      }
    } catch (err) {
      notifications.show({
        title: 'Error',
        message: 'Failed to load channel banners',
        color: 'red',
      });
      console.error('Failed to load channel banners:', err);
    }
  }, [fetchAllBanners, needsAllBanners]);

  useEffect(() => {
    // Always load channel banners on mount
    loadChannelBanners();
  }, [loadChannelBanners]);

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
              Banners
            </Text>
            <Text size="sm" c="dimmed">
              ({activeTab === 'channel' ? channelBannersCount : vodBannersCount}{' '}
              banner
              {(activeTab === 'channel' ? channelBannersCount : vodBannersCount) !==
              1
                ? 's'
                : ''}
              )
            </Text>
          </Flex>

          <Tabs value={activeTab} onChange={setActiveTab} variant="pills">
            <Tabs.List>
              <Tabs.Tab value="channel">Channel Banners</Tabs.Tab>
              <Tabs.Tab value="vod">VOD Banners</Tabs.Tab>
            </Tabs.List>
          </Tabs>
        </Flex>
      </Box>

      {/* Content based on active tab */}
      {activeTab === 'channel' && <BannersTable />}
      {activeTab === 'vod' && <VODBannersTable />}
    </Box>
  );
};

export default BannersPage;
