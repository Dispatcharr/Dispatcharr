import React from 'react';
import { Box, Title, Stack, Anchor, Text } from '@mantine/core';
import useSettingsStore from '../store/settings';

const Help = () => {
  const environment = useSettingsStore((s) => s.environment);
  const swaggerUrl = `${window.location.origin}/swagger/`;

  return (
    <Box p="md">
      <Title order={3} mb="md">
        Help & Resources
      </Title>
      <Stack gap={8}>
        <Text>
          <Anchor href={swaggerUrl} target="_blank" rel="noopener noreferrer">
            API Swagger Documentation
          </Anchor>
        </Text>
        <Text>
          <Anchor href="https://dispatcharr.github.io/Dispatcharr-Docs/" target="_blank" rel="noopener noreferrer">
            Dispatcharr Documentation
          </Anchor>
        </Text>
        <Text>
          <Anchor href="https://discord.gg/aMqkWsydMH" target="_blank" rel="noopener noreferrer">
            Discord
          </Anchor>
        </Text>
      </Stack>
    </Box>
  );
};

export default Help;
