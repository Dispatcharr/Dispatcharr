import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';

import VODFailoverRanking from '../VODFailoverRanking';
import { normalizeVODFailoverRanking } from '../../utils/vodFailoverRanking';

describe('VODFailoverRanking', () => {
  it('migrates the legacy resolution criterion to highest first', () => {
    expect(normalizeVODFailoverRanking(['resolution'])).toEqual([
      'resolution_desc',
      'audio_language',
      'subtitle_language',
      'provider',
      'metadata_completeness',
    ]);
  });

  it('keeps lowest first as the only resolution direction', () => {
    expect(
      normalizeVODFailoverRanking([
        'audio_language',
        'resolution_asc',
        'metadata_completeness',
      ])
    ).toEqual([
      'audio_language',
      'resolution_asc',
      'metadata_completeness',
      'subtitle_language',
      'provider',
    ]);
  });

  it('drops old bitrate criteria because source detail coverage is sparse', () => {
    expect(
      normalizeVODFailoverRanking([
        'bitrate_asc',
        'audio_language',
        'metadata_completeness',
      ])
    ).toEqual([
      'audio_language',
      'metadata_completeness',
      'subtitle_language',
      'provider',
      'resolution_desc',
    ]);
  });

  it('shows and reorders the profile-specific provider preference', () => {
    const onProviderOrderChange = vi.fn();
    render(
      <MantineProvider>
        <VODFailoverRanking
          value={['provider']}
          onChange={vi.fn()}
          providerOrder={['11', '7']}
          providerOptions={[
            { value: '11', label: 'Provider One' },
            { value: '7', label: 'Provider Two' },
          ]}
          onProviderOrderChange={onProviderOrderChange}
        />
      </MantineProvider>
    );

    expect(screen.getByText('Provider One')).toBeInTheDocument();
    expect(screen.getByText('Provider Two')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Move Provider Two up' })
    );

    expect(onProviderOrderChange).toHaveBeenCalledWith(['7', '11']);
  });

  it('can disable a ranking criterion without removing its position', () => {
    const onDisabledChange = vi.fn();
    render(
      <MantineProvider>
        <VODFailoverRanking
          value={['audio_language', 'provider']}
          onChange={vi.fn()}
          disabled={[]}
          onDisabledChange={onDisabledChange}
        />
      </MantineProvider>
    );

    fireEvent.click(
      screen.getByRole('switch', {
        name: 'Enable DUB language preference',
      })
    );
    expect(onDisabledChange).toHaveBeenCalledWith(['audio_language']);
  });
});
