import React, { useEffect, useCallback } from 'react';
import { Box, Loader, Center, Text, Stack } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import useBannersStore from '../store/banners';
import BannersTable from '../components/tables/BannersTable';

const BannersPage = () => {
  const { fetchAllBanners, isLoading, needsAllBanners } = useBannersStore();

  const loadBanners = useCallback(async () => {
    try {
      // Only fetch all banners if we haven't loaded them yet
      if (needsAllBanners()) {
        await fetchAllBanners();
      }
    } catch (err) {
      notifications.show({
        title: 'Error',
        message: 'Failed to load banners',
        color: 'red',
      });
      console.error('Failed to load banners:', err);
    }
  }, [fetchAllBanners, needsAllBanners]);

  useEffect(() => {
    loadBanners();
  }, [loadBanners]);

  return (
    <Box style={{ padding: 10 }}>
      {isLoading && (
        <Center style={{ marginBottom: 20 }}>
          <Stack align="center" spacing="sm">
            <Loader size="sm" />
            <Text size="sm" color="dimmed">
              Loading all banners...
            </Text>
          </Stack>
        </Center>
      )}
      <BannersTable />
    </Box>
  );
};

export default BannersPage;
