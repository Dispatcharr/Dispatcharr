import React, { useEffect, useCallback } from 'react';
import { Box, Flex, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import useBannersStore from '../store/banners';
import BannersTable from '../components/tables/BannersTable';

const BannersPage = () => {
  const { fetchAllBanners, needsAllBanners, banners } = useBannersStore();

  const channelBannersCount = Object.keys(banners).length;

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
              ({channelBannersCount}{' '}
              banner
              {channelBannersCount !== 1 ? 's' : ''})
            </Text>
          </Flex>
        </Flex>
      </Box>

      {/* Channel Banners Table */}
      <BannersTable />
    </Box>
  );
};

export default BannersPage;
