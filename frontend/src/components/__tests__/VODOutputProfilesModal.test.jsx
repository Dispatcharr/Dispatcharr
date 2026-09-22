import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../store/useVODStore', () => ({ default: vi.fn() }));
vi.mock('../../api', () => ({
  default: {
    createVODAccessPolicy: vi.fn(),
    updateVODAccessPolicy: vi.fn(),
    rebuildVODAccessPolicy: vi.fn(),
    deleteVODAccessPolicy: vi.fn(),
    getVODAccessPolicySelections: vi.fn(),
    getVODAccessPolicyCandidates: vi.fn(),
  },
}));
vi.mock('../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../forms/VODCategoryFilter.jsx', () => ({
  default: ({ mode, type }) => (
    <div>{`${mode} ${type} category selection`}</div>
  ),
}));
vi.mock('../VODFailoverRanking.jsx', () => ({
  default: ({ onProviderOrderChange }) => (
    <div>
      Failover priority
      <button onClick={() => onProviderOrderChange(['22', '11'])}>
        Set provider order
      </button>
    </div>
  ),
}));
vi.mock('../VODModal.jsx', () => ({
  default: ({ opened, vod }) =>
    opened ? <div>Movie details: {vod?.name}</div> : null,
}));
vi.mock('../SeriesModal.jsx', () => ({
  default: ({ opened, series }) =>
    opened ? <div>Series details: {series?.name}</div> : null,
}));
vi.mock('../VideoFeaturePicker.jsx', () => ({
  default: ({ label }) => <div>{label}</div>,
}));
vi.mock('lucide-react', () => ({
  Eye: () => null,
  Filter: () => null,
  GripVertical: () => null,
  Info: () => null,
  ListOrdered: () => null,
  Pencil: () => null,
  Plus: () => null,
  RefreshCw: () => null,
  Save: () => null,
  Trash2: () => null,
}));
vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  const Input = ({ label, value = '', onChange, disabled }) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={onChange}
      />
    </label>
  );
  const Modal = ({ opened, title, children }) =>
    opened ? (
      <div>
        <h2>{title}</h2>
        {children}
      </div>
    ) : null;
  Modal.NativeScrollArea = Wrapper;
  const Select = ({ label, value, onChange, data = [], disabled }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value || ''}
        disabled={disabled}
        onChange={(event) => onChange?.(event.target.value || null)}
      >
        <option value="" />
        {data.map((item) => {
          const option =
            typeof item === 'string' ? { value: item, label: item } : item;
          return (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          );
        })}
      </select>
    </label>
  );
  return {
    ActionIcon: ({ children, onClick, 'aria-label': ariaLabel }) => (
      <button aria-label={ariaLabel} onClick={onClick}>
        {children}
      </button>
    ),
    Alert: Wrapper,
    Badge: Wrapper,
    Box: Wrapper,
    Button: ({ children, onClick, disabled, loading }) => (
      <button disabled={disabled || loading} onClick={onClick}>
        {children}
      </button>
    ),
    Checkbox: ({ label, checked, onChange }) => (
      <label>
        <input type="checkbox" checked={checked} onChange={onChange} />
        {label}
      </label>
    ),
    Group: Wrapper,
    Loader: () => <div>Loading</div>,
    Modal,
    MultiSelect: ({ label, value = [], onChange, data = [], disabled }) => (
      <label>
        {label}
        <select
          aria-label={label}
          multiple
          value={value}
          disabled={disabled}
          onChange={(event) =>
            onChange?.(
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
      </label>
    ),
    NumberInput: Input,
    Paper: Wrapper,
    Pagination: () => null,
    Progress: ({ value }) => (
      <div aria-label="Catalog preparation progress">{value}</div>
    ),
    Popover: Wrapper,
    PopoverDropdown: Wrapper,
    PopoverTarget: Wrapper,
    ScrollArea: Wrapper,
    SegmentedControl: () => null,
    Select,
    SimpleGrid: Wrapper,
    Stack: Wrapper,
    Switch: ({ label, checked, onChange }) => (
      <label>
        {label}
        <input
          aria-label={label}
          type="checkbox"
          checked={checked}
          onChange={onChange}
        />
      </label>
    ),
    Table: Wrapper,
    TableTbody: Wrapper,
    TableTd: Wrapper,
    TableTh: Wrapper,
    TableThead: Wrapper,
    TableTr: Wrapper,
    Tabs: Wrapper,
    TabsList: Wrapper,
    TabsPanel: Wrapper,
    TabsTab: Wrapper,
    TagsInput: ({ label, value = [], onChange }) => (
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
    Text: Wrapper,
    TextInput: Input,
    Tooltip: ({ children, label }) => (
      <div data-tooltip={typeof label === 'string' ? label : ''}>
        {children}
      </div>
    ),
  };
});

import API from '../../api';
import useVODStore from '../../store/useVODStore';
import VODOutputProfilesModal from '../VODOutputProfilesModal.jsx';

describe('VODOutputProfilesModal', () => {
  const fetchCategories = vi.fn().mockResolvedValue([]);
  const fetchAccessPolicies = vi.fn().mockResolvedValue([]);
  const removeAccessPolicy = vi.fn();
  const upsertAccessPolicy = vi.fn();
  const profile = {
    id: 7,
    name: 'German HD',
    export_mode: 'compact',
    is_default: true,
    is_active: true,
    hard_constraints: {
      required_audio_languages: ['ger'],
      required_subtitle_languages: ['ger'],
      language_match_mode: 'any',
      min_resolution: 720,
      max_resolution: 1080,
      allow_unknown_metadata: false,
    },
    ranking: ['audio_language', 'subtitle_language', 'resolution'],
    provider_order: [11, 7],
    metadata_source: 'provider',
    category_rules: [],
    selection_status: 'ready',
    selection_current: true,
    selection_available: true,
    selection_active_mode: 'compact',
    selection_progress: { phase: 'Ready', percent: 100 },
    selection_counts: {
      export_mode: 'compact',
      prepared_seconds: 78,
      completed_at: '2026-09-09T06:47:21Z',
      movies: {
        output_entries: 78,
        canonical_titles: 78,
      },
      series: {
        output_entries: 42,
        canonical_titles: 42,
      },
      output_entries: 120,
      canonical_titles: 120,
      eligible_sources: 150,
      unknown_metadata: 4,
    },
  };
  let storeProfiles;

  beforeEach(() => {
    vi.clearAllMocks();
    upsertAccessPolicy.mockReset();
    storeProfiles = [profile];
    API.createVODAccessPolicy.mockResolvedValue({
      ...profile,
      id: 8,
      name: 'New profile',
    });
    API.updateVODAccessPolicy.mockResolvedValue(profile);
    API.rebuildVODAccessPolicy.mockResolvedValue({
      ...profile,
      selection_status: 'pending',
      selection_current: false,
      selection_progress: {
        phase: 'Waiting in Celery queue',
        percent: 0,
        task_id: 'manual-rebuild',
      },
    });
    API.deleteVODAccessPolicy.mockResolvedValue({});
    useVODStore.mockImplementation((selector) =>
      selector({
        categories: {},
        accessPolicies: storeProfiles,
        fetchCategories,
        fetchAccessPolicies,
        upsertAccessPolicy,
        removeAccessPolicy,
      })
    );
  });

  it('shows prepared counts for a current profile', async () => {
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(await screen.findByDisplayValue('German HD')).toBeInTheDocument();
    expect(screen.getByText(/Movies: 78 output entries/)).toBeInTheDocument();
    expect(screen.getByText(/Series: 42 output entries/)).toBeInTheDocument();
    expect(screen.getByText('Compact')).toBeInTheDocument();
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
    expect(screen.getByText('Last build: 1m 18s')).toBeInTheDocument();
    expect(
      screen.queryByText(/Currently active catalog:/)
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Retry catalog update' })
    ).not.toBeInTheDocument();
  });

  it('reuses the VOD category selection for both profile source scopes', async () => {
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    await screen.findByDisplayValue('German HD');
    expect(
      screen.getByText('profile movie category selection')
    ).toBeInTheDocument();
    expect(
      screen.getByText('profile series category selection')
    ).toBeInTheDocument();
    expect(screen.getByText('Content rules')).toBeInTheDocument();
  });

  it('offers a manual rebuild for an outdated catalog', async () => {
    storeProfiles = [
      {
        ...profile,
        selection_status: 'outdated',
        selection_current: false,
      },
    ];
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(await screen.findByText('Outdated')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Rebuild' }));

    await waitFor(() =>
      expect(API.rebuildVODAccessPolicy).toHaveBeenCalledWith(profile.id)
    );
    expect(upsertAccessPolicy).toHaveBeenCalledWith(
      expect.objectContaining({ selection_status: 'pending' }),
      { force: true }
    );
  });

  it('removes a deleted profile and confirms the server list', async () => {
    storeProfiles = [
      { ...profile, id: 9, name: 'Temporary', is_default: false },
    ];
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByLabelText('Profile')).toHaveValue('9')
    );
    fetchAccessPolicies.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(API.deleteVODAccessPolicy).toHaveBeenCalledWith(9)
    );
    expect(removeAccessPolicy).toHaveBeenCalledWith(9);
    expect(fetchAccessPolicies).toHaveBeenCalledTimes(1);
  });

  it('allows deleting the default when another active profile can replace it', async () => {
    storeProfiles = [
      profile,
      { ...profile, id: 9, name: 'Replacement', is_default: false },
    ];
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    await waitFor(() =>
      expect(screen.getByLabelText('Profile')).toHaveValue('7')
    );
    const deleteButton = screen.getByRole('button', { name: 'Delete' });
    expect(deleteButton).toBeEnabled();
    fireEvent.click(deleteButton);

    await waitFor(() =>
      expect(API.deleteVODAccessPolicy).toHaveBeenCalledWith(7)
    );
  });

  it('explains why the last active default profile cannot be deleted', async () => {
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(await screen.findByDisplayValue('German HD')).toBeInTheDocument();
    const deleteButton = screen.getByRole('button', { name: 'Delete' });
    expect(deleteButton).toBeDisabled();
    expect(deleteButton.closest('[data-tooltip]')).toHaveAttribute(
      'data-tooltip',
      expect.stringMatching(/Create or activate another profile/)
    );
  });

  it('keeps a new draft empty instead of reselecting the first profile', async () => {
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);
    expect(await screen.findByDisplayValue('German HD')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'New' }));

    await waitFor(() =>
      expect(screen.getByLabelText('Profile name')).toHaveValue('')
    );
  });

  it('creates and saves a new reusable profile', async () => {
    const pendingProfile = {
      ...profile,
      id: 8,
      name: 'New profile',
      selection_status: 'pending',
      selection_current: false,
      selection_available: false,
      selection_started_at: new Date().toISOString(),
      selection_progress: {
        phase: 'Publishing background task',
        percent: 0,
      },
    };
    API.createVODAccessPolicy.mockResolvedValue(pendingProfile);
    upsertAccessPolicy.mockImplementation((saved) => {
      storeProfiles = [...storeProfiles, saved];
    });
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('German HD');

    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    fireEvent.change(screen.getByLabelText('Profile name'), {
      target: { value: 'New profile' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Set provider order' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    await waitFor(() =>
      expect(API.createVODAccessPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'New profile',
          hard_constraints: {
            source_rules: [],
            content_default_action: 'exclude',
            category_import_rules: [],
            disabled_ranking: [],
            audio_language_order: [],
            subtitle_language_order: [],
          },
          provider_order: [22, 11],
        })
      )
    );
    expect(upsertAccessPolicy).toHaveBeenCalledWith(
      expect.objectContaining({ id: 8, name: 'New profile' }),
      { preserveIfMissing: true }
    );
    expect(screen.getByLabelText('Profile')).toHaveValue('8');
    expect(fetchAccessPolicies).toHaveBeenCalledTimes(2);
    expect(screen.getByText('Preparing')).toBeInTheDocument();
    expect(screen.getByText(/Publishing background task/)).toBeInTheDocument();
    expect(screen.getByText(/elapsed/)).toBeInTheDocument();
  });

  it('uses automatic mode naming and simple suffix rules', async () => {
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('German HD');

    expect(screen.queryByLabelText('Title source')).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText('Custom output title format (optional)')
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add suffix rule' }));

    expect(screen.getByLabelText('Output suffix')).toBeInTheDocument();
    expect(screen.queryByLabelText('Edition')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Name match')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Expression')).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText('Case-sensitive expression')
    ).not.toBeInTheDocument();
  });

  it('publishes visible pending progress as soon as save starts', async () => {
    let finishSave;
    API.updateVODAccessPolicy.mockReturnValue(
      new Promise((resolve) => {
        finishSave = resolve;
      })
    );
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('German HD');
    fireEvent.change(screen.getByLabelText('Profile name'), {
      target: { value: 'German HD updated' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    expect(upsertAccessPolicy).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 7,
        selection_status: 'pending',
        selection_progress: expect.objectContaining({
          phase: 'Saving profile and publishing catalog update',
          percent: 0,
        }),
      })
    );
    finishSave(profile);
    await waitFor(() =>
      expect(upsertAccessPolicy).toHaveBeenLastCalledWith(profile)
    );
  });

  it('enables save only after an existing profile was changed', async () => {
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);
    const name = await screen.findByLabelText('Profile name');
    const saveButton = screen.getByRole('button', { name: 'Save profile' });

    expect(saveButton).toBeDisabled();
    fireEvent.change(name, { target: { value: 'German HD updated' } });
    expect(saveButton).toBeEnabled();
    fireEvent.change(name, { target: { value: 'German HD' } });
    expect(saveButton).toBeDisabled();
  });

  it('does not overwrite an edited draft when profile status is polled', async () => {
    const view = render(<VODOutputProfilesModal opened onClose={vi.fn()} />);
    const name = await screen.findByLabelText('Profile name');
    fireEvent.change(name, { target: { value: 'Unsaved edit' } });

    storeProfiles = [
      {
        ...profile,
        selection_status: 'building',
        selection_current: false,
      },
    ];
    view.rerender(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(screen.getByLabelText('Profile name')).toHaveValue('Unsaved edit');
  });

  it('uses one stable updating state while queued and building', async () => {
    storeProfiles = [
      {
        ...profile,
        selection_status: 'pending',
        selection_current: false,
        active_selection_generation: 'previous-generation',
        selection_progress: { phase: 'Waiting in Celery queue', percent: 0 },
      },
    ];
    const view = render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(await screen.findByText('Updating')).toBeInTheDocument();

    storeProfiles = [
      {
        ...profile,
        selection_status: 'building',
        selection_current: false,
        active_selection_generation: 'previous-generation',
        selection_progress: { phase: 'Preparing movies', percent: 25 },
      },
    ];
    view.rerender(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(screen.getByText('Updating')).toBeInTheDocument();
    expect(screen.queryByText('Queued')).not.toBeInTheDocument();
    expect(screen.queryByText('Preparing')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Retry catalog update' })
    ).not.toBeInTheDocument();
  });

  it('shows only user-facing progress for a running catalog batch', async () => {
    storeProfiles = [
      {
        ...profile,
        selection_status: 'pending',
        selection_current: false,
        selection_task_state: 'STARTED',
        selection_progress: {
          phase: 'VOD profile catalog batch started',
          percent: 0,
          task_id: 'catalog-batch-task-id',
          task_name: 'apps.vod.tasks.rebuild_all_vod_profile_selections',
          queue: 'celery',
          batch: true,
          batch_position: 2,
          batch_total: 3,
          trigger_reason:
            'Automatic recovery: the previous VOD profile build stopped reporting progress',
        },
      },
    ];

    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(
      await screen.findByText(
        /catalog batch is running; this profile is waiting for its turn · Profile 2 of 3/
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/Assigned Celery task:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Trigger:/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Movies: 78 output entries/)
    ).not.toBeInTheDocument();
  });

  it('shows catalog build progress while a previous generation stays available', async () => {
    storeProfiles = [
      {
        ...profile,
        selection_status: 'building',
        selection_task_state: 'RUNNING',
        selection_current: false,
        selection_available: true,
        selection_started_at: new Date().toISOString(),
        selection_progress: {
          phase: 'Building movies output',
          percent: 36,
          processed: 5000,
          total: 10000,
          stage_index: 2,
          stage_count: 5,
          stage_percent: 50,
          phase_started_at: new Date(Date.now() - 30_000).toISOString(),
          target_export_mode: 'compact',
          attempt: 2,
          restart_reason: 'The VOD catalog changed while the profile was built',
          trigger_reason:
            'Automatic recovery: the previous Celery task is no longer available after a service restart',
          original_trigger_reason: 'A source metadata field changed',
        },
      },
    ];

    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(
      await screen.findByText(
        /Movies: writing the selected output catalog in database batches · 36% complete/
      )
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('Catalog preparation progress')
    ).toHaveTextContent('36');
    expect(
      screen.queryByText(/last completed catalog remains available/)
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/No manual retry is required/)
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/State: RUNNING/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Original trigger:/)).not.toBeInTheDocument();
  });

  it('distinguishes an active variants catalog from saved compact settings', async () => {
    storeProfiles = [
      {
        ...profile,
        selection_current: false,
        selection_active_mode: 'variants',
        selection_counts: {
          ...profile.selection_counts,
          export_mode: 'variants',
          movies: { output_entries: 80, canonical_titles: 78 },
        },
      },
    ];

    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(await screen.findByText('Outdated')).toBeInTheDocument();
    expect(
      screen.getByText(/active catalog was built as Variants/)
    ).toBeInTheDocument();
    expect(screen.getByText(/saved as Compact/)).toBeInTheDocument();
  });

  it('configures variants metadata and titles independently without failover controls', async () => {
    storeProfiles = [
      {
        ...profile,
        export_mode: 'variants',
        naming_mode: 'provider',
        name_template: '',
        selection_active_mode: 'variants',
        selection_counts: {
          ...profile.selection_counts,
          export_mode: 'variants',
        },
      },
    ];

    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    expect(
      await screen.findByRole('option', {
        name: 'Variants — every allowed provider source as a separate entry',
      })
    ).toBeInTheDocument();
    const metadataSelect = screen.getAllByLabelText('Metadata')[0];
    expect(metadataSelect).toHaveValue('provider');
    expect(screen.getByLabelText('Title')).toHaveValue('provider');
    expect(screen.queryByText('Failover priority')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Client title')).not.toBeInTheDocument();

    fireEvent.change(metadataSelect, {
      target: { value: 'canonical' },
    });
    fireEvent.change(screen.getByLabelText('Output format'), {
      target: { value: '[{resolution}]' },
    });
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Output format'), {
      target: { value: '{title} [{resolution}] {features}' },
    });
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'secondary' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    await waitFor(() =>
      expect(API.updateVODAccessPolicy).toHaveBeenCalledWith(
        '7',
        expect.objectContaining({
          metadata_source: 'canonical',
          naming_mode: 'template',
          name_template: '{title} [{resolution}] {features}',
          canonical_title_source: 'secondary',
        })
      )
    );
  });

  it('offers compact output formatting with canonical titles and editions', async () => {
    render(<VODOutputProfilesModal opened onClose={vi.fn()} />);

    await screen.findByDisplayValue('German HD');
    expect(screen.getByLabelText('Output')).toHaveValue('compact');
    expect(screen.getByLabelText('Output format')).toHaveValue(
      '{title} ({year}) {edition}'
    );
    expect(screen.getByLabelText('Title')).not.toHaveValue('provider');
    expect(
      screen.queryByRole('option', {
        name: 'Provider — original source title',
      })
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Output format'), {
      target: { value: '{title} {provider}' },
    });
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Output format'), {
      target: { value: '{title} ({year}) {edition}' },
    });
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled();
  });
});
