import { useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MetadataLanguagesInput from '../MetadataLanguagesInput.jsx';

const drag = vi.hoisted(() => ({ end: null }));
vi.mock('@dnd-kit/core', async (original) => ({
  ...(await original()),
  DndContext: ({ children, onDragEnd }) => {
    drag.end = onDragEnd;
    return children;
  },
}));
vi.mock('@dnd-kit/sortable', async (original) => ({
  ...(await original()),
  SortableContext: ({ children }) => children,
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  }),
}));

function Harness({ initial = ['en-US'], disabled = false }) {
  const [value, setValue] = useState(initial);
  return (
    <MantineProvider env="test">
      <MetadataLanguagesInput
        value={value}
        onChange={setValue}
        disabled={disabled}
      />
      <output data-testid="order">{value.join(',')}</output>
    </MantineProvider>
  );
}
beforeEach(() => {
  drag.end = null;
});

describe('ordered metadata language pills', () => {
  it('appends selected languages in the selected order and supports removal', async () => {
    render(<Harness />);
    fireEvent.click(
      screen.getByRole('textbox', { name: 'Metadata languages' })
    );
    fireEvent.click(
      await screen.findByRole('option', { name: 'German (de-DE)' })
    );
    expect(screen.getByTestId('order')).toHaveTextContent('en-US,de-DE');
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove English (US) (en-US)' })
    );
    expect(screen.getByTestId('order')).toHaveTextContent('de-DE');
  });
  it('reorders the existing pills without dropping or duplicating a language', () => {
    render(<Harness initial={['en-US', 'de-DE', 'es-ES']} />);
    act(() => drag.end({ active: { id: 'es-ES' }, over: { id: 'en-US' } }));
    expect(screen.getByTestId('order')).toHaveTextContent('es-ES,en-US,de-DE');
    act(() => drag.end({ active: { id: 'es-ES' }, over: null }));
    expect(screen.getByTestId('order')).toHaveTextContent('es-ES,en-US,de-DE');
  });
  it('disables new choices at five while keeping selected languages removable', async () => {
    render(<Harness initial={['en-US', 'de-DE', 'es-ES', 'fr-FR', 'it-IT']} />);
    fireEvent.click(
      screen.getByRole('textbox', { name: 'Metadata languages' })
    );
    expect(
      await screen.findByRole('option', { name: 'Japanese (ja-JP)' })
    ).toHaveAttribute('data-combobox-disabled');
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove Italian (it-IT)' })
    );
    fireEvent.click(
      screen.getByRole('textbox', { name: 'Metadata languages' })
    );
    fireEvent.click(
      await screen.findByRole('option', { name: 'Japanese (ja-JP)' })
    );
    expect(screen.getByTestId('order')).toHaveTextContent(
      'en-US,de-DE,es-ES,fr-FR,ja-JP'
    );
  });
  it('keeps a legacy language outside the suggestions and blocks edits while disabled', () => {
    const { rerender } = render(<Harness initial={['ca-ES', 'en-US']} />);
    expect(
      screen.getByRole('button', { name: 'Remove ca-ES' })
    ).toBeInTheDocument();
    rerender(<Harness initial={['ca-ES', 'en-US']} disabled />);
    expect(
      screen.getByRole('textbox', { name: 'Metadata languages' })
    ).toBeDisabled();
    act(() => drag.end({ active: { id: 'ca-ES' }, over: { id: 'en-US' } }));
    expect(screen.getByTestId('order')).toHaveTextContent('ca-ES,en-US');
  });
});
