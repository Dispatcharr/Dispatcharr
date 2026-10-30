import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MantineProvider, Modal } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';
import M3URulesModal from '../M3URulesModal.jsx';
import stackClasses from '../../StackedModal.module.css';

vi.mock('../M3URulesEditor.jsx', () => ({
  default: ({ onStateChange }) => (
    <>
      <button onClick={() => onStateChange({ dirty: true, busy: false })}>
        Edit a row
      </button>
      <button onClick={() => onStateChange({ dirty: false, busy: false })}>
        Save row
      </button>
      <button onClick={() => onStateChange({ dirty: true, busy: true })}>
        Start saving
      </button>
      <button
        onClick={() =>
          onStateChange({ dirty: false, busy: false, overlayOpen: true })
        }
      >
        Open preview
      </button>
      <button
        onClick={() =>
          onStateChange({ dirty: false, busy: false, inventoryCount: 1234 })
        }
      >
        Report stream count
      </button>
      <button
        onClick={() =>
          onStateChange({ dirty: false, busy: false, inventoryCount: 0 })
        }
      >
        Report no streams
      </button>
    </>
  ),
}));

const Harness = ({ stacked = false, streamFilters = false, categoryCount }) => {
  const [opened, setOpened] = useState(true);
  const editor = (
    <M3URulesModal
      opened={opened}
      onClose={() => setOpened(false)}
      title={streamFilters ? 'Stream filters' : 'Import rules'}
      streamFilters={streamFilters}
      categoryCount={categoryCount}
      accountId={7}
    />
  );
  return (
    <MantineProvider>
      {stacked ? <Modal.Stack>{editor}</Modal.Stack> : editor}
    </MantineProvider>
  );
};

describe('rule dialog unsaved changes', () => {
  it.each([0, 500])(
    'shows all %s categories in the title even without configured rules',
    (categoryCount) => {
      render(<Harness categoryCount={categoryCount} />);
      expect(
        screen.getByRole('dialog', {
          name: `Import rules (${categoryCount} categories)`,
        })
      ).toBeInTheDocument();
      fireEvent.click(screen.getByText('Report stream count'));
      expect(
        screen.getByRole('dialog', {
          name: `Import rules (${categoryCount} categories)`,
        })
      ).toBeInTheDocument();
    }
  );
  it('uses the checked category inventory when no parent count is supplied', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('Report stream count'));
    expect(
      screen.getByRole('dialog', {
        name: `Import rules (${(1234).toLocaleString()} categories)`,
      })
    ).toBeInTheDocument();
  });
  it('puts the known stream inventory in the title without claiming an unknown count is zero', () => {
    render(<Harness streamFilters />);
    expect(
      screen.getByRole('dialog', { name: 'Stream filters' })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText('Report stream count'));
    expect(
      screen.getByRole('dialog', {
        name: `Stream filters (${(1234).toLocaleString()} streams)`,
      })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText('Report no streams'));
    expect(
      screen.getByRole('dialog', { name: 'Stream filters (0 streams)' })
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Effect not yet checked|Checked against/)
    ).not.toBeInTheDocument();
  });
  it('keeps the rules visible but inert behind the discard confirmation in a modal stack', async () => {
    render(<Harness stacked />);
    fireEvent.click(screen.getByText('Edit a row'));
    const editor = screen.getByRole('dialog', { name: 'Import rules' });
    fireEvent.click(screen.getByLabelText('Close modal'));
    await screen.findByRole('dialog', { name: 'Unsaved changes' });
    await waitFor(() =>
      expect(editor.closest(`.${stackClasses.background}`)).not.toBeNull()
    );
    expect(editor.closest('[inert]')).not.toBeNull();
    expect(editor).toHaveAttribute('data-hidden');
    fireEvent.click(screen.getByText('Keep editing'));
    await waitFor(() => expect(editor.closest('[inert]')).toBeNull());
    expect(
      screen.getByRole('dialog', { name: 'Import rules' })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Close modal'));
    await screen.findByRole('dialog', { name: 'Unsaved changes' });
    fireEvent.click(screen.getByText('Discard'));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
  });

  it('asks before discarding, supports keep editing and marks already saved changes as retained', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('Edit a row'));
    fireEvent.click(screen.getByLabelText('Close modal'));
    await screen.findByText('Unsaved changes');
    expect(
      screen.getByText(/Already saved changes will be kept/)
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText('Keep editing'));
    await waitFor(() =>
      expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument()
    );
    expect(screen.getByText('Edit a row')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Close modal'));
    await screen.findByText('Unsaved changes');
    fireEvent.click(screen.getByText('Discard'));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
  });

  it('closes directly after saving and prevents closing during a request', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('Start saving'));
    expect(screen.getByLabelText('Close modal')).toBeDisabled();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Save row'));
    fireEvent.click(screen.getByLabelText('Close modal'));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
  });

  it('does not close the editor when Escape belongs to a nested dialog', () => {
    render(<Harness />);
    fireEvent.click(screen.getByText('Open preview'));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
  });
});
