import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PluginTaskList } from '../PluginActionList.jsx';

vi.mock('@mantine/core', () => ({
  Badge: ({ children }) => <span>{children}</span>,
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick }) => <button onClick={onClick}>{children}</button>,
  Group: ({ children }) => <div>{children}</div>,
  Modal: ({ children, opened }) => opened ? <div role="dialog">{children}</div> : null,
  Progress: () => <div>Progress</div>,
  Select: ({ 'aria-label': label, value, onChange, data }) => (
    <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
      {data.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <div>{children}</div>,
  TextInput: () => null,
  Tooltip: ({ children }) => <>{children}</>,
}));

const task = (status, result, extra = {}) => ({
  actionId: 'scan', actionLabel: 'Scan', status, result, trigger: 'manual', ...extra,
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('plugin run history output', () => {
  it('shows outcome messages without inline JSON and downloads complete results', () => {
    const largeOutput = 'x'.repeat(5000);
    const tasks = {
      success: task('ok', { message: 'Completed', data: largeOutput }),
      partial: task('partial', { message: 'Some failed', data: ['one'] }),
      error: task('error', { message: 'Failed', data: ['two'] }, { error: 'Failed' }),
    };
    const createUrl = vi.fn(() => 'blob:test');
    const revokeUrl = vi.fn();
    vi.stubGlobal('URL', { createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const OriginalBlob = globalThis.Blob;
    const blob = vi.spyOn(globalThis, 'Blob').mockImplementation(function (parts, options) {
      return new OriginalBlob(parts, options);
    });

    render(<PluginTaskList tasks={tasks} />);
    fireEvent.click(screen.getByText('View history'));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Completed')).toBeInTheDocument();
    expect(within(dialog).getByText('Some failed')).toBeInTheDocument();
    expect(within(dialog).getAllByText('Failed')).toHaveLength(1);
    expect(within(dialog).queryByText(/"data"/)).not.toBeInTheDocument();
    const buttons = within(dialog).getAllByText('Download output');
    expect(buttons).toHaveLength(3);
    fireEvent.click(buttons[0]);
    expect(JSON.parse(blob.mock.calls[0][0][0])).toEqual(tasks.success.result);
    expect(blob.mock.calls[0][1]).toEqual({ type: 'application/json' });
    expect(click).toHaveBeenCalledOnce();
    expect(click.mock.contexts[0].download).toBe('plugin-task-success.json');
    expect(click.mock.contexts[0].isConnected).toBe(false);
    expect(revokeUrl).toHaveBeenCalledWith('blob:test');
  });

  it('offers downloads for falsy results but not missing results or running tasks', () => {
    render(<PluginTaskList tasks={{
      zero: task('ok', 0),
      no: task('error', false),
      empty: task('partial', ''),
      null: task('ok', null),
      missing: task('error', undefined),
      running: task('running', { message: 'Not finished' }),
    }} />);
    fireEvent.click(screen.getByText('View history'));
    expect(within(screen.getByRole('dialog')).getAllByText('Download output')).toHaveLength(3);
  });

  it('shows the trigger filter only for multiple triggers and handles changing runs', () => {
    const manual = task('ok', null);
    const scheduled = task('ok', null, { actionId: 'scheduled', actionLabel: 'Scheduled run', trigger: 'schedule' });
    const { rerender } = render(<PluginTaskList tasks={{ manual }} />);
    expect(screen.queryByLabelText('Filter task history by trigger')).not.toBeInTheDocument();

    rerender(<PluginTaskList tasks={{ manual, scheduled }} />);
    fireEvent.change(screen.getByLabelText('Filter task history by trigger'), { target: { value: 'schedule' } });
    expect(screen.getByText('Scheduled run')).toBeInTheDocument();
    expect(screen.queryByText('Scan')).not.toBeInTheDocument();

    rerender(<PluginTaskList tasks={{ manual }} />);
    expect(screen.queryByLabelText('Filter task history by trigger')).not.toBeInTheDocument();
    expect(screen.getByText('Scan')).toBeInTheDocument();
  });
});
