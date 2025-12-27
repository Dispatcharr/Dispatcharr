import useUserAgentsStore from '../store/userAgents';
import M3UsTable from '../components/tables/M3UsTable';
import EPGsTable from '../components/tables/EPGsTable';
import { Box, Stack } from '@mantine/core';
import ErrorBoundary from '../components/ErrorBoundary'

const PageContent = () => {
  const error = useUserAgentsStore((state) => state.error);
  if (error) throw new Error(error);

  return (
    <Stack
      p="10"
      h="100%" // Set a specific height to ensure proper display
      miw="1100px" // Prevent tables from becoming too cramped
      style={{
        overflowX: 'auto', // Enable horizontal scrolling when needed
        overflowY: 'auto', // Enable vertical scrolling on the container
      }}
      spacing="xs" // Reduce spacing to give tables more room
    >
      <Box sx={{ flex: '1 1 50%', overflow: 'hidden' }}>
        <M3UsTable />
      </Box>

      <Box sx={{ flex: '1 1 50%', overflow: 'hidden' }}>
        <EPGsTable />
      </Box>
    </Stack>
  );
}

const M3UPage = () => {
  return (
    <ErrorBoundary>
      <PageContent/>
    </ErrorBoundary>
  );
}

export default M3UPage;
