import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../api.js', () => ({
  default: { previewVODAccessPolicyStreamFilter: vi.fn() },
}));
vi.mock('../LanguagePicker.jsx', () => ({
  default: () => <div>Languages</div>,
}));
vi.mock('../VideoFeaturePicker.jsx', () => ({
  default: () => <div>Features</div>,
}));
vi.mock('@dnd-kit/core', () => ({
  closestCenter: vi.fn(),
  DndContext: ({ children }) => <>{children}</>,
  KeyboardSensor: vi.fn(),
  PointerSensor: vi.fn(),
  useSensor: vi.fn(() => ({})),
  useSensors: vi.fn(() => []),
}));
vi.mock('@dnd-kit/sortable', () => ({
  arrayMove: vi.fn((value) => value),
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
vi.mock('lucide-react', () => ({
  Eye: () => null,
  GripVertical: () => null,
  Info: () => null,
  Pencil: () => null,
  Plus: () => null,
  Trash2: () => null,
}));
vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  return {
    ActionIcon: ({ children, onClick, 'aria-label': ariaLabel }) => (
      <button aria-label={ariaLabel} onClick={onClick}>
        {children}
      </button>
    ),
    Alert: Wrapper,
    Badge: Wrapper,
    Box: Wrapper,
    Button: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Group: Wrapper,
    Loader: () => <div>Loading</div>,
    Progress: () => <div>Progress</div>,
    Modal: ({ children, opened, title }) =>
      opened ? (
        <div>
          <h2>{title}</h2>
          {children}
        </div>
      ) : null,
    ScrollArea: Wrapper,
    NumberInput: ({ label, value = 0, onChange }) => (
      <label>
        {label}
        <input
          aria-label={label}
          type="number"
          value={value}
          onChange={(event) => onChange?.(Number(event.target.value))}
        />
      </label>
    ),
    Paper: Wrapper,
    Select: ({
      label,
      value,
      onChange,
      data = [],
      'aria-label': ariaLabel,
    }) => (
      <label>
        {label}
        <select
          aria-label={ariaLabel || label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {data.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    ),
    Stack: Wrapper,
    SimpleGrid: Wrapper,
    Switch: ({ label, checked, onChange }) => (
      <label>
        {label}
        <input type="checkbox" checked={checked} onChange={onChange} />
      </label>
    ),
    Table: Wrapper,
    TableTbody: Wrapper,
    TableTd: Wrapper,
    TableTh: Wrapper,
    TableThead: Wrapper,
    TableTr: Wrapper,
    Text: Wrapper,
    TextInput: ({ value, onChange, 'aria-label': ariaLabel }) => (
      <input aria-label={ariaLabel} value={value} onChange={onChange} />
    ),
    Tooltip: Wrapper,
    TagsInput: ({ label, value = [], onChange }) => (
      <label>
        {label}
        <input
          aria-label={label}
          value={value.join(',')}
          onChange={(event) => onChange?.(event.target.value.split(','))}
        />
      </label>
    ),
  };
});

import API from '../../api.js';
import VODSourceRules from '../VODSourceRules.jsx';

describe('VODSourceRules', () => {
  const rules = [
    {
      id: 'exclude-3d',
      match_field: 'category',
      regex_pattern: '^ANIME$',
      required_audio_languages: [],
      required_subtitle_languages: [],
      required_video_features: ['3d'],
      result: 'exclude',
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    API.previewVODAccessPolicyStreamFilter.mockResolvedValue({
      count: 1,
      results: [
        {
          id: 42,
          content_type: 'movie',
          title: '3D Movie',
          provider_title: 'Provider 3D Movie',
          canonical_title: 'Canonical Movie',
          m3u_account_name: 'Provider',
          category_name: 'ANIME',
          audio_languages: ['eng'],
          subtitle_languages: ['ger'],
          resolution: '1080p',
          video_features: ['3d'],
          result: 'exclude',
        },
      ],
    });
  });

  it('opens a draft preview for the clicked ordered filter', async () => {
    const onOpenDetails = vi.fn();
    render(
      <VODSourceRules
        value={rules}
        onChange={vi.fn()}
        categoryRelationIds={['7', '9']}
        onOpenDetails={onOpenDetails}
      />
    );

    fireEvent.click(
      screen.getByRole('button', { name: 'Preview content filters' })
    );

    expect(
      await screen.findByRole('heading', {
        name: 'Content filter preview',
      })
    ).toBeInTheDocument();
    expect(await screen.findByText('Provider 3D Movie')).toBeInTheDocument();
    expect(screen.getByText('Canonical Movie')).toBeInTheDocument();
    expect(screen.queryByText('Canonical title')).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Open details for Provider 3D Movie',
      })
    );
    expect(onOpenDetails).toHaveBeenCalledWith(
      expect.objectContaining({ id: 42, canonical_title: 'Canonical Movie' })
    );
    await waitFor(() =>
      expect(API.previewVODAccessPolicyStreamFilter).toHaveBeenCalledWith({
        source_rules: expect.arrayContaining([
          expect.objectContaining({ id: 'exclude-3d' }),
        ]),
        target_rule_id: 'exclude-3d',
        category_relation_ids: ['7', '9'],
        restrict_to_categories: true,
      })
    );
  });

  it('previews an edited draft before the filter or profile is saved', async () => {
    render(
      <VODSourceRules
        value={rules}
        onChange={vi.fn()}
        categoryRelationIds={['7']}
      />
    );

    fireEvent.click(
      screen.getByRole('button', { name: 'Edit content filter' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Preview draft' }));

    await waitFor(() =>
      expect(API.previewVODAccessPolicyStreamFilter).toHaveBeenCalledWith(
        expect.objectContaining({
          target_rule_id: 'exclude-3d',
          category_relation_ids: ['7'],
          restrict_to_categories: true,
        })
      )
    );
  });

  it('creates a reusable metadata filter with TMDB presence, not exact IDs', () => {
    const onChange = vi.fn();
    const onDefaultActionChange = vi.fn();
    render(
      <VODSourceRules
        value={[]}
        onChange={onChange}
        defaultAction="exclude"
        onDefaultActionChange={onDefaultActionChange}
      />
    );

    fireEvent.change(screen.getByLabelText('Unmatched content'), {
      target: { value: 'include' },
    });
    expect(onDefaultActionChange).toHaveBeenCalledWith('include');

    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    fireEvent.change(screen.getByLabelText('Genre contains'), {
      target: { value: 'Family,Animation' },
    });
    fireEvent.change(screen.getByLabelText('TMDB ID'), {
      target: { value: 'missing' },
    });
    expect(screen.queryByText(/IMDb ID/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save filter' }));

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        result: 'include',
        required_genres: ['Family', 'Animation'],
        tmdb_mode: 'missing',
      }),
    ]);
  });
});
