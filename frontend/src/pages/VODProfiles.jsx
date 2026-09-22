import React from 'react';
import { Navigate } from 'react-router-dom';
import { Box } from '@mantine/core';
import VODOutputProfilesModal from '../components/VODOutputProfilesModal.jsx';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';

const VODProfilesPage = () => {
  const user = useAuthStore((state) => state.user);

  if (!user || user.user_level < USER_LEVELS.ADMIN) {
    return <Navigate to="/vods" replace />;
  }

  return (
    <Box h="100%" style={{ minHeight: 0, overflow: 'hidden' }}>
      <VODOutputProfilesModal opened embedded onClose={() => {}} />
    </Box>
  );
};

export default VODProfilesPage;
