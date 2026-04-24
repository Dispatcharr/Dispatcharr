import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DummyEPGForm from '../DummyEPG';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/epgs', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/DummyEpgUtils.js', () => ({
  addEPG: vi.fn(),
  addNormalizedGroups: vi.fn((groups) => {
    if (!groups) return {};
    const normalized = { ...groups };
    Object.keys(groups).forEach((key) => {
      normalized[`${key}_normalize`] = String(groups[key])
        .toLowerCase()
        .replace(/[^a-z0-9]/g, '');
    });
    return normalized;
  }),
  applyTemplates: vi.fn((templates, allGroups, hasMatch) => {
    if (!hasMatch || !allGroups) return {};
    const fill = (tpl) =>
      tpl
        ? Object.entries(allGroups).reduce(
            (s, [k, v]) => s.replaceAll(`{${k}}`, v),
            tpl
          )
        : '';
    return {
      formattedTitle: fill(templates.titleTemplate),
      formattedSubtitle: fill(templates.subtitleTemplate),
      formattedDescription: fill(templates.descriptionTemplate),
      formattedUpcomingTitle: fill(templates.upcomingTitleTemplate),
      formattedUpcomingDescription: fill(templates.upcomingDescriptionTemplate),
      formattedEndedTitle: fill(templates.endedTitleTemplate),
      formattedEndedDescription: fill(templates.endedDescriptionTemplate),
      formattedChannelLogoUrl: fill(templates.channelLogoUrl),
      formattedProgramPosterUrl: fill(templates.programPosterUrl),
    };
  }),
  buildCustomProperties: vi.fn((custom = {}) => ({
    title_pattern: custom.title_pattern || '',
    time_pattern: custom.time_pattern || '',
    date_pattern: custom.date_pattern || '',
    timezone: custom.timezone || 'US/Eastern',
    output_timezone: custom.output_timezone || '',
    program_duration: custom.program_duration || 180,
    sample_title: custom.sample_title || '',
    title_template: custom.title_template || '',
    subtitle_template: custom.subtitle_template || '',
    description_template: custom.description_template || '',
    upcoming_title_template: custom.upcoming_title_template || '',
    upcoming_description_template: custom.upcoming_description_template || '',
    ended_title_template: custom.ended_title_template || '',
    ended_description_template: custom.ended_description_template || '',
    fallback_title_template: custom.fallback_title_template || '',
    fallback_description_template: custom.fallback_description_template || '',
    channel_logo_url: custom.channel_logo_url || '',
    program_poster_url: custom.program_poster_url || '',
    name_source: custom.name_source || 'channel',
    stream_index: custom.stream_index || 1,
    category: custom.category || '',
    include_date: custom.include_date ?? true,
    include_live: custom.include_live ?? false,
    include_new: custom.include_new ?? false,
  })),
  buildTimePlaceholders: vi.fn((timeGroups) => {
    if (!timeGroups || !timeGroups.hour) return {};
    const hour = parseInt(timeGroups.hour, 10);
    const minute = String(timeGroups.minute ?? '00').padStart(2, '0');
    const ampm = timeGroups.ampm ? ` ${timeGroups.ampm}` : '';
    return {
      starttime: `${hour}:${minute}${ampm}`,
      starttime24: `${String(hour).padStart(2, '0')}:${minute}`,
      endtime: `${(hour + 3) % 24}:${minute}${ampm}`,
      endtime24: `${String((hour + 3) % 24).padStart(2, '0')}:${minute}`,
    };
  }),
  getDummyEpgFormInitialValues: vi.fn(() => ({
    name: '',
    is_active: true,
    source_type: 'dummy',
    custom_properties: {
      title_pattern: '',
      time_pattern: '',
      date_pattern: '',
      timezone: 'US/Eastern',
      output_timezone: '',
      program_duration: 180,
      sample_title: '',
      title_template: '',
      subtitle_template: '',
      description_template: '',
      upcoming_title_template: '',
      upcoming_description_template: '',
      ended_title_template: '',
      ended_description_template: '',
      fallback_title_template: '',
      fallback_description_template: '',
      channel_logo_url: '',
      program_poster_url: '',
      name_source: 'channel',
      stream_index: 1,
      category: '',
      include_date: true,
      include_live: false,
      include_new: false,
    },
  })),
  getTimezones: vi.fn().mockResolvedValue({
    timezones: ['US/Eastern', 'US/Pacific', 'UTC'],
  }),
  matchPattern: vi.fn((pattern, sample, errorLabel = 'Pattern error') => {
    if (!pattern) return { matched: false, groups: {}, error: null };
    try {
      const regex = new RegExp(pattern, 'u');
      const result = regex.exec(sample ?? '');
      if (!result) return { matched: false, groups: {}, error: null };
      const groups = result.groups ?? {};
      return { matched: true, groups, error: null };
    } catch {
      return {
        matched: false,
        groups: {},
        error: `${errorLabel}: invalid regex`,
      };
    }
  }),
  updateEPG: vi.fn(),
  validateCustomNameSource: vi.fn(() => null),
  validateCustomStreamIndex: vi.fn(() => null),
  validateCustomTitlePattern: vi.fn(() => null),
}));

// ── Mantine notifications ──────────────────────────────────────────────────────
vi.mock('@mantine/notifications', () => ({
  showNotification: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  Accordion: ({ children }) => <div data-testid="accordion">{children}</div>,
  AccordionControl: ({ children }) => (
    <button data-testid="accordion-control">{children}</button>
  ),
  AccordionItem: ({ children, value }) => (
    <div data-testid={`accordion-item-${value}`}>{children}</div>
  ),
  AccordionPanel: ({ children }) => (
    <div data-testid="accordion-panel">{children}</div>
  ),
  ActionIcon: ({ children, onClick }) => (
    <button data-testid="action-icon" onClick={onClick}>
      {children}
    </button>
  ),
  Box: ({ children, mt, style }) => (
    <div style={style} data-mt={mt}>
      {children}
    </div>
  ),
  Button: ({ children, onClick, disabled, loading, type, color, variant }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      type={type}
      data-color={color}
      data-variant={variant}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange }) => (
    <label>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange?.(e.target.checked)}
        aria-label={label}
      />
      {label}
    </label>
  ),
  Divider: () => <hr />,
  Group: ({ children }) => <div>{children}</div>,
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  NumberInput: ({ label, value, onChange, min, max }) => (
    <label>
      {label}
      <input
        type="number"
        aria-label={label}
        value={value ?? ''}
        min={min}
        max={max}
        onChange={(e) => onChange?.(Number(e.target.value))}
      />
    </label>
  ),
  Paper: ({ children }) => <div data-testid="paper">{children}</div>,
  Popover: ({ children }) => <div>{children}</div>,
  PopoverDropdown: ({ children }) => (
    <div data-testid="popover-dropdown">{children}</div>
  ),
  PopoverTarget: ({ children }) => <div>{children}</div>,
  Select: ({ label, value, onChange, data, placeholder }) => (
    <label>
      {label}
      <select
        aria-label={label}
        value={value ?? ''}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
      >
        {(data || []).map((opt) => {
          const val = typeof opt === 'string' ? opt : opt.value;
          const lab = typeof opt === 'string' ? opt : opt.label;
          return (
            <option key={val} value={val}>
              {lab}
            </option>
          );
        })}
      </select>
    </label>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, c, fw, style }) => (
    <span data-size={size} data-color={c} data-fw={fw} style={style}>
      {children}
    </span>
  ),
  Textarea: ({ label, value, onChange, placeholder }) => (
    <label>
      {label}
      <textarea
        aria-label={label}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(e) => onChange?.({ target: { value: e.target.value } })}
      />
    </label>
  ),
  TextInput: ({ label, value, onChange, placeholder, ...rest }) => (
    <label>
      {label}
      <input
        type="text"
        aria-label={label}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e.currentTarget.value)}
        {...rest}
      />
    </label>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Info: () => <svg data-testid="icon-info" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useEPGsStore from '../../../store/epgs';
import { showNotification } from '../../../utils/notificationUtils.js';
import * as DummyEpgUtils from '../../../utils/forms/DummyEpgUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeEPG = (overrides = {}) => ({
  id: 1,
  name: 'Test EPG',
  is_active: true,
  custom_properties: {
    title_pattern: '(Test Show.+)',
    time_pattern: '',
    date_pattern: '',
    timezone: 'US/Eastern',
    output_timezone: '',
    program_duration: 180,
    sample_title: 'Test Show 9:00 PM',
    title_template: '{title}',
    subtitle_template: '',
    description_template: '',
    upcoming_title_template: '',
    upcoming_description_template: '',
    ended_title_template: '',
    ended_description_template: '',
    fallback_title_template: '',
    fallback_description_template: '',
    channel_logo_url: '',
    program_poster_url: '',
    name_source: 'channel',
    stream_index: 1,
    category: '',
    include_date: true,
    include_live: false,
    include_new: false,
    ...overrides.custom_properties,
  },
  ...overrides,
});

const makeTemplate = (overrides = {}) => ({
  id: 99,
  name: 'My Template',
  is_active: true,
  source_type: 'dummy',
  custom_properties: {
    title_pattern: '(?P<title>.+)',
    time_pattern: '(?P<hour>\\d+):(?P<minute>\\d+)',
    title_template: '{title}',
    timezone: 'US/Pacific',
    ...overrides.custom_properties,
  },
  ...overrides,
});

const setupMocks = ({ dummyEpgs = [] } = {}) => {
  vi.mocked(useEPGsStore).mockImplementation((sel) =>
    sel({ epgs: dummyEpgs, fetchEPGs: vi.fn() })
  );
};

const defaultProps = (overrides = {}) => ({
  epg: null,
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('DummyEPGForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(DummyEpgUtils.addEPG).mockResolvedValue({
      id: 2,
      name: 'New EPG',
    });
    vi.mocked(DummyEpgUtils.updateEPG).mockResolvedValue({});
    vi.mocked(DummyEpgUtils.getTimezones).mockResolvedValue({
      timezones: ['US/Eastern', 'US/Pacific', 'UTC'],
    });
    setupMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the form when isOpen is true', () => {
      render(<DummyEPGForm {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render when isOpen is false', () => {
      render(<DummyEPGForm {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('shows "Add Dummy EPG" title when no epg prop', () => {
      render(<DummyEPGForm {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Create Dummy EPG'
      );
    });

    it('shows "Edit Dummy EPG" title when epg prop is provided', () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Edit Dummy EPG'
      );
    });

    it('pre-fills form name when editing an existing EPG', () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      expect(screen.getByDisplayValue('Test EPG')).toBeInTheDocument();
    });
  });

  // ── Form initialization ────────────────────────────────────────────────────

  describe('form initialization', () => {
    it('calls getDummyEpgFormInitialValues on mount without epg', () => {
      render(<DummyEPGForm {...defaultProps()} />);
      expect(DummyEpgUtils.getDummyEpgFormInitialValues).toHaveBeenCalled();
    });

    it('calls buildCustomProperties when epg is provided', () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      expect(DummyEpgUtils.buildCustomProperties).toHaveBeenCalledWith(
        expect.objectContaining({ title_pattern: '(Test Show.+)' })
      );
    });

    it('populates sample_title field from epg custom_properties', () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      expect(screen.getByDisplayValue('Test Show 9:00 PM')).toBeInTheDocument();
    });
  });

  // ── Timezone loading ───────────────────────────────────────────────────────

  describe('timezone loading', () => {
    it('calls getTimezones on mount', async () => {
      render(<DummyEPGForm {...defaultProps()} />);
      await waitFor(() => {
        expect(DummyEpgUtils.getTimezones).toHaveBeenCalled();
      });
    });

    it('renders timezone options after loading', async () => {
      render(<DummyEPGForm {...defaultProps()} />);
      await waitFor(() => {
        expect(
          screen.getAllByRole('option', { name: 'US/Eastern' }).length
        ).toBeGreaterThan(0);
      });
    });

    it('shows fallback timezones and warning notification when getTimezones rejects', async () => {
      vi.mocked(DummyEpgUtils.getTimezones).mockRejectedValueOnce(
        new Error('Network error')
      );
      render(<DummyEPGForm {...defaultProps()} />);
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'yellow' })
        );
      });
      // Fallback options should still be rendered
      await waitFor(() => {
        expect(
          screen.getAllByRole('option', { name: 'UTC' }).length
        ).toBeGreaterThan(0);
      });
    });
  });

  // ── Template import ────────────────────────────────────────────────────────

  describe('template import', () => {
    it('shows the import select when dummyEpgs are available', () => {
      setupMocks({ dummyEpgs: [makeTemplate()] });
      render(<DummyEPGForm {...defaultProps()} />);
      expect(
        screen.getByPlaceholderText(/Select a template/i)
      ).toBeInTheDocument();
    });

    it('does not show import select when dummyEpgs is empty', () => {
      setupMocks({ dummyEpgs: [] });
      render(<DummyEPGForm {...defaultProps()} />);
      expect(
        screen.queryByPlaceholderText(/Select a template/i)
      ).not.toBeInTheDocument();
    });

    it('calls buildCustomProperties and applyCustomState on template import', async () => {
      setupMocks({ dummyEpgs: [makeTemplate()] });
      render(<DummyEPGForm {...defaultProps()} />);

      const select = screen.getByPlaceholderText(/Select a template/i);
      fireEvent.change(select, { target: { value: '99' } });

      await waitFor(() => {
        expect(DummyEpgUtils.buildCustomProperties).toHaveBeenCalledWith(
          expect.objectContaining({ timezone: 'US/Pacific' })
        );
      });
    });

    it('shows a notification after successful template import', async () => {
      setupMocks({ dummyEpgs: [makeTemplate()] });
      render(<DummyEPGForm {...defaultProps()} />);

      const select = screen.getByPlaceholderText(/Select a template/i);
      fireEvent.change(select, { target: { value: '99' } });

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Template Imported', color: 'blue' })
        );
      });
    });

    it('sets form name to "[template name] (Copy)" on import', async () => {
      setupMocks({ dummyEpgs: [makeTemplate()] });
      render(<DummyEPGForm {...defaultProps()} />);

      const select = screen.getByPlaceholderText(/Select a template/i);
      fireEvent.change(select, { target: { value: '99' } });

      await waitFor(() => {
        expect(
          screen.getByDisplayValue('My Template (Copy)')
        ).toBeInTheDocument();
      });
    });

    it('does nothing when an invalid template id is selected', async () => {
      setupMocks({ dummyEpgs: [makeTemplate()] });
      render(<DummyEPGForm {...defaultProps()} />);

      const callsBefore = vi.mocked(showNotification).mock.calls.length;
      const select = screen.getByPlaceholderText(/Select a template/i);
      fireEvent.change(select, { target: { value: '999' } });

      await waitFor(() => {
        expect(vi.mocked(showNotification).mock.calls.length).toBe(callsBefore);
      });
    });
  });

  // ── Pattern validation ─────────────────────────────────────────────────────

  describe('pattern validation', () => {
    it('shows title match section when title pattern matches sample title', async () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      await waitFor(() => {
        expect(screen.getByText(/title pattern matched/i)).toBeInTheDocument();
      });
    });

    it('shows no-match warning when title pattern does not match', async () => {
      const epg = makeEPG({
        custom_properties: {
          title_pattern: '(NOMATCH)',
          sample_title: 'Test Show 9:00 PM',
        },
      });
      render(<DummyEPGForm {...defaultProps({ epg })} />);
      await waitFor(() => {
        expect(screen.getByText(/did not match/i)).toBeInTheDocument();
      });
    });

    it('shows error text when title pattern is invalid regex', async () => {
      const epg = makeEPG({
        custom_properties: {
          title_pattern: '(<title>[invalid',
          sample_title: 'Test Show',
        },
      });
      render(<DummyEPGForm {...defaultProps({ epg })} />);
      await waitFor(() => {
        expect(screen.getByText(/pattern error/i)).toBeInTheDocument();
      });
    });

    it('shows calculated time placeholders when time pattern matches', async () => {
      const epg = makeEPG({
        custom_properties: {
          title_pattern: '',
          time_pattern: '(\\d+):(\\d+)\\s*(AM|PM)',
          sample_title: 'Show 9:00 PM',
          timezone: 'US/Eastern',
        },
      });
      render(<DummyEPGForm {...defaultProps({ epg })} />);
      await waitFor(() => {
        expect(screen.getByText(/time pattern matched/i)).toBeInTheDocument();
      });
    });

    it('shows formatted title preview when title template is set and pattern matches', async () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      await waitFor(() => {
        expect(screen.getByText('{title}')).toBeInTheDocument();
      });
    });

    it('shows "(no template provided)" fallback when title pattern matches but no title template', async () => {
      const epg = makeEPG({
        custom_properties: {
          title_pattern: '(Test.+)',
          sample_title: 'Test Show',
          title_template: '',
        },
      });
      render(<DummyEPGForm {...defaultProps({ epg })} />);
      await waitFor(() => {
        expect(
          screen.queryByText('(no template provided)')
        ).not.toBeInTheDocument();
      });
    });

    it('shows date match section when date pattern matches sample', async () => {
      const epg = makeEPG({
        custom_properties: {
          title_pattern: '',
          date_pattern: '(?<month>\\w+)\\s+(?<day>\\d+)',
          sample_title: 'Show Oct 17',
        },
      });
      render(<DummyEPGForm {...defaultProps({ epg })} />);
      await waitFor(() => {
        expect(screen.getByText(/date pattern matched/i)).toBeInTheDocument();
      });
    });

    it('shows calculated time placeholders when time pattern matches', async () => {
      const epg = makeEPG({
        custom_properties: {
          title_pattern: '(Show.+)',
          time_pattern: '(?<hour>\\d+):(?<minute>\\d+)\\s*(?<ampm>AM|PM)',
          sample_title: 'Show @ 9:00 PM',
          timezone: 'US/Eastern',
        },
      });
      render(<DummyEPGForm {...defaultProps({ epg })} />);
      await waitFor(() => {
        expect(
          screen.getByText(/available time placeholders/i)
        ).toBeInTheDocument();
      });
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────

  describe('form submission', () => {
    it('calls addEPG when submitting a new EPG', async () => {
      render(<DummyEPGForm {...defaultProps()} />);

      const nameInput = screen.getByPlaceholderText('My Sports EPG');
      fireEvent.change(nameInput, { target: { value: 'New EPG' } });
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(DummyEpgUtils.addEPG).toHaveBeenCalled();
      });
    });

    it('calls updateEPG when submitting an existing EPG', async () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(DummyEpgUtils.updateEPG).toHaveBeenCalledWith(
          expect.objectContaining({ name: 'Test EPG' }),
          expect.anything()
        );
      });
    });

    it('shows success notification after adding EPG', async () => {
      render(<DummyEPGForm {...defaultProps()} />);

      const nameInput = screen.getByPlaceholderText('My Sports EPG');
      fireEvent.change(nameInput, { target: { value: 'New EPG' } });
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        );
      });
    });

    it('shows success notification after updating an existing EPG', async () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Success', color: 'green' })
        );
      });
    });

    it('shows error notification when addEPG rejects', async () => {
      vi.mocked(DummyEpgUtils.addEPG).mockRejectedValueOnce(
        new Error('Server error')
      );
      render(<DummyEPGForm {...defaultProps()} />);

      const nameInput = screen.getByPlaceholderText('My Sports EPG');
      fireEvent.change(nameInput, { target: { value: 'New EPG' } });
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red', message: 'Server error' })
        );
      });
    });

    it('shows error notification when updateEPG rejects', async () => {
      vi.mocked(DummyEpgUtils.updateEPG).mockRejectedValueOnce(
        new Error('Update failed')
      );
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red', message: 'Update failed' })
        );
      });
    });

    it('calls onClose after successful submission', async () => {
      const onClose = vi.fn();
      render(<DummyEPGForm {...defaultProps({ onClose })} />);

      const nameInput = screen.getByPlaceholderText('My Sports EPG');
      fireEvent.change(nameInput, { target: { value: 'New EPG' } });
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('does not call onClose after a failed submission', async () => {
      vi.mocked(DummyEpgUtils.addEPG).mockRejectedValueOnce(new Error('Fail'));
      const onClose = vi.fn();
      render(<DummyEPGForm {...defaultProps({ onClose })} />);

      const nameInput = screen.getByPlaceholderText('My Sports EPG');
      fireEvent.change(nameInput, { target: { value: 'New EPG' } });
      fireEvent.submit(document.querySelector('form'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  // ── Modal close ────────────────────────────────────────────────────────────

  describe('modal close', () => {
    it('calls onClose when the modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<DummyEPGForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });

    it('calls onClose when Cancel button is clicked', () => {
      const onClose = vi.fn();
      render(<DummyEPGForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Checkbox toggles ───────────────────────────────────────────────────────

  describe('checkbox toggles', () => {
    it('renders include_date checkbox', () => {
      render(<DummyEPGForm {...defaultProps()} />);
      expect(screen.getByText('Include Date Tag')).toBeInTheDocument();
    });

    it('renders include_live checkbox', () => {
      render(<DummyEPGForm {...defaultProps()} />);
      expect(screen.getByText('Include Live Tag')).toBeInTheDocument();
    });

    it('renders include_new checkbox', () => {
      render(<DummyEPGForm {...defaultProps()} />);
      expect(screen.getByText('Include New Tag')).toBeInTheDocument();
    });
  });

  // ── Program duration ───────────────────────────────────────────────────────

  describe('program duration input', () => {
    it('renders the program duration field', () => {
      render(<DummyEPGForm {...defaultProps()} />);
      expect(screen.getByLabelText(/program duration/i)).toBeInTheDocument();
    });

    it('pre-fills program duration from epg', () => {
      render(<DummyEPGForm {...defaultProps({ epg: makeEPG() })} />);
      expect(screen.getByDisplayValue('180')).toBeInTheDocument();
    });
  });
});
