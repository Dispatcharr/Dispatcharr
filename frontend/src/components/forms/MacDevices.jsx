import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Image,
} from '@mantine/core';
import {
  AlertTriangle,
  Send,
  SquarePen,
  SquareMinus,
  SquarePlus,
  X,
} from 'lucide-react';
import API from '../../api';
import useMacDevicesStore from '../../store/macDevices';

// Mirrors apps/mac_panel/panels.py's PANELS registry. There is no API to
// fetch this list, so it's kept small and in sync by hand — add sibling
// domains here (and server-side) as they come up.
const PANEL_OPTIONS = [
  { value: 'iboxx', label: 'IBOXX Player' },
  { value: 'cr7', label: 'CR7 Player' },
  { value: 'iboplayer', label: 'IBO Player' },
  { value: 'ibovpn', label: 'IBO VPN Player' },
  { value: 'messitv', label: 'Messi TV Player' },
  { value: 'hqplayer', label: 'HQ Player TV' },
];

const emptyDeviceForm = {
  panel: 'iboxx',
  panel_base_url: '',
  mac_address: '',
  device_key: '',
  label: '',
  playlist_name: 'Dispatcharr',
  include_epg: true,
  protect_pin: '',
};

// The panels' captcha SVGs are consistently invalid XML (the root <svg> tag
// carries duplicate width/height attributes, e.g.
// `<svg ... width="200" height="120" xmlns="..." width="150" height="50" ...>`).
// Browsers tolerate that when it's dumped into the live DOM via
// dangerouslySetInnerHTML (which is exactly what we don't want to do here —
// see the security note on <img> usage below), but a data:image/svg+xml
// resource must be well-formed XML or the <img> silently fails to render
// (naturalWidth/Height stay 0, no error is thrown). Route the markup through
// the browser's own lenient HTML parser first — it dedupes the attributes
// (first occurrence wins) — then re-serialize the cleaned, now well-formed
// SVG. The parsed document is never attached to the live page and is only
// used as an image resource afterwards, so this stays inert: SVG loaded via
// <img src="data:..."> cannot execute scripts or fetch external resources.
const svgToDataUri = (svg) => {
  try {
    const doc = new DOMParser().parseFromString(svg, 'text/html');
    const svgEl = doc.body.querySelector('svg');
    const cleaned = svgEl ? new XMLSerializer().serializeToString(svgEl) : svg;
    return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(cleaned)))}`;
  } catch {
    return null;
  }
};

const DeviceForm = ({ initial, onCancel, onSave }) => {
  const [values, setValues] = useState(initial || emptyDeviceForm);
  const [protectEnabled, setProtectEnabled] = useState(
    Boolean((initial || emptyDeviceForm).protect_pin)
  );
  const [saving, setSaving] = useState(false);

  const setField = (field, value) =>
    setValues((v) => ({ ...v, [field]: value }));

  const submit = async () => {
    setSaving(true);
    try {
      // Clear a leftover PIN if the admin toggled protection off rather
      // than sending a stale value the panel would silently keep using.
      await onSave({
        ...values,
        protect_pin: protectEnabled ? values.protect_pin : '',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack
      gap="xs"
      p="sm"
      style={{
        border: '1px solid var(--mantine-color-default-border)',
        borderRadius: 6,
      }}
    >
      <Group grow>
        <Select
          label="Panel"
          data={PANEL_OPTIONS}
          value={values.panel}
          onChange={(v) => setField('panel', v)}
        />
        <TextInput
          label="Base URL Override"
          description="Leave blank to use the panel's default domain"
          placeholder="https://sibling-domain.example.com"
          value={values.panel_base_url}
          onChange={(e) => setField('panel_base_url', e.target.value)}
        />
      </Group>
      <Group grow>
        <TextInput
          label="MAC Address"
          placeholder="AA:BB:CC:DD:EE:FF"
          value={values.mac_address}
          onChange={(e) => setField('mac_address', e.target.value)}
        />
        <TextInput
          label="Device Key"
          value={values.device_key}
          onChange={(e) => setField('device_key', e.target.value)}
        />
      </Group>
      <Group grow>
        <TextInput
          label="Label"
          placeholder="e.g. Living Room"
          value={values.label}
          onChange={(e) => setField('label', e.target.value)}
        />
        <TextInput
          label="Playlist Name"
          value={values.playlist_name}
          onChange={(e) => setField('playlist_name', e.target.value)}
        />
      </Group>
      <Switch
        label="Include EPG URL"
        checked={values.include_epg}
        onChange={(e) => setField('include_epg', e.currentTarget.checked)}
      />
      <Switch
        label="Protect Playlist with PIN"
        description="Mirrors the panel's own 'Protect Playlist' option — requires this PIN to view/edit the playlist on the panel"
        checked={protectEnabled}
        onChange={(e) => setProtectEnabled(e.currentTarget.checked)}
      />
      {protectEnabled && (
        <TextInput
          label="PIN"
          placeholder="e.g. 1234"
          value={values.protect_pin}
          onChange={(e) => setField('protect_pin', e.target.value)}
        />
      )}
      <Group justify="flex-end">
        <Button variant="subtle" size="xs" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button size="xs" onClick={submit} loading={saving}>
          Save
        </Button>
      </Group>
    </Stack>
  );
};

const PushCaptchaPanel = ({ device, onCancel, onSubmit }) => {
  const [svg, setSvg] = useState(null);
  const [captchaToken, setCaptchaToken] = useState(null);
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const loadCaptcha = async () => {
    setLoading(true);
    setAnswer('');
    const resp = await API.getMacPanelCaptcha(device.id);
    if (resp) {
      setSvg(resp.svg);
      setCaptchaToken(resp.captcha_token);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadCaptcha();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device.id]);

  const submit = async () => {
    setSubmitting(true);
    try {
      await onSubmit({ captcha: answer, captcha_token: captchaToken });
    } finally {
      setSubmitting(false);
    }
  };

  const dataUri = svg ? svgToDataUri(svg) : null;

  return (
    <Stack
      gap="xs"
      p="sm"
      style={{
        border: '1px solid var(--mantine-color-default-border)',
        borderRadius: 6,
      }}
    >
      <Text size="sm" fw={500}>
        Captcha required for {device.label || device.mac_address}
      </Text>
      {loading && <Text size="sm">Loading captcha…</Text>}
      {!loading && dataUri && (
        <Image src={dataUri} alt="Panel captcha" w={160} fit="contain" />
      )}
      <Group grow align="flex-end">
        <TextInput
          label="Captcha answer"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          disabled={loading}
        />
        <Button
          size="xs"
          variant="subtle"
          onClick={loadCaptcha}
          disabled={loading}
        >
          Refresh
        </Button>
      </Group>
      <Group justify="flex-end">
        <Button
          variant="subtle"
          size="xs"
          onClick={onCancel}
          disabled={submitting}
        >
          Cancel
        </Button>
        <Button
          size="xs"
          onClick={submit}
          loading={submitting}
          disabled={!answer || loading}
        >
          Submit &amp; Push
        </Button>
      </Group>
    </Stack>
  );
};

const MacDevices = ({ user, isOpen, onClose }) => {
  const devices = useMacDevicesStore((s) => s.devices);
  const [loading, setLoading] = useState(false);
  const [editingDevice, setEditingDevice] = useState(undefined); // undefined = none, null = new, obj = editing
  const [pushingDeviceId, setPushingDeviceId] = useState(null);
  const [captchaDevice, setCaptchaDevice] = useState(null);
  const [pushResult, setPushResult] = useState(null); // { deviceId, success, message }

  useEffect(() => {
    if (isOpen && user?.id) {
      setLoading(true);
      API.getMacDevices(user.id).finally(() => setLoading(false));
      setEditingDevice(undefined);
      setCaptchaDevice(null);
      setPushResult(null);
    }
  }, [isOpen, user?.id]);

  if (!isOpen || !user) {
    return null;
  }

  const allowedNetworks = user?.custom_properties?.allowed_networks;
  const hasNetworkRestriction =
    allowedNetworks &&
    (Array.isArray(allowedNetworks) ? allowedNetworks.length > 0 : true);

  const refresh = () => API.getMacDevices(user.id);

  const handleSaveDevice = async (values) => {
    const payload = { ...values, user: user.id };
    if (editingDevice && editingDevice.id) {
      await API.updateMacDevice(editingDevice.id, payload);
    } else {
      await API.createMacDevice(payload);
    }
    setEditingDevice(undefined);
  };

  const handleDeleteDevice = async (device) => {
    await API.deleteMacDevice(device.id);
  };

  const startPush = async (device) => {
    setPushResult(null);
    setPushingDeviceId(device.id);
    const resp = await API.pushMacDevice(device.id);
    setPushingDeviceId(null);
    if (!resp) {
      return; // errorNotification already shown
    }
    if (resp.captchaRequired) {
      setCaptchaDevice(device);
      return;
    }
    setPushResult({
      deviceId: device.id,
      success: true,
      message: resp.message,
    });
    refresh();
  };

  const submitCaptchaPush = async ({ captcha, captcha_token }) => {
    const device = captchaDevice;
    const resp = await API.pushMacDevice(device.id, { captcha, captcha_token });
    if (!resp) {
      return;
    }
    if (resp.captchaRequired) {
      // Wrong answer or expired token — let the panel handle a fresh captcha.
      setPushResult({
        deviceId: device.id,
        success: false,
        message: 'Captcha rejected, try again.',
      });
      return;
    }
    setCaptchaDevice(null);
    setPushResult({
      deviceId: device.id,
      success: true,
      message: resp.message,
    });
    refresh();
  };

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={`MAC Devices — ${user.username}`}
      size="lg"
    >
      <Stack gap="sm">
        {hasNetworkRestriction && (
          <Alert
            icon={<AlertTriangle size={16} />}
            color="yellow"
            title="Network restriction in effect"
          >
            This user has an IP/network restriction configured. Pushing
            credentials to a MAC panel does not bypass it — the customer's
            device may still be blocked at playback time even after a successful
            push.
          </Alert>
        )}

        {loading && <Text size="sm">Loading devices…</Text>}

        {!loading && devices.length === 0 && (
          <Text size="sm" c="dimmed">
            No MAC devices yet for this user.
          </Text>
        )}

        {!loading &&
          devices.map((device) => (
            <Stack
              key={device.id}
              gap={4}
              p="xs"
              style={{
                border: '1px solid var(--mantine-color-default-border)',
                borderRadius: 6,
              }}
            >
              <Group justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="wrap">
                  <Badge size="sm" color="gray">
                    {PANEL_OPTIONS.find((p) => p.value === device.panel)
                      ?.label || device.panel}
                  </Badge>
                  <Text size="sm" style={{ fontFamily: 'monospace' }}>
                    {device.mac_address}
                  </Text>
                  {device.label && (
                    <Text size="sm" c="dimmed">
                      {device.label}
                    </Text>
                  )}
                  {device.protect_pin && (
                    <Badge size="sm" color="yellow" variant="light">
                      PIN Protected
                    </Badge>
                  )}
                </Group>
                <Group gap={4} wrap="nowrap">
                  <ActionIcon
                    size="sm"
                    variant="transparent"
                    onClick={() => startPush(device)}
                    loading={pushingDeviceId === device.id}
                    title="Push credentials"
                  >
                    <Send size={16} />
                  </ActionIcon>
                  <ActionIcon
                    size="sm"
                    variant="transparent"
                    onClick={() => setEditingDevice(device)}
                    title="Edit device"
                  >
                    <SquarePen size={16} />
                  </ActionIcon>
                  <ActionIcon
                    size="sm"
                    variant="transparent"
                    color="red"
                    onClick={() => handleDeleteDevice(device)}
                    title="Delete device"
                  >
                    <SquareMinus size={16} />
                  </ActionIcon>
                </Group>
              </Group>
              <Text size="xs" c="dimmed">
                {device.last_pushed_at
                  ? `Last push: ${device.last_push_status} — ${device.last_push_message} (${device.last_pushed_at})`
                  : 'Never pushed'}
              </Text>

              {captchaDevice?.id === device.id && (
                <PushCaptchaPanel
                  device={device}
                  onCancel={() => setCaptchaDevice(null)}
                  onSubmit={submitCaptchaPush}
                />
              )}

              {pushResult?.deviceId === device.id && !captchaDevice && (
                <Alert
                  color={pushResult.success ? 'green' : 'red'}
                  variant="light"
                  p="xs"
                >
                  {pushResult.message}
                </Alert>
              )}

              {editingDevice?.id === device.id && (
                <DeviceForm
                  initial={editingDevice}
                  onCancel={() => setEditingDevice(undefined)}
                  onSave={handleSaveDevice}
                />
              )}
            </Stack>
          ))}

        <Divider />

        {editingDevice === null ? (
          <DeviceForm
            initial={null}
            onCancel={() => setEditingDevice(undefined)}
            onSave={handleSaveDevice}
          />
        ) : (
          <Button
            leftSection={<SquarePlus size={16} />}
            variant="light"
            size="xs"
            onClick={() => setEditingDevice(null)}
          >
            Add Device
          </Button>
        )}

        <Group justify="flex-end">
          <Button
            leftSection={<X size={14} />}
            variant="subtle"
            onClick={onClose}
          >
            Close
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default MacDevices;
