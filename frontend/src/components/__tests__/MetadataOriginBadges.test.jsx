import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it } from 'vitest';
import MetadataOriginBadges, {
  MetadataOriginLegend,
} from '../MetadataOriginBadges.jsx';
import { sourceMetadataOrigins } from '../../utils/libraryMetadataOrigins.js';

const renderUI = (element) =>
  render(<MantineProvider env="test">{element}</MantineProvider>);

describe('metadata origin badges', () => {
  it('labels each value with its origin and shows a dash without values', () => {
    renderUI(
      <>
        <MetadataOriginBadges
          field="audio_languages"
          origins={{ audio_languages: { eng: 'category', ger: 'manual' } }}
        />
        <MetadataOriginBadges field="video_features" origins={{}} />
        <MetadataOriginLegend />
      </>
    );
    expect(screen.getByLabelText('eng · Category default')).toBeInTheDocument();
    expect(screen.getByLabelText('ger · Manual')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    const legend = screen.getByLabelText('Metadata origins');
    expect(legend).toHaveTextContent('Category default');
    expect(legend).toHaveTextContent('Manual');
    expect(legend).not.toHaveTextContent('Detected during playback');
  });

  it('lets provider episode resolutions replace only an inherited value', () => {
    const source = (provenance) => ({
      effective_metadata: {
        values: { resolution: '1080p', audio_languages: ['eng'] },
        provenance: { resolution: provenance, audio_languages: 'category' },
      },
      provider: { technical: { episode_resolutions: ['720p'] } },
    });
    expect(sourceMetadataOrigins(source('category'), true)).toEqual({
      resolution: { '720p': 'provider' },
      audio_languages: { eng: 'category' },
    });
    expect(sourceMetadataOrigins(source('manual'), true).resolution).toEqual({
      '1080p': 'manual',
    });
    expect(sourceMetadataOrigins(source('category')).resolution).toEqual({
      '1080p': 'category',
    });
  });
});
