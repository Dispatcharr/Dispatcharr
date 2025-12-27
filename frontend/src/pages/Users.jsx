import UsersTable from '../components/tables/UsersTable';
import { Box } from '@mantine/core';
import useAuthStore from '../store/auth';
import ErrorBoundary from '../components/ErrorBoundary';

const PageContent = () => {
  const authUser = useAuthStore((s) => s.user);
  if (!authUser.id) throw new Error();

  return (
    <Box p={10}>
      <UsersTable />
    </Box>
  );
}

const UsersPage = () => {
  return (
    <ErrorBoundary>
      <PageContent/>
    </ErrorBoundary>
  );
};

export default UsersPage;
