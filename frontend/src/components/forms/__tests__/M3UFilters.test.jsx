import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));
vi.mock('../../../api.js', () => ({
  default: {
    getM3UFilters: vi.fn(),
    previewM3UFilter: vi.fn(),
  },
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../../../utils/forms/M3uFilterUtils.js', () => ({
  addM3UFilter: vi.fn(),
  deleteM3UFilter: vi.fn(),
  updateM3UFilter: vi.fn(),
}));
vi.mock('../../ConfirmationDialog', () => ({
  default: ({ opened, onConfirm }) =>
    opened ? <button onClick={onConfirm}>Confirm delete</button> : null,
}));
vi.mock('@dnd-kit/core', () => ({
  closestCenter: vi.fn(),
  DndContext: ({ children }) => <div>{children}</div>,
  KeyboardSensor: vi.fn(),
  PointerSensor: vi.fn(),
  useSensor: vi.fn(),
  useSensors: vi.fn(() => []),
}));
vi.mock('@dnd-kit/sortable', () => ({
  arrayMove: (items) => items,
  SortableContext: ({ children }) => <div>{children}</div>,
  sortableKeyboardCoordinates: vi.fn(),
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  }),
  verticalListSortingStrategy: vi.fn(),
}));
vi.mock('@dnd-kit/utilities', () => ({
  CSS: { Transform: { toString: () => '' } },
}));
vi.mock('@dnd-kit/modifiers', () => ({ restrictToVerticalAxis: vi.fn() }));
vi.mock('lucide-react', () => ({
  Eye: () => null,
  GripVertical: () => null,
  Info: () => null,
  Plus: () => null,
  Save: () => null,
  Trash2: () => null,
}));
vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  const Modal = ({ opened, children, title }) =>
    opened ? (
      <div>
        <h2>{title}</h2>
        {children}
      </div>
    ) : null;
  Modal.NativeScrollArea = Wrapper;
  return {
    ActionIcon: ({ children, onClick, disabled, 'aria-label': ariaLabel }) => (
      <button aria-label={ariaLabel} onClick={onClick} disabled={disabled}>
        {children}
      </button>
    ),
    Alert: Wrapper,
    Button: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Checkbox: ({ checked, onChange, 'aria-label': ariaLabel }) => (
      <input
        aria-label={ariaLabel}
        type="checkbox"
        checked={checked}
        onChange={onChange}
      />
    ),
    Group: Wrapper,
    Modal,
    ScrollArea: Wrapper,
    Select: ({ value, onChange, data = [], 'aria-label': ariaLabel }) => (
      <select
        aria-label={ariaLabel}
        value={value || ''}
        onChange={(event) => onChange(event.target.value)}
      >
        {data.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    ),
    Stack: Wrapper,
    Table: ({ children }) => <table>{children}</table>,
    TableTbody: ({ children }) => <tbody>{children}</tbody>,
    TableTd: ({ children }) => <td>{children}</td>,
    TableTh: ({ children }) => <th>{children}</th>,
    TableThead: ({ children }) => <thead>{children}</thead>,
    TableTr: ({ children, ...props }) => <tr {...props}>{children}</tr>,
    Text: Wrapper,
    TextInput: ({ value, onChange, error, 'aria-label': ariaLabel }) => (
      <input
        aria-label={ariaLabel}
        aria-invalid={Boolean(error)}
        value={value}
        onChange={onChange}
      />
    ),
  };
});

import API from '../../../api.js';
import useWarningsStore from '../../../store/warnings';
import * as filterAPI from '../../../utils/forms/M3uFilterUtils.js';
import M3UFilters from '../M3UFilters.jsx';

const playlist = {
  id: 10,
  filters: [
    {
      id: 1,
      filter_type: 'group',
      regex_pattern: 'HBO.*',
      exclude: false,
      order: 0,
      custom_properties: { case_sensitive: false },
    },
  ],
};

describe('M3UFilters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getM3UFilters.mockResolvedValue(playlist.filters);
    API.previewM3UFilter.mockResolvedValue({
      count: 1,
      inventory_count: 12,
      catalog_complete: true,
      results: [
        {
          id: 7,
          name: 'HBO HD',
          group: 'Entertainment',
          url: 'https://example.test/live/7',
          result: 'exclude',
        },
      ],
    });
    useWarningsStore.mockImplementation((selector) =>
      selector({
        isWarningSuppressed: () => false,
        suppressWarning: vi.fn(),
      })
    );
  });

  it('does not render without a valid open account', () => {
    render(<M3UFilters playlist={playlist} isOpen={false} />);
    expect(screen.queryByText('Stream filters')).not.toBeInTheDocument();
  });

  it('edits existing filters inline', async () => {
    render(<M3UFilters playlist={playlist} isOpen onClose={vi.fn()} />);
    expect(await screen.findByText('Stream filters')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Stream filter regular expression')
    ).toHaveValue('HBO.*');
    expect(screen.queryByText('Filter')).not.toBeInTheDocument();
  });

  it('adds a new inline row without opening another dialog', async () => {
    render(<M3UFilters playlist={playlist} isOpen onClose={vi.fn()} />);
    await screen.findByLabelText('Stream filter regular expression');
    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    expect(
      screen.getAllByLabelText('Stream filter regular expression')
    ).toHaveLength(2);
  });

  it('creates a new rule from its inline row', async () => {
    filterAPI.addM3UFilter.mockResolvedValue({
      id: 2,
      filter_type: 'group',
      regex_pattern: 'NEWS.*',
      exclude: true,
      order: 1,
    });
    render(<M3UFilters playlist={playlist} isOpen onClose={vi.fn()} />);
    await screen.findByLabelText('Stream filter regular expression');
    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    const patterns = screen.getAllByLabelText(
      'Stream filter regular expression'
    );
    fireEvent.change(patterns[1], { target: { value: 'NEWS.*' } });
    fireEvent.click(screen.getAllByLabelText('Save stream filter')[1]);

    await waitFor(() =>
      expect(filterAPI.addM3UFilter).toHaveBeenCalledWith(
        playlist,
        expect.objectContaining({ regex_pattern: 'NEWS.*' })
      )
    );
    expect(API.getM3UFilters).toHaveBeenCalledWith(10);
  });

  it('marks identical filters instead of sending the duplicate', async () => {
    API.getM3UFilters.mockResolvedValue([]);
    const { container } = render(
      <M3UFilters playlist={playlist} isOpen onClose={vi.fn()} />
    );
    await screen.findByText('No stream filters configured.');

    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    const patterns = screen.getAllByLabelText(
      'Stream filter regular expression'
    );
    fireEvent.change(patterns[0], { target: { value: 'NEWS.*' } });
    fireEvent.change(patterns[1], { target: { value: 'NEWS.*' } });
    fireEvent.click(screen.getAllByLabelText('Save stream filter')[1]);

    expect(filterAPI.addM3UFilter).not.toHaveBeenCalled();
    expect(container.querySelectorAll('[data-invalid="true"]')).toHaveLength(2);
  });

  it('deletes a saved filter after confirmation', async () => {
    render(<M3UFilters playlist={playlist} isOpen onClose={vi.fn()} />);
    await screen.findByLabelText('Delete stream filter');
    fireEvent.click(screen.getByLabelText('Delete stream filter'));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() =>
      expect(filterAPI.deleteM3UFilter).toHaveBeenCalledWith(playlist, 1)
    );
  });

  it('previews a rule in the context of the ordered filter list', async () => {
    render(<M3UFilters playlist={playlist} isOpen onClose={vi.fn()} />);
    fireEvent.click(await screen.findByLabelText('Preview stream filter'));

    await waitFor(() =>
      expect(API.previewM3UFilter).toHaveBeenCalledWith(
        10,
        1,
        expect.objectContaining({ regex_pattern: 'HBO.*' })
      )
    );
    expect(await screen.findByText('HBO HD')).toBeInTheDocument();
    expect(
      screen.getByText('1 matching streams from 12 candidates')
    ).toBeInTheDocument();
  });
});
