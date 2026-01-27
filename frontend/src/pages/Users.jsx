import React, { useState } from 'react';
import UsersTable from '../components/tables/UsersTable';
import { Box } from '@mantine/core';
import useAuthStore from '../store/auth';

const UsersPage = () => {
  const authUser = useAuthStore((s) => s.user);

  if (!authUser.id) {
    return <></>;
  }

  return (
    <Box style={{ padding: 10 }}>
      <UsersTable />
    </Box>
  );
};

export default UsersPage;
