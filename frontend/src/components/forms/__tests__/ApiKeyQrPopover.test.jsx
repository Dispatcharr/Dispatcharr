import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Render the real QR code, but record the props it was given so the encoded
// payload can be asserted on (it is not recoverable from the SVG itself).
const qrProps = vi.hoisted(() => []);

vi.mock('qrcode.react', async (importOriginal) => {
  const actual = await importOriginal();
  const { createElement } = await import('react');
  return {
    ...actual,
    QRCodeSVG: (props) => {
      qrProps.push(props);
      return createElement(actual.QRCodeSVG, props);
    },
  };
});

vi.mock('../../../store/settings', () => ({ default: vi.fn() }));
vi.mock('../../../images/logo.png', () => ({
  default: 'dispatcharr-logo.png',
}));

import useSettingsStore from '../../../store/settings';
import ApiKeyQrPopover from '../ApiKeyQrPopover';

const API_KEY = 'k'.repeat(54);
const QR_LABEL = 'QR code containing the API key';

const user = {
  username: 'user1',
  first_name: 'Ada',
  last_name: 'Lovelace',
  email: 'ada@example.com',
};

const setEnvMode = (envMode) => {
  vi.mocked(useSettingsStore).mockImplementation((selector) =>
    selector({ environment: { env_mode: envMode } })
  );
};

// env="test" renders the popover in place and skips transitions.
const renderPopover = (props = {}) =>
  render(
    <MantineProvider env="test">
      <ApiKeyQrPopover apiKey={API_KEY} user={user} {...props} />
    </MantineProvider>
  );

const open = () =>
  fireEvent.click(screen.getByLabelText('Show API key QR code'));

const lastPayload = () => JSON.parse(qrProps[qrProps.length - 1].value);

describe('ApiKeyQrPopover', () => {
  beforeEach(() => {
    qrProps.length = 0;
    vi.clearAllMocks();
    setEnvMode('aio');
  });

  it('does not generate a QR code until opened', () => {
    renderPopover();

    expect(screen.getByLabelText('Show API key QR code')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: QR_LABEL })).toBeNull();
    expect(qrProps).toHaveLength(0);
  });

  it('renders a real SVG QR code with the logo when opened', async () => {
    renderPopover();
    open();

    const svg = await screen.findByRole('img', { name: QR_LABEL });
    expect(svg.tagName.toLowerCase()).toBe('svg');
    expect(svg.querySelector('path')).not.toBeNull();

    const image = svg.querySelector('image');
    expect(image).not.toBeNull();
    expect(image.getAttribute('href')).toBe('dispatcharr-logo.png');
    expect(screen.getByText('Scan API Key')).toBeInTheDocument();
  });

  it('encodes the versioned user_api_key payload', async () => {
    renderPopover();
    open();
    await screen.findByRole('img', { name: QR_LABEL });

    expect(lastPayload()).toEqual({
      v: 1,
      type: 'user_api_key',
      api_key: API_KEY,
      base_url: `${window.location.protocol}//${window.location.host}`,
      username: 'user1',
      first_name: 'Ada',
      last_name: 'Lovelace',
      email: 'ada@example.com',
    });
  });

  it('uses the backend port as base_url in dev mode', async () => {
    setEnvMode('dev');
    renderPopover();
    open();
    await screen.findByRole('img', { name: QR_LABEL });

    expect(lastPayload().base_url).toBe(
      `${window.location.protocol}//${window.location.hostname}:5656`
    );
  });

  it('keeps the error correction and logo settings that make it scannable', async () => {
    renderPopover();
    open();
    await screen.findByRole('img', { name: QR_LABEL });

    const props = qrProps[qrProps.length - 1];
    expect(props.level).toBe('H');
    expect(props.imageSettings).toMatchObject({
      src: 'dispatcharr-logo.png',
      excavate: true,
    });
    // A white background is required for the quiet zone on the dark popover.
    expect(props.bgColor).toBe('#ffffff');
    expect(props.marginSize).toBe(4);
  });

  it('tolerates a missing user and still encodes the key', async () => {
    renderPopover({ user: null });
    open();
    await screen.findByRole('img', { name: QR_LABEL });

    expect(lastPayload()).toMatchObject({
      type: 'user_api_key',
      api_key: API_KEY,
      username: '',
      first_name: '',
      last_name: '',
      email: '',
    });
  });

  // Regression: long non-ASCII names used to exceed what a QR code can hold at
  // this error correction level, which made the renderer throw while the form
  // (which is always mounted in the sidebar) was rendering.
  it('renders instead of throwing when identity fields are huge', async () => {
    renderPopover({
      user: {
        username: 'u'.repeat(150),
        first_name: '名'.repeat(150),
        last_name: '姓'.repeat(150),
        email: `${'e'.repeat(240)}@example.com`,
      },
    });
    open();

    expect(await screen.findByRole('img', { name: QR_LABEL })).toBeTruthy();
    expect(lastPayload()).toMatchObject({
      api_key: API_KEY,
      username: '',
      first_name: '',
      last_name: '',
      email: '',
    });
  });

  it('closes when the button is clicked again', async () => {
    renderPopover();
    open();
    await screen.findByRole('img', { name: QR_LABEL });

    open();

    await waitFor(() => {
      expect(screen.queryByRole('img', { name: QR_LABEL })).toBeNull();
    });
  });

  it('updates the code when the key changes while open', async () => {
    const { rerender } = renderPopover();
    open();
    await screen.findByRole('img', { name: QR_LABEL });

    rerender(
      <MantineProvider env="test">
        <ApiKeyQrPopover apiKey="regenerated-key" user={user} />
      </MantineProvider>
    );

    await waitFor(() => {
      expect(lastPayload().api_key).toBe('regenerated-key');
    });
  });
});
