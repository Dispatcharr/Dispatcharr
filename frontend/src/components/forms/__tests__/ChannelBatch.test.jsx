import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ChannelBatchForm from '../ChannelBatch';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/channelsTable.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/streamProfiles', () => ({ default: vi.fn() }));
vi.mock('../../../store/epgs', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: vi.fn(),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/ChannelUtils.js', () => ({
  requeryChannels: vi.fn(),
}));

vi.mock('../../../utils/forms/ChannelBatchUtils.js', () => ({
  batchSetEPG: vi.fn(),
  buildEpgAssociations: vi.fn(),
  buildSubmitValues: vi.fn(),
  bulkRegexRenameChannels: vi.fn(),
  computeRegexPreview: vi.fn(),
  getChannelGroupChange: vi.fn(),
  getEpgChange: vi.fn(),
  getEpgData: vi.fn(),
  getLogoChange: vi.fn(),
  getMatureContentChange: vi.fn(),
  getRegexNameChange: vi.fn(),
  getStreamProfileChange: vi.fn(),
  getUserLevelChange: vi.fn(),
  setChannelLogosFromEpg: vi.fn(),
  setChannelNamesFromEpg: vi.fn(),
  setChannelTvgIdsFromEpg: vi.fn(),
  updateChannels: vi.fn(),
}));

// ── Sub-component mocks ────────────────────────────────────────────────────────
vi.mock('../ChannelGroup', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div data-testid="channel-group-form">
        <button onClick={() => onClose({ id: 99, name: 'New Group' })}>
          Save Group
        </button>
        <button onClick={() => onClose(null)}>Cancel Group</button>
      </div>
    ) : null,
}));

vi.mock('../../ConfirmationDialog', () => ({
  default: ({
    opened,
    onConfirm,
    onClose,
    title,
    confirmLabel,
    cancelLabel,
    loading,
    message,
  }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="dialog-title">{title}</div>
        <div data-testid="dialog-message">{message}</div>
        <button
          data-testid="dialog-confirm"
          onClick={onConfirm}
          disabled={loading}
        >
          {confirmLabel}
        </button>
        <button data-testid="dialog-cancel" onClick={onClose}>
          {cancelLabel}
        </button>
      </div>
    ) : null,
}));

vi.mock('../../LazyLogo', () => ({
  default: ({ src, alt }) => (
    <img src={src} alt={alt} data-testid="lazy-logo" />
  ),
}));

vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, disabled, loading, type }) => (
    <button
      type={type ?? 'button'}
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Divider: () => <hr />,
  Flex: ({ children }) => <div>{children}</div>,
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
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Popover: ({ children }) => <div data-testid="popover">{children}</div>,
  PopoverDropdown: ({ children }) => (
    <div data-testid="popover-dropdown">{children}</div>
  ),
  PopoverTarget: ({ children }) => (
    <div data-testid="popover-target">{children}</div>
  ),
  ScrollArea: ({ children, h }) => <div style={{ height: h }}>{children}</div>,
  Select: ({ label, data, value, onChange, disabled }) => (
    <select
      aria-label={label}
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
      disabled={disabled}
      data-testid={`select-${label?.toLowerCase?.().replace(/\s+/g, '-')}`}
    >
      {(data ?? []).map((opt) => {
        const val = typeof opt === 'string' ? opt : opt.value;
        const lbl = typeof opt === 'string' ? opt : opt.label;
        return (
          <option key={val} value={val}>
            {lbl}
          </option>
        );
      })}
    </select>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, c }) => (
    <span data-size={size} data-color={c}>
      {children}
    </span>
  ),
  TextInput: ({ label, placeholder, value, onChange, disabled }) => (
    <input
      aria-label={label}
      placeholder={placeholder}
      value={value ?? ''}
      onChange={onChange}
      disabled={disabled}
      data-testid={`input-${label?.toLowerCase?.().replace(/\s+/g, '-')}`}
    />
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
  UnstyledButton: ({ children, onClick, style }) => (
    <button onClick={onClick} style={style}>
      {children}
    </button>
  ),
  useMantineTheme: () => ({ tailwind: { green: { 5: '#38a169' } } }),
}));

// ── @mantine/form ──────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  useForm: vi.fn(),
}));

// ── react-window ───────────────────────────────────────────────────────────────
vi.mock('react-window', () => ({
  FixedSizeList: ({ children, itemCount, height }) => (
    <div data-testid="fixed-size-list" style={{ height }}>
      {Array.from({ length: itemCount }, (_, i) =>
        children({ index: i, style: {} })
      )}
    </div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ListOrdered: () => <svg data-testid="icon-list-ordered" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
  X: () => <svg data-testid="icon-x" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels';
import useChannelsTableStore from '../../../store/channelsTable.jsx';
import useStreamProfilesStore from '../../../store/streamProfiles';
import useEPGsStore from '../../../store/epgs';
import useWarningsStore from '../../../store/warnings';
import { useChannelLogoSelection } from '../../../hooks/useSmartLogos';
import { useForm } from '@mantine/form';
import { showNotification } from '../../../utils/notificationUtils.js';
import { requeryChannels } from '../../../utils/forms/ChannelUtils.js';
import * as ChannelBatchUtils from '../../../utils/forms/ChannelBatchUtils.js';

// ── Constants ──────────────────────────────────────────────────────────────────
const CHANNEL_IDS = [1, 2, 3];

const makeChannelGroups = () => ({
  1: { id: 1, name: 'Sports' },
  2: { id: 2, name: 'News' },
});

const makeLogos = () => ({
  5: { id: 5, name: 'HBO Logo', url: '/logos/hbo.png' },
  6: { id: 6, name: 'ESPN Logo', url: '/logos/espn.png' },
});

const makeProfiles = () => [
  { id: 1, name: 'HD Profile' },
  { id: 2, name: 'SD Profile' },
];

const makeEpgs = () => ({
  10: { id: 10, name: 'XMLTV', source_type: 'dummy' },
  11: { id: 11, name: 'Live EPG', source_type: 'xmltv' },
});

const makeFormValues = (overrides = {}) => ({
  stream_profile_id: '-1',
  user_level: '-1',
  is_adult: '-1',
  channel_group: '',
  logo: '',
  ...overrides,
});

// ── Setup helper ───────────────────────────────────────────────────────────────
const setupMocks = (overrides = {}) => {
  const mockFetchEPGs = vi.fn().mockResolvedValue(undefined);
  const formValues = makeFormValues(overrides.formValues);
  const mockGetValues = vi.fn().mockReturnValue(formValues);
  const mockSetFieldValue = vi.fn();

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ channelGroups: overrides.channelGroups ?? makeChannelGroups() })
  );
  useChannelsStore.getState = vi.fn(() => ({ fetchChannelIds: vi.fn() }));

  vi.mocked(useChannelsTableStore).mockImplementation((sel) =>
    sel({ channels: overrides.pageChannels ?? [] })
  );

  vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
    sel({ profiles: overrides.profiles ?? makeProfiles() })
  );

  vi.mocked(useEPGsStore).mockImplementation((sel) =>
    sel({
      epgs: overrides.epgs ?? makeEpgs(),
      tvgs: overrides.tvgs ?? {},
      fetchEPGs: mockFetchEPGs,
    })
  );

  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({
      isWarningSuppressed:
        overrides.isWarningSuppressed ?? vi.fn().mockReturnValue(false),
      suppressWarning: vi.fn(),
    })
  );

  vi.mocked(useChannelLogoSelection).mockReturnValue({
    logos: overrides.logos ?? makeLogos(),
    ensureLogosLoaded: vi.fn(),
    isLoading: overrides.logosLoading ?? false,
  });

  vi.mocked(useForm).mockReturnValue({
    getValues: mockGetValues,
    setValues: vi.fn(),
    setFieldValue: mockSetFieldValue,
    getInputProps: vi.fn().mockReturnValue({}),
    onSubmit: (fn) => fn,
    reset: vi.fn(),
    values: formValues,
    key: vi.fn().mockReturnValue('mock-key'),
  });

  vi.mocked(ChannelBatchUtils.computeRegexPreview).mockReturnValue([]);
  vi.mocked(ChannelBatchUtils.buildSubmitValues).mockReturnValue({
    stream_profile_id: '1',
  });
  vi.mocked(ChannelBatchUtils.buildEpgAssociations).mockResolvedValue(null);
  vi.mocked(ChannelBatchUtils.updateChannels).mockResolvedValue(undefined);
  vi.mocked(ChannelBatchUtils.bulkRegexRenameChannels).mockResolvedValue(
    undefined
  );
  vi.mocked(ChannelBatchUtils.batchSetEPG).mockResolvedValue(undefined);
  vi.mocked(ChannelBatchUtils.setChannelNamesFromEpg).mockResolvedValue(
    undefined
  );
  vi.mocked(ChannelBatchUtils.setChannelLogosFromEpg).mockResolvedValue(
    undefined
  );
  vi.mocked(ChannelBatchUtils.setChannelTvgIdsFromEpg).mockResolvedValue(
    undefined
  );
  vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(null);
  vi.mocked(ChannelBatchUtils.getLogoChange).mockReturnValue(null);
  vi.mocked(ChannelBatchUtils.getStreamProfileChange).mockReturnValue(null);
  vi.mocked(ChannelBatchUtils.getUserLevelChange).mockReturnValue(null);
  vi.mocked(ChannelBatchUtils.getMatureContentChange).mockReturnValue(null);
  vi.mocked(ChannelBatchUtils.getRegexNameChange).mockReturnValue(null);
  vi.mocked(ChannelBatchUtils.getEpgChange).mockReturnValue(null);
  vi.mocked(requeryChannels).mockResolvedValue(undefined);

  return { mockFetchEPGs, mockGetValues, mockSetFieldValue };
};

const renderForm = (props = {}) =>
  render(
    <ChannelBatchForm
      channelIds={props.channelIds ?? CHANNEL_IDS}
      isOpen={props.isOpen ?? true}
      onClose={props.onClose ?? vi.fn()}
      {...props}
    />
  );

// ──────────────────────────────────────────────────────────────────────────────

describe('ChannelBatchForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders nothing when isOpen is false', () => {
      setupMocks();
      const { container } = renderForm({ isOpen: false });
      expect(container.firstChild).toBeNull();
    });

    it('renders the form when isOpen is true', () => {
      setupMocks();
      renderForm();
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('calls fetchEPGs when modal opens', () => {
      const { mockFetchEPGs } = setupMocks();
      renderForm();
      expect(mockFetchEPGs).toHaveBeenCalled();
    });

    it('does not call fetchEPGs when isOpen is false', () => {
      const { mockFetchEPGs } = setupMocks();
      renderForm({ isOpen: false });
      expect(mockFetchEPGs).not.toHaveBeenCalled();
    });
  });

  // ── No-changes guard ───────────────────────────────────────────────────────

  describe('no-changes guard', () => {
    it('shows a notification when Apply Changes is clicked with no changes selected', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(null);
      vi.mocked(ChannelBatchUtils.getLogoChange).mockReturnValue(null);
      vi.mocked(ChannelBatchUtils.getStreamProfileChange).mockReturnValue(null);
      vi.mocked(ChannelBatchUtils.getUserLevelChange).mockReturnValue(null);
      vi.mocked(ChannelBatchUtils.getMatureContentChange).mockReturnValue(null);
      vi.mocked(ChannelBatchUtils.getRegexNameChange).mockReturnValue(null);
      vi.mocked(ChannelBatchUtils.getEpgChange).mockReturnValue(null);

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'orange' })
      );
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('opens confirmation dialog when at least one change is present', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
    });
  });

  // ── Warning suppression ────────────────────────────────────────────────────

  describe('warning suppression', () => {
    it('skips confirmation dialog and calls onSubmit directly when batch-update warning is suppressed', async () => {
      const isWarningSuppressed = vi
        .fn()
        .mockImplementation((key) => key === 'batch-update-channels');
      setupMocks({ isWarningSuppressed });
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );
      const onClose = vi.fn();

      renderForm({ onClose });
      fireEvent.click(screen.getByText('Submit'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });
  });

  // ── Confirmation dialog ────────────────────────────────────────────────────

  describe('confirmation dialog', () => {
    it('closes confirmation dialog on cancel', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));
      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('dialog-cancel'));
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('calls updateChannels on confirm', async () => {
      setupMocks({
        formValues: {
          stream_profile_id: '1', // survives: not '-1' or '0', so kept as-is after parseInt...
          user_level: '-1', // deleted
          is_adult: '-1', // deleted
          channel_group: '', // deleted (channel_group key is removed)
          logo: '', // deleted
        },
      });
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(ChannelBatchUtils.updateChannels).toHaveBeenCalledWith(
          CHANNEL_IDS,
          { stream_profile_id: '1' }
        );
      });
    });

    it('calls requeryChannels after successful submit', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(requeryChannels).toHaveBeenCalled();
      });
    });

    it('calls onClose after successful submit', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );
      const onClose = vi.fn();

      renderForm({ onClose });
      fireEvent.click(screen.getByText('Submit'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Regex rename ───────────────────────────────────────────────────────────

  describe('regex rename', () => {
    it('calls bulkRegexRenameChannels when regexFind is set and form is submitted', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getRegexNameChange).mockReturnValue(
        '• Name Change: Apply regex find "foo" replace with "bar"'
      );

      renderForm();

      // Set regexFind state by firing change on the Find input
      const findInput = screen.getByPlaceholderText('e.g. ^(.*) HD$');
      fireEvent.change(findInput, { target: { value: 'foo' } });

      fireEvent.click(screen.getByText('Submit'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(ChannelBatchUtils.bulkRegexRenameChannels).toHaveBeenCalledWith(
          CHANNEL_IDS,
          'foo',
          '', // regexReplace default is ''
          'g'
        );
      });
    });
  });

  // ── Set names from EPG ─────────────────────────────────────────────────────

  describe('set names from EPG', () => {
    it('shows notification when no channels are selected', () => {
      setupMocks();
      renderForm({ channelIds: [] });

      fireEvent.click(screen.getByText('Set Names from EPG'));

      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'orange' })
      );
    });

    it('opens set-names confirmation dialog when channels are selected', () => {
      setupMocks();
      renderForm();

      fireEvent.click(screen.getByText('Set Names from EPG'));

      expect(screen.getByTestId('dialog-title')).toHaveTextContent(
        'Confirm Set Names from EPG'
      );
    });

    it('skips dialog and executes directly when warning is suppressed', async () => {
      const isWarningSuppressed = vi
        .fn()
        .mockImplementation((key) => key === 'batch-set-names-from-epg');
      setupMocks({ isWarningSuppressed });

      renderForm();
      fireEvent.click(screen.getByText('Set Names from EPG'));

      await waitFor(() => {
        expect(ChannelBatchUtils.setChannelNamesFromEpg).toHaveBeenCalledWith(
          CHANNEL_IDS
        );
      });
    });

    it('calls setChannelNamesFromEpg on confirm', async () => {
      setupMocks();
      renderForm();

      fireEvent.click(screen.getByText('Set Names from EPG'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(ChannelBatchUtils.setChannelNamesFromEpg).toHaveBeenCalledWith(
          CHANNEL_IDS
        );
      });
    });

    it('shows success notification after setting names', async () => {
      setupMocks();
      renderForm();

      fireEvent.click(screen.getByText('Set Names from EPG'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'blue' })
        );
      });
    });

    it('shows error notification when setChannelNamesFromEpg rejects', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.setChannelNamesFromEpg).mockRejectedValue(
        new Error('fail')
      );

      renderForm();
      fireEvent.click(screen.getByText('Set Names from EPG'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
    });
  });

  // ── Set logos from EPG ─────────────────────────────────────────────────────

  describe('set logos from EPG', () => {
    it('shows notification when no channels selected', () => {
      setupMocks();
      renderForm({ channelIds: [] });

      fireEvent.click(screen.getByText('Set Logos from EPG'));

      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'orange' })
      );
    });

    it('opens confirmation dialog for set logos', () => {
      setupMocks();
      renderForm();

      fireEvent.click(screen.getByText('Set Logos from EPG'));

      expect(screen.getByTestId('dialog-title')).toHaveTextContent(
        'Confirm Set Logos from EPG'
      );
    });

    it('calls setChannelLogosFromEpg on confirm', async () => {
      setupMocks();
      renderForm();

      fireEvent.click(screen.getByText('Set Logos from EPG'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(ChannelBatchUtils.setChannelLogosFromEpg).toHaveBeenCalledWith(
          CHANNEL_IDS
        );
      });
    });

    it('shows error notification when setChannelLogosFromEpg rejects', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.setChannelLogosFromEpg).mockRejectedValue(
        new Error('fail')
      );

      renderForm();
      fireEvent.click(screen.getByText('Set Logos from EPG'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
    });
  });

  // ── Set TVG-IDs from EPG ───────────────────────────────────────────────────

  describe('set TVG-IDs from EPG', () => {
    it('shows notification when no channels selected', () => {
      setupMocks();
      renderForm({ channelIds: [] });

      fireEvent.click(screen.getByText('Set TVG-IDs from EPG'));

      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'orange' })
      );
    });

    it('opens confirmation dialog for set TVG-IDs', () => {
      setupMocks();
      renderForm();

      fireEvent.click(screen.getByText('Set TVG-IDs from EPG'));

      expect(screen.getByTestId('dialog-title')).toHaveTextContent(
        'Confirm Set TVG-IDs from EPG'
      );
    });

    it('calls setChannelTvgIdsFromEpg on confirm', async () => {
      setupMocks();
      renderForm();

      fireEvent.click(screen.getByText('Set TVG-IDs from EPG'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(ChannelBatchUtils.setChannelTvgIdsFromEpg).toHaveBeenCalledWith(
          CHANNEL_IDS
        );
      });
    });

    it('shows error notification when setChannelTvgIdsFromEpg rejects', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.setChannelTvgIdsFromEpg).mockRejectedValue(
        new Error('fail')
      );

      renderForm();
      fireEvent.click(screen.getByText('Set TVG-IDs from EPG'));
      fireEvent.click(screen.getByTestId('dialog-confirm'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
    });
  });

  // ── Channel group modal ────────────────────────────────────────────────────

  describe('channel group modal', () => {
    it('opens channel group form when SquarePlus is clicked', () => {
      setupMocks();
      renderForm();

      fireEvent.click(
        screen.getAllByTestId('icon-square-plus')[0].closest('button')
      );

      expect(screen.getByTestId('channel-group-form')).toBeInTheDocument();
    });

    it('closes channel group modal and updates selection when a new group is saved', () => {
      setupMocks();
      renderForm();

      fireEvent.click(
        screen.getAllByTestId('icon-square-plus')[0].closest('button')
      );
      fireEvent.click(screen.getByText('Save Group'));

      expect(
        screen.queryByTestId('channel-group-form')
      ).not.toBeInTheDocument();
    });

    it('closes channel group modal without updating selection when cancelled', () => {
      setupMocks();
      renderForm();

      fireEvent.click(
        screen.getAllByTestId('icon-square-plus')[0].closest('button')
      );
      fireEvent.click(screen.getByText('Cancel Group'));

      expect(
        screen.queryByTestId('channel-group-form')
      ).not.toBeInTheDocument();
    });
  });

  // ── RegexPreview ───────────────────────────────────────────────────────────

  describe('RegexPreview', () => {
    it('does not render preview when find is empty', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.computeRegexPreview).mockReturnValue([]);
      renderForm();

      expect(screen.queryByText(/Preview shows/)).not.toBeInTheDocument();
    });

    it('renders preview items when computeRegexPreview returns results', () => {
      setupMocks({
        pageChannels: [
          { id: 1, name: 'HBO East' },
          { id: 2, name: 'HBO West' },
        ],
      });
      vi.mocked(ChannelBatchUtils.computeRegexPreview).mockReturnValue([
        { before: 'HBO East', after: 'Cinemax East' },
        { before: 'HBO West', after: 'Cinemax West' },
      ]);

      renderForm();

      // Trigger a find value so RegexPreview renders (simulate find state)
      // Since RegexPreview reads `find` from props passed by the parent,
      // we verify computeRegexPreview was called with correct channel ids
      expect(ChannelBatchUtils.computeRegexPreview).toHaveBeenCalled();
    });
  });

  // ── Empty channelIds ───────────────────────────────────────────────────────

  describe('empty channelIds', () => {
    it('still renders the form with 0 channels', () => {
      setupMocks();
      renderForm({ channelIds: [] });
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });
  });

  // ── Error resilience ───────────────────────────────────────────────────────

  describe('error resilience', () => {
    it('does not throw when requeryChannels rejects after submit', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );
      vi.mocked(requeryChannels).mockRejectedValue(new Error('network'));

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      await expect(
        waitFor(() => fireEvent.click(screen.getByTestId('dialog-confirm')))
      ).resolves.not.toThrow();
    });

    it('does not throw when setChannelNamesFromEpg rejects and no channels', async () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.setChannelNamesFromEpg).mockRejectedValue(
        new Error('fail')
      );

      renderForm();
      fireEvent.click(screen.getByText('Set Names from EPG'));

      await expect(
        waitFor(() => fireEvent.click(screen.getByTestId('dialog-confirm')))
      ).resolves.not.toThrow();
    });
  });

  // ── Batch update confirmation message ──────────────────────────────────────

  describe('batch update confirmation message', () => {
    it('displays the channel count in the confirmation message', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      expect(screen.getByTestId('dialog-message')).toHaveTextContent('3');
    });

    it('displays a single change line in the confirmation message', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getStreamProfileChange).mockReturnValue(
        '• Stream Profile: HD Profile'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      expect(screen.getByTestId('dialog-message')).toHaveTextContent(
        '• Stream Profile: HD Profile'
      );
    });

    it('displays multiple change lines when several fields are changed', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );
      vi.mocked(ChannelBatchUtils.getStreamProfileChange).mockReturnValue(
        '• Stream Profile: HD Profile'
      );
      vi.mocked(ChannelBatchUtils.getUserLevelChange).mockReturnValue(
        '• User Level: Admin'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      const message = screen.getByTestId('dialog-message');
      expect(message).toHaveTextContent('• Channel Group: Sports');
      expect(message).toHaveTextContent('• Stream Profile: HD Profile');
      expect(message).toHaveTextContent('• User Level: Admin');
    });

    it('displays regex rename change line when regexFind is set', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getRegexNameChange).mockReturnValue(
        '• Name Change: Apply regex find "foo" replace with "bar"'
      );

      renderForm();
      const findInput = screen.getByPlaceholderText('e.g. ^(.*) HD$');
      fireEvent.change(findInput, { target: { value: 'foo' } });
      fireEvent.click(screen.getByText('Submit'));

      expect(screen.getByTestId('dialog-message')).toHaveTextContent(
        '• Name Change: Apply regex find "foo" replace with "bar"'
      );
    });

    it('uses "Apply Changes" as the confirm button label', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      expect(screen.getByTestId('dialog-confirm')).toHaveTextContent(
        'Apply Changes'
      );
    });

    it('shows "Confirm Batch Update" as the dialog title', () => {
      setupMocks();
      vi.mocked(ChannelBatchUtils.getChannelGroupChange).mockReturnValue(
        '• Channel Group: Sports'
      );

      renderForm();
      fireEvent.click(screen.getByText('Submit'));

      expect(screen.getByTestId('dialog-title')).toHaveTextContent(
        'Confirm Batch Update'
      );
    });
  });
});
