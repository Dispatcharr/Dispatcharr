import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import EpgSettingsForm from '../EpgSettingsForm';

vi.mock('../../../../store/settings.jsx', () => {
  const mock = vi.fn();
  mock.getState = vi.fn();
  return { default: mock };
});

// Real parse/diff helpers; only the network save is stubbed.
vi.mock('../../../../utils/pages/SettingsUtils.js', async (importOriginal) => ({
  ...(await importOriginal()),
  saveGroupSettings: vi.fn(),
}));

vi.mock('@mantine/core', () => ({
  Alert: ({ title }) => <div data-testid="alert">{title}</div>,
  Button: ({ children, type, disabled }) => (
    <button type={type || 'button'} disabled={disabled}>
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  NumberInput: ({ label, value, onChange, error }) => (
    <label>
      {label}
      <input
        aria-label={label}
        type="number"
        value={value ?? ''}
        onChange={(e) =>
          onChange(e.target.value === '' ? '' : Number(e.target.value))
        }
      />
      {error && <span role="alert">{error}</span>}
    </label>
  ),
}));

import useSettingsStore from '../../../../store/settings.jsx';
import { saveGroupSettings } from '../../../../utils/pages/SettingsUtils.js';

const storedSettings = (value) => ({
  epg_settings: { id: 7, key: 'epg_settings', value },
});

const setStore = (settings) => {
  useSettingsStore.mockImplementation((selector) => selector({ settings }));
  useSettingsStore.getState.mockReturnValue({ settings });
};

const field = (label) => screen.getByLabelText(label);

describe('EpgSettingsForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    saveGroupSettings.mockResolvedValue(undefined);
  });

  it('shows the defaults when nothing is stored', () => {
    setStore({});
    render(<EpgSettingsForm active />);

    expect(field('Minimum guide history (days)').value).toBe('1');
    expect(field('Maximum guide history (days)').value).toBe('30');
    expect(field('Default days back').value).toBe('0');
    expect(field('Default days forward').value).toBe('0');
  });

  it('loads stored values, including a stored 0', () => {
    setStore(
      storedSettings({
        epg_history_min_days: 0,
        epg_history_max_days: 14,
        epg_default_prev_days: 3,
        epg_default_days: 0,
      })
    );
    render(<EpgSettingsForm active />);

    expect(field('Minimum guide history (days)').value).toBe('0');
    expect(field('Maximum guide history (days)').value).toBe('14');
    expect(field('Default days back').value).toBe('3');
  });

  it('saves only the fields that changed', async () => {
    const settings = storedSettings({
      epg_history_min_days: 1,
      epg_history_max_days: 30,
      epg_default_prev_days: 0,
      epg_default_days: 0,
    });
    setStore(settings);
    render(<EpgSettingsForm active />);

    fireEvent.change(field('Maximum guide history (days)'), {
      target: { value: '14' },
    });
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => expect(saveGroupSettings).toHaveBeenCalledTimes(1));
    expect(saveGroupSettings).toHaveBeenCalledWith(
      settings,
      'epg_settings',
      { epg_history_max_days: 14 }
    );
    expect(await screen.findByTestId('alert')).toHaveTextContent(
      'Saved Successfully'
    );
  });

  it('rejects a minimum above the maximum', async () => {
    setStore({});
    render(<EpgSettingsForm active />);

    fireEvent.change(field('Minimum guide history (days)'), {
      target: { value: '40' },
    });
    fireEvent.click(screen.getByText('Save'));

    expect(
      await screen.findByText('Minimum cannot be greater than the maximum')
    ).toBeInTheDocument();
    expect(saveGroupSettings).not.toHaveBeenCalled();
  });

  it('rejects default days back above the maximum', async () => {
    setStore({});
    render(<EpgSettingsForm active />);

    fireEvent.change(field('Default days back'), { target: { value: '31' } });
    fireEvent.click(screen.getByText('Save'));

    expect(
      await screen.findByText('Cannot be greater than the maximum guide history')
    ).toBeInTheDocument();
    expect(saveGroupSettings).not.toHaveBeenCalled();
  });

  it('does not save an emptied field', async () => {
    setStore({});
    render(<EpgSettingsForm active />);

    fireEvent.change(field('Default days forward'), { target: { value: '' } });
    fireEvent.click(screen.getByText('Save'));

    expect(
      await screen.findByText('Enter a whole number of days')
    ).toBeInTheDocument();
    expect(saveGroupSettings).not.toHaveBeenCalled();
  });
});
