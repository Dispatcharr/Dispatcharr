import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const dndState = vi.hoisted(() => ({ onDragEnd: null }));

vi.mock('../../../api', () => ({
  default: {
    getM3UGroupRules: vi.fn(),
    createM3UGroupRule: vi.fn(),
    updateM3UGroupRule: vi.fn(),
    deleteM3UGroupRule: vi.fn(),
    previewM3UGroupRule: vi.fn(),
    applyM3UGroupRule: vi.fn(),
  },
}));

vi.mock('../../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../VideoFeaturePicker.jsx', () => ({
  default: ({ value = [] }) => (
    <div aria-label="Video features">{value.join(',')}</div>
  ),
}));

vi.mock('@dnd-kit/core', () => ({
  closestCenter: vi.fn(),
  DndContext: ({ children, onDragEnd }) => {
    dndState.onDragEnd = onDragEnd;
    return <>{children}</>;
  },
  KeyboardSensor: vi.fn(),
  PointerSensor: vi.fn(),
  useSensor: vi.fn(() => ({})),
  useSensors: vi.fn(() => []),
}));
vi.mock('@dnd-kit/sortable', () => ({
  arrayMove: vi.fn((items, from, to) => {
    const next = [...items];
    next.splice(to, 0, next.splice(from, 1)[0]);
    return next;
  }),
  SortableContext: ({ children }) => <>{children}</>,
  sortableKeyboardCoordinates: vi.fn(),
  useSortable: vi.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  })),
  verticalListSortingStrategy: vi.fn(),
}));
vi.mock('@dnd-kit/utilities', () => ({
  CSS: { Transform: { toString: vi.fn(() => '') } },
}));
vi.mock('@dnd-kit/modifiers', () => ({ restrictToVerticalAxis: vi.fn() }));

vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
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
    Modal: ({ children, opened, title }) =>
      opened ? (
        <div>
          <div>{title}</div>
          {children}
        </div>
      ) : null,
    MultiSelect: ({ value = [], onChange, data = [], disabled }) => (
      <select
        aria-label="Select video features"
        multiple
        value={value}
        disabled={disabled}
        onChange={(event) =>
          onChange(
            Array.from(event.target.selectedOptions, (option) => option.value)
          )
        }
      >
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    ),
    ScrollArea: Wrapper,
    Select: ({ value, onChange, data, disabled }) => (
      <select
        aria-label={`Select ${value}`}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    ),
    Stack: Wrapper,
    Table: Wrapper,
    TableTbody: Wrapper,
    TableTd: Wrapper,
    TableTh: Wrapper,
    TableThead: Wrapper,
    TableTr: ({ children, ...props }) => <div {...props}>{children}</div>,
    Text: Wrapper,
    TagsInput: ({ value = [], onChange }) => (
      <input
        aria-label="Language codes"
        value={value.join(',')}
        onChange={(event) =>
          onChange(event.target.value.split(',').filter(Boolean))
        }
      />
    ),
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

vi.mock('lucide-react', () => ({
  GripVertical: () => null,
  Play: () => null,
  Plus: () => null,
  Save: () => null,
  Trash2: () => null,
}));

import API from '../../../api';
import M3UGroupRules from '../M3UGroupRules';

describe('M3UGroupRules', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getM3UGroupRules.mockResolvedValue([
      {
        id: 5,
        scope: 'movie',
        match_field: 'group_name',
        match_mode: 'any',
        regex_pattern: '^GERMANY',
        exclude_regex_pattern: '',
        action: 'enable',
        case_sensitive: false,
        enabled: true,
        order: 10,
        metadata_defaults: {},
      },
    ]);
    API.updateM3UGroupRule.mockImplementation(
      async (_account, id, payload) => ({
        id,
        ...payload,
      })
    );
    API.createM3UGroupRule.mockImplementation(async (_account, payload) => ({
      id: 7,
      ...payload,
    }));
    API.previewM3UGroupRule.mockResolvedValue({
      count: 1,
      results: [
        {
          relation_id: 9,
          name: 'GERMANY ANIME',
          currently_enabled: false,
          would_enable: true,
          item_count: 12,
        },
      ],
      truncated: false,
    });
    API.applyM3UGroupRule.mockResolvedValue({ updated: 1 });
  });

  it('loads and saves an edited future-discovery rule', async () => {
    render(<M3UGroupRules accountId={49} scope="movie" />);

    const regex = await screen.findByLabelText('Include regular expression');
    fireEvent.change(regex, { target: { value: '^(GERMANY|DE)' } });
    fireEvent.click(screen.getByLabelText('Save rule'));

    await waitFor(() =>
      expect(API.updateM3UGroupRule).toHaveBeenCalledWith(
        49,
        5,
        expect.objectContaining({
          scope: 'movie',
          regex_pattern: '^(GERMANY|DE)',
          action: 'enable',
        })
      )
    );
  });

  it('previews the complete ordered rule result before applying it', async () => {
    render(<M3UGroupRules accountId={49} scope="movie" />);

    await screen.findByLabelText('Include regular expression');
    fireEvent.click(screen.getByLabelText('Preview and apply rule'));

    expect(await screen.findByText('GERMANY ANIME')).toBeInTheDocument();
    expect(API.previewM3UGroupRule).toHaveBeenCalledWith(
      49,
      5,
      expect.objectContaining({ regex_pattern: '^GERMANY' })
    );
    fireEvent.click(screen.getByText('Save and apply to existing'));
    await waitFor(() =>
      expect(API.applyM3UGroupRule).toHaveBeenCalledWith(49, 5)
    );
  });

  it('rejects a catch-all rule before another active rule', async () => {
    API.getM3UGroupRules.mockResolvedValue([
      {
        id: 5,
        scope: 'live',
        match_field: 'group_name',
        match_mode: 'any',
        regex_pattern: 'DE|.*',
        exclude_regex_pattern: '',
        action: 'enable',
        case_sensitive: false,
        enabled: true,
        order: 0,
        metadata_defaults: {},
      },
      {
        id: 6,
        scope: 'live',
        match_field: 'group_name',
        match_mode: 'any',
        regex_pattern: '.*',
        exclude_regex_pattern: '',
        action: 'disable',
        case_sensitive: false,
        enabled: true,
        order: 1,
        metadata_defaults: {},
      },
    ]);
    render(<M3UGroupRules accountId={49} scope="live" />);

    await screen.findByDisplayValue('DE|.*');
    fireEvent.click(screen.getAllByLabelText('Save rule')[0]);

    expect(API.updateM3UGroupRule).not.toHaveBeenCalled();
    expect(
      screen.getAllByLabelText('Include regular expression')[0]
    ).toHaveAttribute('aria-invalid', 'true');
  });

  it('persists drag-and-drop ordering without numeric order inputs', async () => {
    API.getM3UGroupRules.mockResolvedValue([
      {
        id: 5,
        scope: 'movie',
        match_field: 'group_name',
        match_mode: 'any',
        regex_pattern: '^GERMANY',
        exclude_regex_pattern: '',
        action: 'enable',
        case_sensitive: false,
        enabled: true,
        order: 0,
        metadata_defaults: {},
      },
      {
        id: 6,
        scope: 'movie',
        match_field: 'group_name',
        match_mode: 'any',
        regex_pattern: '^MULTI',
        exclude_regex_pattern: '',
        action: 'disable',
        case_sensitive: false,
        enabled: true,
        order: 1,
        metadata_defaults: {},
      },
    ]);
    render(<M3UGroupRules accountId={49} scope="movie" />);
    await screen.findByDisplayValue('^MULTI');

    await act(async () => {
      await dndState.onDragEnd({ active: { id: 6 }, over: { id: 5 } });
    });

    await waitFor(() => {
      expect(API.updateM3UGroupRule).toHaveBeenCalledWith(
        49,
        6,
        expect.objectContaining({ order: 0 })
      );
      expect(API.updateM3UGroupRule).toHaveBeenCalledWith(
        49,
        5,
        expect.objectContaining({ order: 1 })
      );
    });
  });

  it('adds account rules locally and creates them only when saved', async () => {
    render(<M3UGroupRules accountId={49} scope="movie" />);
    await screen.findByDisplayValue('^GERMANY');

    fireEvent.click(screen.getByText('Add rule'));
    expect(API.createM3UGroupRule).not.toHaveBeenCalled();
    const patterns = screen.getAllByLabelText('Include regular expression');
    fireEvent.change(patterns[1], { target: { value: '^NEWS' } });
    fireEvent.click(screen.getAllByLabelText('Save rule')[1]);

    await waitFor(() =>
      expect(API.createM3UGroupRule).toHaveBeenCalledWith(
        49,
        expect.objectContaining({
          scope: 'movie',
          regex_pattern: '^NEWS',
        })
      )
    );
  });

  it('marks identical import rules instead of sending the duplicate', async () => {
    const { container } = render(
      <M3UGroupRules accountId={49} scope="movie" />
    );
    await screen.findByDisplayValue('^GERMANY');

    fireEvent.click(screen.getByText('Add rule'));
    const patterns = screen.getAllByLabelText('Include regular expression');
    fireEvent.change(patterns[1], { target: { value: '^GERMANY' } });
    fireEvent.click(screen.getAllByLabelText('Save rule')[1]);

    expect(API.createM3UGroupRule).not.toHaveBeenCalled();
    expect(container.querySelectorAll('[data-invalid="true"]')).toHaveLength(2);
  });

  it('keeps profile import rules as a draft until Save and apply', () => {
    const onChange = vi.fn();
    const onApplied = vi.fn();
    render(
      <M3UGroupRules
        mode="profile"
        scope="movie"
        value={[
          {
            id: 'profile-rule-1',
            scope: 'movie',
            m3u_account_id: null,
            regex_pattern: '^GERMANY',
            action: 'enable',
            case_sensitive: false,
            enabled: true,
            order: 0,
          },
        ]}
        onChange={onChange}
        onApplied={onApplied}
      />
    );

    fireEvent.change(screen.getByLabelText('Include regular expression'), {
      target: { value: '^HINDI' },
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByText('If no rule matches')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Save and apply'));
    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        id: 'profile-rule-1',
        regex_pattern: '^HINDI',
        action: 'enable',
        order: 0,
      }),
    ]);
    expect(onApplied).toHaveBeenCalledOnce();
  });
});
