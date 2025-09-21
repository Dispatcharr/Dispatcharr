import React from 'react';
import ChannelsTable from '../components/tables/ChannelsTable';
import StreamsTable from '../components/tables/StreamsTable';
import { Box } from '@mantine/core';
import { Allotment } from 'allotment';
import { USER_LEVELS } from '../constants';
import useAuthStore from '../store/auth';
import useLocalStorage from '../hooks/useLocalStorage';

const ChannelsPage = () => {
  const authUser = useAuthStore((s) => s.user);
  const [allotmentSizes, setAllotmentSizes] = useLocalStorage(
    'channels-splitter-sizes',
    [50, 50]
  );

  const handleSplitChange = (sizes) => {
    setAllotmentSizes(sizes);
  };

  const handleResize = (sizes) => {
    setAllotmentSizes(sizes);
  };

  if (!authUser.id) {
    return <></>;
  }
  if (authUser.user_level <= USER_LEVELS.STANDARD) {
    return (
      <Box style={{ padding: 10 }}>
        <ChannelsTable />
      </Box>
    );
  }

  return (
    <div
      style={{
        height: '100vh',
        width: '100%',
        display: 'flex',
        overflowX: 'auto',
      }}
    >
      <Allotment
        defaultSizes={allotmentSizes}
        style={{ height: '100%', width: '100%', minWidth: '600px' }}
        className="custom-allotment"
        minSize={100}
        onChange={handleSplitChange}
        onResize={handleResize}
      >
        <div style={{ padding: 10, overflowX: 'auto', minWidth: '100px' }}>
          <div style={{ minWidth: '600px' }}>
            <ChannelsTable />
          </div>
        </div>
        <div style={{ padding: 10, overflowX: 'auto', minWidth: '100px' }}>
          <div style={{ minWidth: '600px' }}>
            <StreamsTable />
          </div>
        </div>
      </Allotment>
    </div>
  );
};

export default ChannelsPage;
