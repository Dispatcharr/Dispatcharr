import useUserAgentsStore from '../store/userAgents';
import M3UsTable from '../components/tables/M3UsTable';
import EPGsTable from '../components/tables/EPGsTable';
import { Box, Stack } from '@mantine/core';

const M3UPage = () => {
  const error = useUserAgentsStore((state) => state.error);
  if (error) return <div>Error: {error}</div>;
  return (
    <Stack
      style={{
        padding: 10,
        height: '100%', // Set a specific height to ensure proper display
        minWidth: '1100px', // Prevent tables from becoming too cramped
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
};

export default M3UPage;
