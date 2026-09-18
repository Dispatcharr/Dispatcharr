import React from 'react';
import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import VODSourceList from '../VODSourceList.jsx';

const provider = {
  id: 17,
  stream_id: '607403',
  external_series_id: 'series-17',
  container_extension: 'mkv',
  m3u_account: { name: 'Provider A' },
  category: { name: 'German movies' },
  movie: { name: 'Example movie' },
  series: { name: 'Example series' },
  source_metadata: {
    values: {
      audio_languages: ['ger'],
      subtitle_languages: ['eng'],
      resolution: '1080p',
      container_extension: 'mkv',
      bitrate_kbps: 13706,
      file_size_bytes: 1500000000,
      video_codec: 'hevc',
      audio_codec: 'eac3',
      frame_rate: '24000/1001',
      episode_resolutions: ['720p', '1080p'],
      episode_video_codecs: ['h264', 'hevc'],
    },
  },
};

describe('VODSourceList', () => {
  const renderList = (contentType) =>
    render(
      <MantineProvider>
        <VODSourceList
          providers={[provider]}
          selectedProvider={provider}
          contentType={contentType}
        />
      </MantineProvider>
    );

  it('shows movie languages and known detailed technical metadata separately', () => {
    renderList('movie');

    expect(screen.getByRole('columnheader', { name: 'DUB' })).toBeVisible();
    expect(screen.getByRole('columnheader', { name: 'SUB' })).toBeVisible();
    expect(screen.getByText('GER')).toBeVisible();
    expect(screen.getByText('ENG')).toBeVisible();
    expect(screen.getByText('13.7 Mbps')).toBeVisible();
    expect(screen.getByText('1.5 GB')).toBeVisible();
    expect(screen.getByText('HEVC')).toBeVisible();
    expect(screen.getByText('EAC3')).toBeVisible();
    expect(screen.getByText('23.98 FPS')).toBeVisible();
  });

  it('summarizes episode video facts without showing a series container', () => {
    renderList('series');

    expect(screen.getByRole('columnheader', { name: 'Codec' })).toBeVisible();
    expect(screen.getByText('720p')).toBeVisible();
    expect(screen.getByText('1080p')).toBeVisible();
    expect(screen.getByText('H264')).toBeVisible();
    expect(screen.getByText('HEVC')).toBeVisible();
    expect(screen.queryByText('MKV')).not.toBeInTheDocument();
  });

  it('reuses the exact source table for profile order and exclusions', () => {
    const excluded = {
      ...provider,
      id: 18,
      stream_id: '607404',
      m3u_account: { name: 'Provider B' },
      movie: { name: 'Excluded edition' },
    };
    render(
      <MantineProvider>
        <VODSourceList
          providers={[excluded, provider]}
          selectedProvider={provider}
          contentType="movie"
          profileCandidates={{
            results: [
              {
                relation_id: provider.id,
                allowed: true,
                position: 1,
                selected: true,
                reason: 'eligible',
              },
              {
                relation_id: excluded.id,
                allowed: false,
                position: null,
                selected: false,
                reason: 'source_rule_exclude',
              },
            ],
          }}
        />
      </MantineProvider>
    );

    expect(screen.getByRole('columnheader', { name: 'Order' })).toBeVisible();
    expect(screen.getByText('#1')).toBeVisible();
    expect(screen.queryByText('Preferred')).not.toBeInTheDocument();
    expect(screen.getByText('Excluded')).toBeVisible();
    expect(screen.getByText('source rule exclude')).toBeVisible();
  });
});
