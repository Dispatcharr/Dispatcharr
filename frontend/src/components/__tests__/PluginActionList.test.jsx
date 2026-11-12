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
  Select: () => null,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <div>{children}</div>,
  TextInput: () => null,
  Tooltip: ({ children }) => <>{children}</>,
}));

const task = (status, result, extra = {}) => ({
  actionId: 'scan', actionLabel: 'Scan', status, result, trigger: 'manual', ...extra,
});

afterEach(() => vi.restoreAllMocks());

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
    const blob = vi.spyOn(globalThis, 'Blob').mockImplementation((parts, options) => new OriginalBlob(parts, options));

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
    expect(click.mock.instances[0].download).toBe('plugin-task-success.json');
    expect(click.mock.instances[0].isConnected).toBe(false);
    expect(revokeUrl).toHaveBeenCalledWith('blob:test');
    vi.unstubAllGlobals();
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
});
