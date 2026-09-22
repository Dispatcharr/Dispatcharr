import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../api', () => ({
  default: {
    searchVODCanonicalTargets: vi.fn(),
    updateVODRelationManualMetadata: vi.fn(),
    updateVODRelationTmdbMatch: vi.fn(),
  },
}));
vi.mock('../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../LanguagePicker.jsx', () => ({
  default: ({ label, value = [], onChange }) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value.join(',')}
        onChange={(event) =>
          onChange(event.target.value.split(',').filter(Boolean))
        }
      />
    </label>
  ),
}));
vi.mock('../VideoFeaturePicker.jsx', () => ({
  default: ({ label, value = [], onChange }) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value.join(',')}
        onChange={(event) =>
          onChange(event.target.value.split(',').filter(Boolean))
        }
      />
    </label>
  ),
}));
vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  return {
    Alert: Wrapper,
    Button: ({ children, onClick, disabled, loading }) => (
      <button onClick={onClick} disabled={disabled || loading}>
        {children}
      </button>
    ),
    Group: Wrapper,
    Modal: ({ opened, children, title }) =>
      opened ? (
        <div>
          <h2>{title}</h2>
          {children}
        </div>
      ) : null,
    SegmentedControl: () => null,
    Select: ({ label, value, onChange, data = [] }) => (
      <label>
        {label}
        <select
          aria-label={label}
          value={value || ''}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="" />
          {data.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
    ),
    Stack: Wrapper,
    Text: Wrapper,
    TextInput: ({ label, description, value, onChange }) => (
      <label>
        {label}
        <input aria-label={label} value={value} onChange={onChange} />
        <span>{description}</span>
      </label>
    ),
  };
});

import API from '../../api';
import VODSourceMetadataModal from '../VODSourceMetadataModal.jsx';

const provider = {
  id: 51,
  m3u_account: { name: 'Provider' },
  category: { name: 'Movies' },
  movie: {
    id: 12,
    name: 'Current movie',
    display_name: 'Current movie',
    clean_title: 'Clean current movie',
    year: 2020,
    tmdb_match_id: '123',
    tmdb_id: '123',
  },
  source_metadata: {
    values: {
      audio_languages: ['ger'],
      subtitle_languages: ['eng'],
      resolution: '1080p',
      container_extension: 'mkv',
      video_features: ['hdr'],
    },
    provenance: {
      audio_languages: 'category',
      subtitle_languages: 'observed',
      resolution: 'provider',
      container_extension: 'relation',
      video_features: 'observed',
    },
  },
};

describe('VODSourceMetadataModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.updateVODRelationManualMetadata.mockResolvedValue({
      source_metadata: {
        values: {
          audio_languages: ['ger'],
          subtitle_languages: ['ger'],
          resolution: '1080p',
          container_extension: 'mkv',
          video_features: ['hdr'],
        },
        provenance: { subtitle_languages: 'manual' },
      },
    });
    API.updateVODRelationTmdbMatch.mockResolvedValue({ moved_sources: 1 });
    API.searchVODCanonicalTargets.mockResolvedValue({ results: [] });
  });

  it('prefills effective metadata but keeps provider format read-only', async () => {
    const onSaved = vi.fn();
    render(
      <VODSourceMetadataModal
        provider={provider}
        contentType="movie"
        opened
        onClose={vi.fn()}
        onSaved={onSaved}
      />
    );

    expect(screen.getByLabelText('DUB languages')).toHaveValue('ger');
    expect(screen.getByLabelText('SUB languages')).toHaveValue('eng');
    expect(screen.getByLabelText('Resolution')).toHaveValue('1080p');
    expect(screen.getByLabelText('Video features')).toHaveValue('hdr');
    expect(screen.getByLabelText('Canonical title')).toHaveValue(
      'Clean current movie'
    );
    expect(screen.queryByLabelText('Format')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Edit' })).toBeInTheDocument();
    expect(
      screen.getByText(/Current: Current movie · TMDB 123/)
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('SUB languages'), {
      target: { value: 'ger' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save and lock' }));

    await waitFor(() =>
      expect(API.updateVODRelationManualMetadata).toHaveBeenCalledWith(
        'movie',
        51,
        {
          audio_languages: ['ger'],
          subtitle_languages: ['ger'],
          resolution: '1080p',
          video_features: ['hdr'],
        },
        [
          'audio_languages',
          'subtitle_languages',
          'resolution',
          'video_features',
        ]
      )
    );
    expect(onSaved).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 51,
        source_metadata: expect.objectContaining({
          provenance: { subtitle_languages: 'manual' },
        }),
      })
    );
  });

  it('searches and moves only this source to an existing canonical title', async () => {
    API.searchVODCanonicalTargets.mockResolvedValueOnce({
      results: [
        {
          id: 88,
          title: 'Avatar: The Way of Water',
          year: 2022,
          tmdb_id: '76600',
          source_count: 3,
        },
      ],
    });
    render(
      <VODSourceMetadataModal
        provider={provider}
        contentType="movie"
        opened
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onMoved={vi.fn()}
      />
    );

    fireEvent.change(screen.getByLabelText('Canonical title'), {
      target: { value: 'Avatar' },
    });
    fireEvent.change(screen.getByLabelText('Year'), {
      target: { value: '2022' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Use' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Move, save and lock' })
    );

    await waitFor(() =>
      expect(API.updateVODRelationTmdbMatch).toHaveBeenCalledWith(
        { target_id: 88 },
        [{ content_type: 'movie', relation_id: 51 }],
        { confirmed: false }
      )
    );
  });

  it('warns before changing an enriched assignment and confirms once', async () => {
    API.searchVODCanonicalTargets.mockResolvedValueOnce({
      results: [
        {
          id: 88,
          title: 'Avatar',
          year: 2022,
          tmdb_id: '76600',
          source_count: 3,
        },
      ],
    });
    API.updateVODRelationTmdbMatch.mockRejectedValueOnce({
      status: 409,
      body: {
        requires_confirmation: true,
        previously_enriched_sources: 1,
      },
    });
    const onMoved = vi.fn();
    render(
      <VODSourceMetadataModal
        provider={provider}
        contentType="movie"
        opened
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onMoved={onMoved}
      />
    );

    fireEvent.change(screen.getByLabelText('Canonical title'), {
      target: { value: 'Avatar' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Use' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Move, save and lock' })
    );

    expect(
      await screen.findByText(/Metadata has already been stored/)
    ).toBeInTheDocument();
    expect(API.updateVODRelationManualMetadata).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Move source' }));

    await waitFor(() =>
      expect(API.updateVODRelationTmdbMatch).toHaveBeenLastCalledWith(
        { target_id: 88 },
        [{ content_type: 'movie', relation_id: 51 }],
        { confirmed: true }
      )
    );
    expect(API.updateVODRelationManualMetadata).toHaveBeenCalledTimes(1);
    expect(onMoved).toHaveBeenCalledWith({ moved_sources: 1 });
  });

  it('creates a new canonical title from provider data when no local title matches', async () => {
    render(
      <VODSourceMetadataModal
        provider={provider}
        contentType="movie"
        opened
        onClose={vi.fn()}
        onSaved={vi.fn()}
        onMoved={vi.fn()}
      />
    );

    fireEvent.change(screen.getByLabelText('Canonical title'), {
      target: { value: 'Unlisted title' },
    });
    fireEvent.change(screen.getByLabelText('Year'), {
      target: { value: '2026' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Create from provider' })
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Move, save and lock' })
    );

    await waitFor(() =>
      expect(API.updateVODRelationTmdbMatch).toHaveBeenCalledWith(
        { create_from_provider: true },
        [{ content_type: 'movie', relation_id: 51 }],
        { confirmed: false }
      )
    );
  });
});
