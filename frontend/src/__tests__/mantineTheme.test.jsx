import { render, screen } from '@testing-library/react';
import {
  Checkbox,
  CheckboxIndicator,
  DEFAULT_THEME,
  MantineProvider,
  useMantineTheme,
} from '@mantine/core';
import { describe, expect, it } from 'vitest';
import theme from '../mantineTheme.jsx';

const RadiusProbe = () => {
  const current = useMantineTheme();
  return (
    <>
      <output aria-label="Default radius">{current.defaultRadius}</output>
      <output aria-label="Surface radius">
        {current.radius[current.defaultRadius]}
      </output>
      <output aria-label="Small control radius">{current.radius.xs}</output>
      <output aria-label="Pill radius">{current.radius.xl}</output>
    </>
  );
};

describe('shared surface rounding', () => {
  it('uses the existing M3U account card radius as the app default', () => {
    render(
      <MantineProvider theme={theme}>
        <RadiusProbe />
      </MantineProvider>
    );
    expect(screen.getByLabelText('Default radius')).toHaveTextContent('md');
    expect(screen.getByLabelText('Surface radius')).toHaveTextContent(
      DEFAULT_THEME.radius.md
    );
  });

  it('preserves the radius scale for small controls and rounded pills', () => {
    render(
      <MantineProvider theme={theme}>
        <RadiusProbe />
      </MantineProvider>
    );
    expect(screen.getByLabelText('Small control radius')).toHaveTextContent(
      DEFAULT_THEME.radius.xs
    );
    expect(screen.getByLabelText('Pill radius')).toHaveTextContent(
      DEFAULT_THEME.radius.xl
    );
  });

  it('keeps checkboxes distinct from round radio buttons', () => {
    render(
      <MantineProvider theme={theme}>
        <Checkbox label="Select item" />
        <CheckboxIndicator data-testid="selection-indicator" />
      </MantineProvider>
    );
    expect(
      screen
        .getByRole('checkbox', { name: 'Select item' })
        .closest('.mantine-Checkbox-root')
        .style.getPropertyValue('--checkbox-radius')
    ).toBe('var(--mantine-radius-sm)');
    expect(
      screen
        .getByTestId('selection-indicator')
        .style.getPropertyValue('--checkbox-radius')
    ).toBe('var(--mantine-radius-sm)');
  });
});
