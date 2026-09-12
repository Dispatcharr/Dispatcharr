import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import LogFilesPage from '../LogFiles';
import API from '../../api';

vi.mock('../../api', () => ({
  default: {
    getLogFiles: vi.fn(),
    downloadLogFile: vi.fn(),
  },
}));

vi.mock('../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: () => ({ fullDateTimeFormat: 'DD/MM/YYYY HH:mm:ss' }),
  format: vi.fn(() => '14/07/2026 23:00:00'),
}));

// Stands in for the table chrome, running the real column definitions.
vi.mock('../../components/tables/CustomTable', () => ({
  useTable: (options) => options,
  CustomTable: ({ table }) => (
    <table data-testid="custom-table">
      <tbody>
        {table.data.map((row) => (
          <tr key={row.name}>
            {table.columns.map((column) => (
              <td key={column.id || column.accessorKey}>
                {column.cell
                  ? column.cell({
                      cell: { getValue: () => row[column.accessorKey] },
                    })
                  : table.bodyCellRenderFns[column.id]({
                      cell: { column: { id: column.id } },
                      row: { original: row },
                    })}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  ),
}));

vi.mock('@mantine/core', () => ({
  Anchor: ({ children, onClick, to }) => (
    <a href={to || '#'} onClick={onClick}>
      {children}
    </a>
  ),
  Alert: ({ title, children }) => (
    <div role="alert">
      {title}
      {children}
    </div>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick }) => (
    <button onClick={onClick}>{children}</button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Loader: () => <div data-testid="loader" />,
  Paper: ({ children }) => <div>{children}</div>,
  Text: ({ children, title }) => <span title={title}>{children}</span>,
  Title: ({ children }) => <h3>{children}</h3>,
}));

const files = {
  files: [
    { name: 'dispatcharr.log', size: 2048, modified: '2026-07-14T11:00:00Z' },
    {
      name: 'dispatcharr.log.1',
      size: 5 * 1024 * 1024,
      modified: '2026-07-13T11:00:00Z',
    },
  ],
};

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/logs']}>
      <LogFilesPage />
    </MemoryRouter>
  );

describe('LogFilesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getLogFiles.mockResolvedValue(files);
  });

  it('lists log files with size and modified time', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('dispatcharr.log')).toBeInTheDocument();
    });
    expect(screen.getByText('dispatcharr.log.1')).toBeInTheDocument();
    expect(screen.getByText('2.00 KB')).toBeInTheDocument();
    expect(screen.getByText('5.00 MB')).toBeInTheDocument();
    expect(screen.getAllByText('14/07/2026 23:00:00')).toHaveLength(2);
  });

  it('renders the listing through the project table', async () => {
    renderPage();
    expect(await screen.findByTestId('custom-table')).toBeInTheDocument();
  });

  it('keeps the exact byte count a hover away', async () => {
    renderPage();
    await screen.findByText('2.00 KB');
    expect(screen.getByText('5.00 MB')).toHaveAttribute(
      'title',
      '5,242,880 bytes'
    );
  });

  it('says so when nothing is writing the files', async () => {
    API.getLogFiles.mockResolvedValue({ ...files, collector_running: false });
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Log collector not running/
    );
  });

  it('stays quiet when the collector is running, and on an older backend', async () => {
    API.getLogFiles.mockResolvedValue({ ...files, collector_running: true });
    renderPage();
    await screen.findByText('dispatcharr.log');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    API.getLogFiles.mockResolvedValue(files);
    renderPage();
    await screen.findAllByText('dispatcharr.log');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('links filenames to the raw view route', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('dispatcharr.log')).toBeInTheDocument();
    });
    expect(screen.getByText('dispatcharr.log').closest('a')).toHaveAttribute(
      'href',
      '/logs/dispatcharr.log'
    );
  });

  it('downloads a file from its Download link', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('dispatcharr.log')).toBeInTheDocument();
    });
    fireEvent.click(screen.getAllByText('Download')[0]);
    expect(API.downloadLogFile).toHaveBeenCalledWith('dispatcharr.log');
  });

  it('refresh re-fetches the list', async () => {
    renderPage();
    await waitFor(() => {
      expect(API.getLogFiles).toHaveBeenCalledTimes(1);
    });
    fireEvent.click(screen.getByText('Refresh'));
    await waitFor(() => {
      expect(API.getLogFiles).toHaveBeenCalledTimes(2);
    });
  });

  it('shows an empty state when there are no files', async () => {
    API.getLogFiles.mockResolvedValue({ files: [] });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('No log files yet')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('custom-table')).not.toBeInTheDocument();
  });

  it('says the listing failed rather than that there are no files', async () => {
    API.getLogFiles.mockRejectedValue(new Error('HTTP error! Status: 500'));
    renderPage();
    expect(
      await screen.findByText('Failed to load log files')
    ).toBeInTheDocument();
    expect(screen.queryByText('No log files yet')).not.toBeInTheDocument();
  });
});
