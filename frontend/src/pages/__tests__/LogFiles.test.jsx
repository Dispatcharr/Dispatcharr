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

vi.mock('@mantine/core', () => {
  const TableStub = ({ children }) => <table>{children}</table>;
  TableStub.Thead = ({ children }) => <thead>{children}</thead>;
  TableStub.Tbody = ({ children }) => <tbody>{children}</tbody>;
  TableStub.Tr = ({ children }) => <tr>{children}</tr>;
  TableStub.Th = ({ children, ta }) => <th data-align={ta}>{children}</th>;
  TableStub.Td = ({ children, ta }) => <td data-align={ta}>{children}</td>;

  return {
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
    Paper: ({ children }) => <div>{children}</div>,
    Table: TableStub,
    Text: ({ children, title }) => <span title={title}>{children}</span>,
    Title: ({ children }) => <h3>{children}</h3>,
  };
});

const files = {
  path: '/data/logs',
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
    expect(screen.getByText('2.0 KB')).toBeInTheDocument();
    expect(screen.getByText('5.0 MB')).toBeInTheDocument();
  });

  it('right-aligns sizes and keeps the exact count a hover away', async () => {
    API.getLogFiles.mockResolvedValue(files);
    renderPage();
    await screen.findByText('2.0 KB');
    expect(screen.getByText('Size')).toHaveAttribute('data-align', 'right');
    expect(screen.getByText('2.0 KB').closest('td')).toHaveAttribute(
      'data-align',
      'right'
    );
    expect(screen.getByText('5.0 MB')).toHaveAttribute(
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
    API.getLogFiles.mockResolvedValue({ path: '/data/logs', files: [] });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('No log files yet')).toBeInTheDocument();
    });
  });
});
