import React, { Suspense, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { Box } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import VODSourceManagerModal from '../components/VODSourceManagerModal.jsx';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';

const SeriesModal = React.lazy(() => import('../components/SeriesModal.jsx'));
const VODModal = React.lazy(() => import('../components/VODModal.jsx'));

const VODPlaybackHistoryPage = () => {
  const user = useAuthStore((state) => state.user);
  const [selectedSeries, setSelectedSeries] = useState(null);
  const [selectedVOD, setSelectedVOD] = useState(null);
  const [seriesOpened, seriesHandlers] = useDisclosure(false);
  const [vodOpened, vodHandlers] = useDisclosure(false);

  if (!user || user.user_level < USER_LEVELS.ADMIN) {
    return <Navigate to="/vods" replace />;
  }

  const openContent = (item) => {
    if (item.contentType === 'series') {
      setSelectedSeries(item);
      seriesHandlers.open();
      return;
    }
    setSelectedVOD(item);
    vodHandlers.open();
  };

  return (
    <Box h="100%" style={{ minHeight: 0, overflow: 'hidden' }}>
      <VODSourceManagerModal
        opened
        embedded
        onClose={() => {}}
        onOpenContent={openContent}
      />
      {seriesOpened && selectedSeries && (
        <ErrorBoundary inline>
          <Suspense fallback={null}>
            <SeriesModal
              series={selectedSeries}
              opened
              onClose={seriesHandlers.close}
              onCanonicalMoved={setSelectedSeries}
              initialRelationId={selectedSeries.relation_id}
              allowSourceEditing
            />
          </Suspense>
        </ErrorBoundary>
      )}
      {vodOpened && selectedVOD && (
        <ErrorBoundary inline>
          <Suspense fallback={null}>
            <VODModal
              vod={selectedVOD}
              opened
              onClose={vodHandlers.close}
              onCanonicalMoved={setSelectedVOD}
              initialRelationId={selectedVOD.relation_id}
              allowSourceEditing
            />
          </Suspense>
        </ErrorBoundary>
      )}
    </Box>
  );
};

export default VODPlaybackHistoryPage;
