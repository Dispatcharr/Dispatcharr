import React from 'react';
import { Box, Text } from '@mantine/core';
import { AlertTriangle, Info, OctagonAlert } from 'lucide-react';
import dispatcharrLogo from '../images/logo.png';

// Shared chrome for every plugin note/warning box: colored background,
// matching border, a top-aligned icon, and small colored text. Each
// exported variant below is just this shell with a fixed tone/icon, so
// adding a new tone never means copy-pasting the box styling again.
const TONES = {
  danger: {
    background: 'rgba(239, 68, 68, 0.1)',
    border: 'rgba(239, 68, 68, 0.35)',
    iconColor: '#ef4444',
    textColor: '#f87171',
  },
  support: {
    background: 'rgba(20, 145, 126, 0.1)',
    border: 'rgba(20, 145, 126, 0.35)',
    iconColor: undefined,
    textColor: '#4db8a8',
  },
  caution: {
    background: 'rgba(249, 115, 22, 0.1)',
    border: 'rgba(249, 115, 22, 0.35)',
    iconColor: '#f97316',
    textColor: '#fb923c',
  },
  info: {
    background: 'rgba(148, 163, 184, 0.08)',
    border: 'rgba(148, 163, 184, 0.25)',
    iconColor: '#94a3b8',
    textColor: '#cbd5e1',
  },
  restart: {
    background: 'rgba(234, 179, 8, 0.1)',
    border: 'rgba(234, 179, 8, 0.35)',
    iconColor: '#eab308',
    textColor: '#ca8a04',
  },
};

export const PluginWarningBox = ({ tone, icon, children }) => {
  const { background, border, iconColor, textColor } = TONES[tone];
  return (
    <Box
      style={{
        background,
        border: `1px solid ${border}`,
        borderRadius: 'var(--mantine-radius-sm)',
        padding: '10px 14px',
        display: 'flex',
        gap: 10,
        alignItems: 'flex-start',
      }}
    >
      <Box style={{ color: iconColor, flexShrink: 0, paddingTop: 1 }}>
        {icon}
      </Box>
      <Text size="xs" style={{ color: textColor }}>
        {children}
      </Text>
    </Box>
  );
};

export const PluginSecurityWarning = ({ children }) => (
  <PluginWarningBox tone="danger" icon={<OctagonAlert size={16} />}>
    {children}
  </PluginWarningBox>
);

export const PluginSupportDisclaimer = () => (
  <PluginWarningBox
    tone="support"
    icon={
      <img
        src={dispatcharrLogo}
        alt="Dispatcharr"
        width={16}
        height={16}
        draggable={false}
        style={{ display: 'block', objectFit: 'contain' }}
      />
    }
  >
    Dispatcharr community support cannot assist with third-party plugin
    issues. For help, use the plugin&apos;s Discord thread or submit an issue
    on the plugin&apos;s repository.
  </PluginWarningBox>
);

export const PluginDowngradeWarning = ({ children }) => (
  <PluginWarningBox tone="caution" icon={<AlertTriangle size={16} />}>
    {children}
  </PluginWarningBox>
);

export const PluginInfoNote = ({ children }) => (
  <PluginWarningBox tone="info" icon={<Info size={16} />}>
    {children}
  </PluginWarningBox>
);

// Message defaults to the import-restart notice; pass children to describe
// a different restart trigger (e.g. a newly granted plugin capability)
// without duplicating the box styling.
export const PluginRestartWarning = ({ children }) => (
  <PluginWarningBox tone="restart" icon={<AlertTriangle size={16} />}>
    {children || (
      <>
        Importing a plugin may briefly restart the backend (you might see a
        temporary disconnect). Please wait a few seconds and the app will
        reconnect automatically.
      </>
    )}
  </PluginWarningBox>
);
