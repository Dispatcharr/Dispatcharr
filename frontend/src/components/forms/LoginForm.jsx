import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import useAuthStore from '../../store/auth';
import API from '../../api';
import { Paper, Title, TextInput, Button, Center, Stack, Text } from '@mantine/core';

const LoginForm = () => {
  const login = useAuthStore((s) => s.login);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const initData = useAuthStore((s) => s.initData);

  const navigate = useNavigate(); // Hook to navigate to other routes
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [version, setVersion] = useState('');
  const [timestamp, setTimestamp] = useState(null);

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/channels');
    }
  }, [isAuthenticated, navigate]);

  useEffect(() => {
    const fetchVersion = async () => {
      try {
        const data = await API.getVersion();
        setVersion(data.version || '');
        setTimestamp(data.timestamp || null);
      } catch (e) {
        console.error('Failed to fetch version info:', e);
      }
    };

    fetchVersion();
  }, []);

  const handleInputChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    await login(formData);
    initData();
    navigate('/channels'); // Or any other route you'd like
  };

  return (
    <Center
      style={{
        height: '100vh',
      }}
    >
      <Paper
        elevation={3}
        style={{ padding: 30, width: '100%', maxWidth: 400 }}
      >
        <Title order={4} align="center">
          Login
        </Title>
        <form onSubmit={handleSubmit}>
          <Stack>
            <TextInput
              label="Username"
              name="username"
              value={formData.username}
              onChange={handleInputChange}
              required
            />

            <TextInput
              label="Password"
              type="password"
              name="password"
              value={formData.password}
              onChange={handleInputChange}
              required
            />

            <Button type="submit" mt="sm">
              Login
            </Button>
            <Text size="xs" ta="right" c="dimmed">
              v{version || '0.0.0'}{timestamp ? `-${timestamp}` : ''}
            </Text>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
};

export default LoginForm;
