import useUserAgentsStore from '../store/userAgents';
import M3UsTable from '../components/tables/M3UsTable';
import EPGsTable from '../components/tables/EPGsTable';
import { Box, Stack } from '@mantine/core';
import ErrorBoundary from '../components/ErrorBoundary';

const PageContent = ({ section = 'all' }) => {
  const error = useUserAgentsStore((state) => state.error);
  if (error) throw new Error(error);

  return (
    <Stack
      p="10"
      gap="xs"
      style={{
        // Fill the viewport exactly; never scroll the page itself. Each table
        // scrolls internally within its own share of the height.
        height: '100%',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {section !== 'epg' && (
        <Box style={{ flex: '1 1 auto', minHeight: 0 }}>
          <M3UsTable />
        </Box>
      )}

      {section !== 'm3u' && (
        <Box
          style={{
            flex: section === 'all' ? '0 0 50%' : '1 1 auto',
            minHeight: 0,
          }}
        >
          <EPGsTable />
        </Box>
      )}
    </Stack>
  );
};

const ContentSources = ({ section = 'all' }) => {
  return (
    <ErrorBoundary inline>
      <PageContent section={section} />
    </ErrorBoundary>
  );
};

export default ContentSources;
