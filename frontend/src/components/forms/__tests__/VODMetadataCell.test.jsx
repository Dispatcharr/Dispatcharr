import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it } from 'vitest';
import VODMetadataCell from '../VODMetadataCell.jsx';
import classes from '../VODMetadataCell.module.css';

const renderCell = (props) =>
  render(
    <MantineProvider env="test">
      <VODMetadataCell {...props} />
    </MantineProvider>
  );

describe('compact metadata tags', () => {
  it('shows each language as a read-only tag with the complete list in its tooltip', () => {
    renderCell({
      values: { audio_languages: ['ger', 'eng', 'fre'] },
      field: 'audio_languages',
    });
    for (const code of ['ger', 'eng', 'fre']) {
      expect(
        screen.getByText(code).closest('.mantine-Badge-root')
      ).not.toBeNull();
    }
    expect(screen.getByTitle('ger, eng, fre')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('shows feature tags without a separate editable field frame', () => {
    renderCell({
      values: { video_features: ['dv', 'hdr', 'custom:imax'] },
      field: 'video_features',
    });
    for (const tag of ['Dolby Vision', 'HDR', 'imax'])
      expect(screen.getByText(tag)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByTitle('Dolby Vision, HDR, imax')).toBeInTheDocument();
  });

  it('preserves explicit empty values without adding an interactive frame', () => {
    renderCell({
      values: { audio_languages: [] },
      field: 'audio_languages',
      emptyLabel: 'None',
    });
    expect(screen.getByText('None')).toBeInTheDocument();
    expect(screen.getByTitle('Explicitly empty default')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('uses the same fixed-size class for every DUB and SUB language tag', () => {
    render(
      <MantineProvider env="test">
        <VODMetadataCell
          values={{ audio_languages: ['ger', 'eng', 'fre'] }}
          field="audio_languages"
        />
        <VODMetadataCell
          values={{ subtitle_languages: ['jpn', 'ara'] }}
          field="subtitle_languages"
        />
      </MantineProvider>
    );
    for (const code of ['ger', 'eng', 'fre', 'jpn', 'ara']) {
      expect(screen.getByText(code).closest('.mantine-Badge-root')).toHaveClass(
        classes.languageTag
      );
    }
  });
});
