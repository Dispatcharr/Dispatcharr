import useUserAgentsStore from '../store/userAgents';
import M3UsTable from '../components/tables/M3UsTable';
import EPGsTable from '../components/tables/EPGsTable';
import { Box, Stack } from '@mantine/core';
import ErrorBoundary from '../components/ErrorBoundary';

const PageContent = () => {
  const error = useUserAgentsStore((state) => state.error);
  if (error) throw new Error(error);

  return (
    <Stack
      p="10"
      gap="xs"
      style={{
        // Fill the viewport exactly; never scroll the page itself. Each table
        // scrolls internally within its own share of the height.
        height: '100vh',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Takes whatever's left above the EPG table, so adding/filtering M3U
          rows never resizes the EPG table below it. */}
      <Box style={{ flex: '1 1 auto', minHeight: 0 }}>
        <M3UsTable />
      </Box>

      {/* Fixed to half the available height so it never jumps around. */}
      <Box style={{ flex: '0 0 50%', minHeight: 0 }}>
        <EPGsTable />
      </Box>
    </Stack>
  );
};

const M3UPage = () => {
  return (
    <ErrorBoundary>
      <PageContent />
    </ErrorBoundary>
  );
};

export default M3UPage;
