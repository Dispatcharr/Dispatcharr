import React from 'react';
import {
  Badge,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import useSettingsStore from '../../../store/settings.jsx';

const TlsOption = ({ label, description, tooltip, badgeText, badgeColor }) => (
  <div>
    <Group gap="xs" align="center">
      <Text size="sm" fw={500}>
        {label}
      </Text>
      <Tooltip label={tooltip}>
        <Badge color={badgeColor} variant="light" size="sm">
          {badgeText}
        </Badge>
      </Tooltip>
    </Group>
    <Text size="xs" c="dimmed">
      {description}
    </Text>
  </div>
);

const TlsServiceCard = ({ serviceName, children }) => (
  <Paper p="md" withBorder h="100%">
    <Stack gap="sm">
      <Text fw={600}>{serviceName}</Text>
      {children}
    </Stack>
  </Paper>
);

const RedisStatus = ({ tls }) => {
  const enabled = tls?.enabled ?? false;
  const verify = tls?.verify ?? true;
  const mtls = tls?.mtls ?? false;

  let verifyColor = 'gray';
  let verifyTooltip = 'Verification is not active — TLS is disabled';
  if (enabled) {
    verifyColor = verify ? 'green' : 'yellow';
    verifyTooltip = verify
      ? "The server's identity is verified using a trusted certificate"
      : 'The connection is encrypted but the server identity is not verified';
  }

  let mtlsColor = 'gray';
  let mtlsTooltip = 'Mutual authentication is not active';
  if (enabled && mtls) {
    mtlsColor = 'green';
    mtlsTooltip = 'Both client and server verify each other with certificates';
  }

  return (
    <TlsServiceCard serviceName="Redis">
      <TlsOption
        label="Encryption"
        description="Encrypt traffic between Dispatcharr and Redis."
        tooltip={
          enabled
            ? 'The connection is encrypted'
            : 'The connection is not encrypted'
        }
        badgeText={enabled ? 'Enabled' : 'Disabled'}
        badgeColor={enabled ? 'green' : 'gray'}
      />
      <TlsOption
        label="Server Verification"
        description="Verify the Redis server's identity using a CA certificate."
        tooltip={verifyTooltip}
        badgeText={verify && enabled ? 'On' : 'Off'}
        badgeColor={verifyColor}
      />
      <TlsOption
        label="Mutual TLS"
        description="Authenticate Dispatcharr to Redis using a client certificate."
        tooltip={mtlsTooltip}
        badgeText={mtls && enabled ? 'Active' : 'Inactive'}
        badgeColor={mtlsColor}
      />
    </TlsServiceCard>
  );
};

const PostgresStatus = ({ tls }) => {
  const enabled = tls?.enabled ?? false;
  const sslMode = tls?.ssl_mode;
  const mtls = tls?.mtls ?? false;

  let modeColor = 'gray';
  let modeTooltip = 'Verification mode is not active — TLS is disabled';
  let modeBadge = 'Off';
  if (enabled && sslMode) {
    modeBadge = sslMode;
    if (sslMode === 'verify-full') {
      modeColor = 'green';
      modeTooltip = 'Server certificate and hostname are both verified';
    } else if (sslMode === 'verify-ca') {
      modeColor = 'yellow';
      modeTooltip =
        'Server certificate is verified, but hostname is not checked';
    } else {
      modeColor = 'yellow';
      modeTooltip = 'Connection is encrypted but the server is not verified';
    }
  }

  let mtlsColor = 'gray';
  let mtlsTooltip = 'Mutual authentication is not active';
  if (enabled && mtls) {
    mtlsColor = 'green';
    mtlsTooltip = 'Both client and server verify each other with certificates';
  }

  return (
    <TlsServiceCard serviceName="PostgreSQL">
      <TlsOption
        label="Encryption"
        description="Encrypt traffic between Dispatcharr and PostgreSQL."
        tooltip={
          enabled
            ? 'The connection is encrypted'
            : 'The connection is not encrypted'
        }
        badgeText={enabled ? 'Enabled' : 'Disabled'}
        badgeColor={enabled ? 'green' : 'gray'}
      />
      <TlsOption
        label="Verification Mode"
        description="How strictly to verify the PostgreSQL server's identity."
        tooltip={modeTooltip}
        badgeText={modeBadge}
        badgeColor={modeColor}
      />
      <TlsOption
        label="Mutual TLS"
        description="Authenticate Dispatcharr to PostgreSQL using a client certificate."
        tooltip={mtlsTooltip}
        badgeText={mtls && enabled ? 'Active' : 'Inactive'}
        badgeColor={mtlsColor}
      />
    </TlsServiceCard>
  );
};

const ConnectionSecurityPanel = React.memo(() => {
  const environment = useSettingsStore((s) => s.environment);

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Encrypt connections to Redis and PostgreSQL using environment variables
        in the docker compose file.
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
        <RedisStatus tls={environment.redis_tls} />
        <PostgresStatus tls={environment.postgres_tls} />
      </SimpleGrid>
    </Stack>
  );
});

export default ConnectionSecurityPanel;
