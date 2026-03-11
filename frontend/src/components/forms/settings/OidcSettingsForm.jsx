import React, { useEffect, useState, useCallback } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Collapse,
  ColorInput,
  CopyButton,
  Divider,
  Flex,
  Group,
  Loader,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { Check, Copy, Plus, Trash2, ChevronDown, ChevronUp } from 'lucide-react';
import API from '../../../api';

const USER_LEVEL_OPTIONS = [
  { value: '0', label: 'Streamer' },
  { value: '1', label: 'Standard User' },
  { value: '10', label: 'Admin' },
];

const emptyProvider = {
  name: '',
  slug: '',
  issuer_url: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  is_enabled: true,
  auto_create_users: true,
  default_user_level: '1',
  group_claim: 'groups',
  group_mappings: [],
  button_text: '',
  button_color: '#4285F4',
  allowed_redirect_uris: '',
};

const ProviderForm = ({ provider, onSave, onCancel, onDelete }) => {
  const editing = !!provider?.id;
  const [saving, setSaving] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  const form = useForm({
    initialValues: editing
      ? {
          name: provider.name || '',
          slug: provider.slug || '',
          issuer_url: provider.issuer_url || '',
          client_id: provider.client_id || '',
          client_secret: '',
          scopes: provider.scopes || 'openid profile email',
          is_enabled: provider.is_enabled ?? true,
          auto_create_users: provider.auto_create_users ?? true,
          default_user_level: String(provider.default_user_level ?? 1),
          group_claim: provider.group_claim || 'groups',
          group_mappings: provider.group_to_level_mapping
            ? Object.entries(provider.group_to_level_mapping).map(([group, level]) => ({
                group,
                level: String(level),
              }))
            : [],
          button_text: provider.button_text || '',
          button_color: provider.button_color || '#4285F4',
          allowed_redirect_uris: provider.allowed_redirect_uris || '',
        }
      : { ...emptyProvider },
    validate: {
      name: (v) => (!v ? 'Name is required' : null),
      slug: (v) => (!v ? 'Slug is required' : null),
      issuer_url: (v) => (!v ? 'Issuer URL is required' : null),
      client_id: (v) => (!v ? 'Client ID is required' : null),
    },
  });

  const autoSlug = (name) =>
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');

  const handleSubmit = async (values) => {
    setSaving(true);
    try {
      // Convert group_mappings rows to object for the API
      const groupMapping = {};
      for (const row of values.group_mappings || []) {
        if (row.group.trim()) {
          groupMapping[row.group.trim()] = parseInt(row.level, 10);
        }
      }
      const { group_mappings, ...rest } = values;
      const payload = {
        ...rest,
        default_user_level: parseInt(values.default_user_level, 10),
        group_to_level_mapping: groupMapping,
      };
      if (editing && !payload.client_secret) {
        delete payload.client_secret;
      }
      await onSave(provider?.id, payload);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={form.onSubmit(handleSubmit)}>
      <Stack gap="sm">
        <Alert variant="light" color="blue" title="Callback URL">
          <Text size="sm" mb={6}>
            Register this URL as the allowed redirect / callback URI in your identity provider:
          </Text>
          <Group gap="xs" align="center">
            <Code style={{ flex: 1, wordBreak: 'break-all' }}>
              {`${window.location.origin}/oidc/callback`}
            </Code>
            <CopyButton value={`${window.location.origin}/oidc/callback`} timeout={2000}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow>
                  <ActionIcon
                    size="sm"
                    variant="subtle"
                    color={copied ? 'teal' : 'gray'}
                    onClick={copy}
                  >
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
          </Group>
        </Alert>

        <TextInput
          label="Name"
          placeholder="e.g. Authentik, Google, Keycloak"
          {...form.getInputProps('name')}
          onChange={(e) => {
            form.getInputProps('name').onChange(e);
            if (!editing) {
              form.setFieldValue('slug', autoSlug(e.target.value));
            }
          }}
        />
        <TextInput
          label="Slug"
          placeholder="url-safe-identifier"
          {...form.getInputProps('slug')}
        />
        <TextInput
          label="Issuer URL"
          description="Discovery is supported — just enter the base issuer URL and all endpoints will be auto-configured via .well-known/openid-configuration"
          placeholder="https://auth.example.com/application/o/myapp"
          {...form.getInputProps('issuer_url')}
        />
        <TextInput
          label="Client ID"
          placeholder="Client ID from your identity provider"
          {...form.getInputProps('client_id')}
        />
        <TextInput
          label="Client Secret"
          placeholder={
            editing
              ? 'Leave blank to keep existing secret'
              : 'Client secret from your identity provider'
          }
          type="password"
          {...form.getInputProps('client_secret')}
        />
        <TextInput
          label="Scopes"
          placeholder="openid profile email"
          {...form.getInputProps('scopes')}
        />
        <Switch
          label="Enabled"
          {...form.getInputProps('is_enabled', { type: 'checkbox' })}
        />
        <Switch
          label="Auto-create users on first login"
          {...form.getInputProps('auto_create_users', { type: 'checkbox' })}
        />
        <Select
          label="Default user level for new users"
          description="Used when no group mapping matches"
          data={USER_LEVEL_OPTIONS}
          {...form.getInputProps('default_user_level')}
        />

        <Divider label="Group → Role Mapping" labelPosition="center" />

        <TextInput
          label="Group Claim"
          description='OIDC claim containing user groups (e.g. "groups", "roles", "realm_access.roles")'
          placeholder="groups"
          {...form.getInputProps('group_claim')}
        />
        <Text size="xs" c="dimmed" mb={4}>
          Map IdP group names to Dispatcharr user levels. The highest matching
          level wins. If no group matches, the default level above is used.
        </Text>
        {(form.values.group_mappings || []).map((_, idx) => (
          <Flex key={idx} gap="sm" align="flex-end">
            <TextInput
              label={idx === 0 ? 'Group Name' : undefined}
              placeholder="e.g. dispatcharr-admins"
              style={{ flex: 1 }}
              {...form.getInputProps(`group_mappings.${idx}.group`)}
            />
            <Select
              label={idx === 0 ? 'User Level' : undefined}
              data={USER_LEVEL_OPTIONS}
              style={{ width: 160 }}
              {...form.getInputProps(`group_mappings.${idx}.level`)}
            />
            <ActionIcon
              color="red"
              variant="subtle"
              onClick={() => form.removeListItem('group_mappings', idx)}
              mb={2}
            >
              <Trash2 size={16} />
            </ActionIcon>
          </Flex>
        ))}
        <Button
          variant="light"
          size="xs"
          leftSection={<Plus size={14} />}
          onClick={() =>
            form.insertListItem('group_mappings', { group: '', level: '1' })
          }
        >
          Add Group Mapping
        </Button>
        <TextInput
          label="Button Text"
          placeholder="Sign in with ..."
          {...form.getInputProps('button_text')}
        />
        <ColorInput
          label="Button Color"
          {...form.getInputProps('button_color')}
        />

        <Divider label="Security" labelPosition="center" />

        <TextInput
          label="Allowed Redirect Hosts"
          description="Comma-separated hosts (host:port recommended) or full URLs allowed for OAuth redirects. If empty, same-host+port fallback is used."
          placeholder="localhost:9191, app.example.com:443, [::1]:9191"
          {...form.getInputProps('allowed_redirect_uris')}
        />

        <Flex justify="space-between" align="center" mt="md">
          {editing ? (
            deleteConfirm ? (
              <Group gap="xs">
                <Text size="sm" c="red">
                  Confirm delete?
                </Text>
                <Button
                  size="xs"
                  color="red"
                  variant="filled"
                  onClick={() => onDelete(provider.id)}
                >
                  Yes, Delete
                </Button>
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => setDeleteConfirm(false)}
                >
                  No
                </Button>
              </Group>
            ) : (
              <Button
                variant="subtle"
                color="red"
                size="xs"
                leftSection={<Trash2 size={14} />}
                onClick={() => setDeleteConfirm(true)}
              >
                Delete Provider
              </Button>
            )
          ) : (
            <div />
          )}
          <Group gap="sm">
            <Button variant="default" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              {editing ? 'Save Changes' : 'Create Provider'}
            </Button>
          </Group>
        </Flex>
      </Stack>
    </form>
  );
};

const OidcSettingsForm = React.memo(({ active }) => {
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState(null); // provider id or 'new'
  const [ssoEnabled, setSsoEnabled] = useState(false);
  const [ssoSaving, setSsoSaving] = useState(false);

  const fetchProviders = useCallback(async () => {
    setLoading(true);
    try {
      const data = await API.getOIDCManagedProviders();
      const list = Array.isArray(data) ? data : data?.results || [];
      setProviders(list);
      setSsoEnabled(list.some((p) => p.is_enabled));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (active) fetchProviders();
  }, [active, fetchProviders]);

  const toggleSso = async (checked) => {
    setSsoSaving(true);
    try {
      for (const p of providers) {
        if (p.is_enabled !== checked) {
          await API.updateOIDCProvider(p.id, { is_enabled: checked });
        }
      }
      setSsoEnabled(checked);
      await fetchProviders();
    } finally {
      setSsoSaving(false);
    }
  };

  const handleSave = async (id, payload) => {
    if (id) {
      await API.updateOIDCProvider(id, payload);
    } else {
      await API.createOIDCProvider(payload);
    }
    setExpandedId(null);
    fetchProviders();
  };

  const handleDelete = async (id) => {
    await API.deleteOIDCProvider(id);
    setExpandedId(null);
    fetchProviders();
  };

  const toggleExpand = (id) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  if (loading && providers.length === 0) return <Loader />;

  return (
    <Stack gap="md">
      <Flex justify="space-between" align="center">
        <Text fw={500}>OIDC Single Sign-On</Text>
        <Switch
          label="SSO Enabled"
          checked={ssoEnabled}
          disabled={providers.length === 0 || ssoSaving}
          onChange={(e) => toggleSso(e.currentTarget.checked)}
        />
      </Flex>

      {providers.length === 0 && !loading && (
        <Alert variant="light" color="blue" title="No OIDC Providers">
          Add an OIDC provider to enable single sign-on. Supports Authentik,
          Keycloak, Google, Okta, and any OpenID Connect compatible provider.
        </Alert>
      )}

      {providers.map((p) => (
        <Card key={p.id} withBorder padding="sm">
          <Flex
            justify="space-between"
            align="center"
            style={{ cursor: 'pointer' }}
            onClick={() => toggleExpand(p.id)}
          >
            <Group gap="sm">
              <Text fw={500}>{p.name}</Text>
              <Badge
                color={p.is_enabled ? 'green' : 'gray'}
                variant="light"
                size="sm"
              >
                {p.is_enabled ? 'Enabled' : 'Disabled'}
              </Badge>
              <Text size="xs" c="dimmed">
                {p.issuer_url}
              </Text>
            </Group>
            {expandedId === p.id ? (
              <ChevronUp size={16} />
            ) : (
              <ChevronDown size={16} />
            )}
          </Flex>
          <Collapse in={expandedId === p.id}>
            <Divider my="sm" />
            <ProviderForm
              provider={p}
              onSave={handleSave}
              onCancel={() => setExpandedId(null)}
              onDelete={handleDelete}
            />
          </Collapse>
        </Card>
      ))}

      {/* New provider inline form */}
      {expandedId === 'new' ? (
        <Card withBorder padding="sm">
          <Text fw={500} mb="sm">
            New OIDC Provider
          </Text>
          <ProviderForm
            provider={null}
            onSave={handleSave}
            onCancel={() => setExpandedId(null)}
            onDelete={handleDelete}
          />
        </Card>
      ) : (
        <Button
          leftSection={<Plus size={16} />}
          variant="light"
          onClick={() => setExpandedId('new')}
        >
          Add OIDC Provider
        </Button>
      )}
    </Stack>
  );
});

OidcSettingsForm.displayName = 'OidcSettingsForm';
export default OidcSettingsForm;
