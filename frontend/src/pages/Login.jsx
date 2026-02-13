import React, { lazy, Suspense } from 'react';
import LoginForm from '../components/forms/LoginForm';
const SuperuserForm = lazy(() => import('../components/forms/SuperuserForm'));
import useAuthStore from '../store/auth';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import { Text } from '@mantine/core';

const Login = ({}) => {
  const superuserExists = useAuthStore((s) => s.superuserExists);

  if (!superuserExists) {
    return (
      <ErrorBoundary>
        <Suspense fallback={<Text>Loading...</Text>}>
          <SuperuserForm />
        </Suspense>
      </ErrorBoundary>
    );
  }

  return <LoginForm />;
};

export default Login;
