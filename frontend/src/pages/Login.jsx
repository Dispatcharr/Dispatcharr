import React, { lazy, Suspense } from 'react';
import LoginForm from '../components/forms/LoginForm';
const SuperuserForm = lazy(() => import('../components/forms/SuperuserForm'));
import useAuthStore from '../store/auth';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import { Center, Image, Loader, Paper, Stack } from '@mantine/core';
import logo from '../assets/logo.png';

const LoginLoadingCard = () => (
  <Center style={{ height: '100vh' }}>
    <Paper
      elevation={3}
      style={{
        padding: 30,
        width: '100%',
        maxWidth: 500,
      }}
    >
      <Stack align="center" justify="center" spacing="lg" mih={280}>
        <Image
          src={logo}
          alt="Dispatcharr Logo"
          width={120}
          height={120}
          fit="contain"
        />
        <Loader aria-label="Loading login" />
      </Stack>
    </Paper>
  </Center>
);

const Login = () => {
  const superuserExists = useAuthStore((s) => s.superuserExists);

  if (superuserExists === null) {
    return <LoginLoadingCard />;
  }

  if (!superuserExists) {
    return (
      <ErrorBoundary>
        <Suspense fallback={<LoginLoadingCard />}>
          <SuperuserForm />
        </Suspense>
      </ErrorBoundary>
    );
  }

  return <LoginForm />;
};

export default Login;
