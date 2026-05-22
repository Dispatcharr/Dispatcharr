import React, { useState } from 'react';
import { Box, Button, Group } from '@mantine/core';
import { formatKB } from '../../utils/networkUtils.js';

const SizedInstallButton = ({
  latest_size,
  children,
  color,
  loading,
  disabled,
  onClick,
  ...buttonProps
}) => {
  const [hovered, setHovered] = useState(false);
  if (!Number.isFinite(latest_size) || latest_size <= 0) {
    return (
      <Button
        color={color}
        loading={loading}
        disabled={disabled}
        onClick={onClick}
        {...buttonProps}
      >
        {children}
      </Button>
    );
  }
  const isDisabled = disabled || loading;
  const colorVar = color
    ? `var(--mantine-color-${color}-filled)`
    : 'var(--mantine-primary-color-filled)';
  return (
    <Group
      gap={0}
      align="stretch"
      wrap="nowrap"
      onMouseEnter={() => {
        if (!isDisabled) setHovered(true);
      }}
      onMouseLeave={() => setHovered(false)}
    >
      <Button
        color={color}
        loading={loading}
        disabled={disabled}
        onClick={onClick}
        styles={
          hovered && !isDisabled
            ? {
                root: {
                  background: color
                    ? `var(--mantine-color-${color}-filled-hover)`
                    : 'var(--mantine-primary-color-filled-hover)',
                },
              }
            : undefined
        }
        {...buttonProps}
        style={{ borderTopRightRadius: 0, borderBottomRightRadius: 0 }}
      >
        {children}
      </Button>
      <Box
        onClick={!isDisabled ? onClick : undefined}
        style={{
          background: isDisabled
            ? colorVar
            : hovered
              ? color
                ? `var(--mantine-color-${color}-filled-hover)`
                : 'var(--mantine-primary-color-filled-hover)'
              : colorVar,
          filter: isDisabled
            ? 'brightness(0.65) saturate(0.7)'
            : hovered
              ? 'brightness(0.86)'
              : 'brightness(0.82)',
          borderLeft: '1px solid rgba(0,0,0,0.2)',
          borderTopRightRadius: 'var(--mantine-radius-sm)',
          borderBottomRightRadius: 'var(--mantine-radius-sm)',
          display: 'flex',
          alignItems: 'center',
          padding: '0 9px',
          fontSize: 11,
          color: '#fff',
          cursor: isDisabled ? 'default' : 'pointer',
          userSelect: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        {formatKB(latest_size)}
      </Box>
    </Group>
  );
};

export default SizedInstallButton;
