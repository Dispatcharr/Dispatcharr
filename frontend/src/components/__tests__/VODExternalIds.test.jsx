import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@mantine/core', () => ({
  Badge: ({ children, component, href }) =>
    component === 'a' ? <a href={href}>{children}</a> : <span>{children}</span>,
  Group: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
}));

import VODExternalIds from '../VODExternalIds.jsx';

describe('VODExternalIds', () => {
  it('shows linked canonical external IDs without an edit action', () => {
    render(
      <VODExternalIds
        contentType="movie"
        tmdb={{
          id: '123',
          external_ids: {
            imdb_id: 'tt123',
            tvdb_id: '456',
            wikidata_id: 'Q789',
          },
        }}
      />
    );

    expect(screen.getByRole('link', { name: 'TMDB 123' })).toHaveAttribute(
      'href',
      'https://www.themoviedb.org/movie/123'
    );
    expect(screen.getByRole('link', { name: 'IMDb tt123' })).toHaveAttribute(
      'href',
      'https://www.imdb.com/title/tt123'
    );
    expect(screen.getByRole('link', { name: 'TVDB 456' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Wikidata Q789' })).toHaveAttribute(
      'href',
      'https://www.wikidata.org/wiki/Q789'
    );
    expect(
      screen.queryByRole('button', { name: /Correct TMDB/i })
    ).not.toBeInTheDocument();
  });
});
