import { fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it } from 'vitest';
import VODSourceMetadata from '../VODSourceMetadata.jsx';

describe('selected VOD source metadata', () => {
  it('shows no invented metadata for an unknown source', () => {
    const { container } = render(
      <MantineProvider>
        <VODSourceMetadata source={{}} />
      </MantineProvider>
    );
    expect(
      container.querySelector('[aria-label^="Selected source metadata:"]')
    ).toBeNull();
  });
  it('shows provenance and replaces metadata when the source changes', async () => {
    const source = {
      effective_metadata: {
        values: { audio_languages: ['ger'], resolution: '1080p' },
        provenance: { audio_languages: 'category', resolution: 'observed' },
      },
    };
    const view = render(
      <MantineProvider>
        <VODSourceMetadata source={source} />
      </MantineProvider>
    );
    fireEvent.mouseEnter(
      screen.getByLabelText('Selected source metadata: DUB: ger · 1080p')
    );
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Category default'
    );
    expect(screen.getByRole('tooltip')).toHaveTextContent('Observed');
    view.rerender(
      <MantineProvider>
        <VODSourceMetadata
          source={{
            effective_metadata: {
              values: { audio_languages: ['fre'], resolution: '2160p' },
              provenance: { audio_languages: 'provider', resolution: 'manual' },
            },
          }}
        />
      </MantineProvider>
    );
    expect(screen.getByText('DUB: fre · 2160p')).toBeInTheDocument();
    expect(screen.queryByText('DUB: ger · 1080p')).not.toBeInTheDocument();
  });
});
