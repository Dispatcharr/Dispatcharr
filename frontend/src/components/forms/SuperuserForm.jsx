// frontend/src/components/forms/SuperuserForm.js
import React, { useState, useEffect } from 'react';
import {
  TextInput,
  Center,
  Button,
  Paper,
  Title,
  Stack,
  Text,
  Image,
  Divider,
  Code,
  Anchor,
  Modal,
  Group,
} from '@mantine/core';
import API from '../../api';
import useAuthStore from '../../store/auth';
import useSettingsStore from '../../store/settings';
import logo from '../../assets/logo.png';

const createSuperUser = (formData) => {
  return API.createSuperUser({
    username: formData.username,
    password: formData.password,
    email: formData.email,
  });
};

function SetupHelpModal({ opened, onClose, clientIp }) {
  const ip = clientIp || '<your-ip>';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Finish setup from this network"
      centered
      data-testid="setup-help"
    >
      <Stack spacing="md">
        <Text size="sm">
          Web setup is limited to local networks by default. Dispatcharr
          currently sees your connection as <Code>{ip}</Code>.
        </Text>
        <Text size="sm">
          To allow web setup from this IP, set the environment variable and
          restart, then reload this page:
        </Text>
        <Code block>DISPATCHARR_SETUP_ALLOWED_IP={ip}</Code>
        <Text size="sm">
          Or create the admin account from the host with a management command:
        </Text>
        <div>
          <Text weight={500} size="sm" mb={8}>
            If running with Docker:
          </Text>
          <Code block>
            {`docker exec <container_name> python manage.py createsuperuser`}
          </Code>
        </div>
        <div>
          <Text weight={500} size="sm" mb={8}>
            If running locally:
          </Text>
          <Code block>python manage.py createsuperuser</Code>
        </div>
        <Text size="xs" color="dimmed">
          Replace <code>{'<container_name>'}</code> with your Docker container
          name. After the account exists, this setup page will no longer be
          available.
        </Text>
      </Stack>
    </Modal>
  );
}

function SuperuserForm() {
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    email: '',
  });
  const setupClientIp = useAuthStore((s) => s.setupClientIp);
  const initialSetupAllowed = useAuthStore((s) => s.setupAllowed);
  const [clientIp, setClientIp] = useState(setupClientIp);
  const [setupAllowed, setSetupAllowed] = useState(
    initialSetupAllowed !== false
  );
  const [setupHelpOpened, setSetupHelpOpened] = useState(
    initialSetupAllowed === false
  );
  const setSuperuserStatus = useAuthStore((s) => s.setSuperuserStatus);
  const fetchVersion = useSettingsStore((s) => s.fetchVersion);
  const storedVersion = useSettingsStore((s) => s.version);

  useEffect(() => {
    // Fetch version info using the settings store (will skip if already loaded)
    fetchVersion();
  }, [fetchVersion]);

  const handleChange = (e) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await createSuperUser(formData);
      if (response?.superuser_exists) {
        setSuperuserStatus({ superuser_exists: true });
      }
    } catch (err) {
      const body = err?.body;
      if (err?.status === 403 || body?.setup_allowed === false) {
        if (body?.client_ip) {
          setClientIp(body.client_ip);
        }
        setSetupAllowed(false);
        setSetupHelpOpened(true);
      }
    }
  };

  return (
    <Center
      style={{
        height: '100vh',
      }}
    >
      <Paper
        elevation={3}
        style={{
          padding: 30,
          width: '100%',
          maxWidth: 500,
          position: 'relative',
        }}
      >
        <Stack align="center" spacing="lg">
          <Image
            src={logo}
            alt="Dispatcharr Logo"
            width={120}
            height={120}
            fit="contain"
          />
          <Title order={2} align="center">
            Dispatcharr
          </Title>
          <Text size="sm" color="dimmed" align="center">
            {setupAllowed
              ? 'Welcome! Create your Super User Account to get started.'
              : 'Web setup from this network is not enabled yet.'}
          </Text>
          <Divider style={{ width: '100%' }} />
        </Stack>

        {setupAllowed ? (
          <form onSubmit={handleSubmit}>
            <Stack>
              <TextInput
                label="Username"
                name="username"
                value={formData.username}
                onChange={handleChange}
                required
              />
              <TextInput
                label="Password"
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                required
              />

              <TextInput
                label="Email (optional)"
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
              />

              <Group justify="flex-end">
                <Anchor
                  size="sm"
                  component="button"
                  type="button"
                  onClick={() => setSetupHelpOpened(true)}
                >
                  Remote setup help
                </Anchor>
              </Group>

              <Button type="submit" fullWidth>
                Create Account
              </Button>
            </Stack>
          </form>
        ) : (
          <Stack>
            <Text size="sm" align="center">
              Your connection appears as <Code>{clientIp || 'unknown'}</Code>.
              Open the instructions to allow this IP for web setup, or create
              the admin account from the host.
            </Text>
            <Button fullWidth onClick={() => setSetupHelpOpened(true)}>
              View setup instructions
            </Button>
          </Stack>
        )}

        {storedVersion.version && (
          <Text
            size="xs"
            color="dimmed"
            style={{
              position: 'absolute',
              bottom: 6,
              right: 30,
            }}
          >
            v{storedVersion.version}
          </Text>
        )}
      </Paper>

      <SetupHelpModal
        opened={setupHelpOpened}
        onClose={() => setSetupHelpOpened(false)}
        clientIp={clientIp}
      />
    </Center>
  );
}

export default SuperuserForm;
