import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../api.js', () => ({
  default: {
    getVODAccessPolicyCandidates: vi.fn(),
  },
}));

vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  return {
    Alert: Wrapper,
    Badge: Wrapper,
    Button: ({ children, onClick, loading }) => (
      <button disabled={loading} onClick={onClick}>
        {children}
      </button>
    ),
    Group: Wrapper,
    Loader: () => <div>Loading</div>,
    Modal: ({ opened, title, children }) =>
      opened ? (
        <div>
          <h2>{title}</h2>
          {children}
        </div>
      ) : null,
    ScrollArea: Wrapper,
    Stack: Wrapper,
    Table: Wrapper,
    TableTbody: Wrapper,
    TableTd: Wrapper,
    TableTh: Wrapper,
    TableThead: Wrapper,
    TableTr: Wrapper,
    Text: Wrapper,
  };
});

import API from '../../api.js';
import VODCandidateSourcesModal from '../VODCandidateSourcesModal.jsx';

describe('VODCandidateSourcesModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getVODAccessPolicyCandidates.mockResolvedValue({
      profile_name: 'Hindi compact',
      canonical_name: 'Example Movie',
      count: 2,
      eligible_count: 1,
      results: [
        {
          relation_id: 11,
          provider_asset_id: '101',
          source_name: 'Example Movie Hindi',
          m3u_account_name: 'Provider A',
          category_name: 'Hindi Movies',
          metadata: {
            audio_languages: ['hin'],
            resolution: '1080p',
          },
          container_extension: 'mkv',
          allowed: true,
          position: 1,
          current: false,
          selected: true,
          reason: 'eligible',
        },
        {
          relation_id: 12,
          provider_asset_id: '102',
          source_name: 'Example Movie 3D',
          m3u_account_name: 'Provider B',
          category_name: '3D Movies',
          metadata: { video_features: ['3d'] },
          allowed: false,
          position: null,
          current: true,
          selected: false,
          reason: 'feature_excluded',
        },
      ],
    });
  });

  it('loads one title lazily and explains eligible and excluded sources', async () => {
    render(
      <VODCandidateSourcesModal
        opened
        onClose={vi.fn()}
        profileId={7}
        contentType="movie"
        canonicalId={3}
        currentRelationId={12}
        editionKey="ed:three-d"
      />
    );

    await waitFor(() =>
      expect(API.getVODAccessPolicyCandidates).toHaveBeenCalledWith(7, {
        type: 'movie',
        canonical_id: 3,
        current_relation_id: 12,
        edition_key: 'ed:three-d',
      })
    );
    expect(await screen.findByText('Example Movie Hindi')).toBeInTheDocument();
    expect(screen.getByText('Example Movie 3D')).toBeInTheDocument();
    expect(screen.getByText('Video feature excluded')).toBeInTheDocument();
    expect(screen.getByText('Playing')).toBeInTheDocument();
  });

  it('offers a controlled switch only for an eligible non-current source', async () => {
    const onSwitch = vi.fn().mockResolvedValue({});
    const onClose = vi.fn();
    render(
      <VODCandidateSourcesModal
        opened
        onClose={onClose}
        profileId={7}
        contentType="movie"
        canonicalId={3}
        currentRelationId={12}
        onSwitch={onSwitch}
      />
    );

    fireEvent.click(
      await screen.findByRole('button', { name: 'Next request' })
    );

    expect(screen.getByText(/different byte layouts/)).toBeInTheDocument();

    await waitFor(() =>
      expect(onSwitch).toHaveBeenCalledWith(11, 'next_request')
    );
    expect(onClose).toHaveBeenCalled();
    expect(screen.getByText('Current source')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Switch now' })).toHaveLength(
      1
    );
  });
});
