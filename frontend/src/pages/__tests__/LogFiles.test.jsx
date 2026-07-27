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
  TableStub.Th = ({ children }) => <th>{children}</th>;
  TableStub.Td = ({ children }) => <td>{children}</td>;

  return {
    Anchor: ({ children, onClick, to }) => (
      <a href={to || '#'} onClick={onClick}>
        {children}
      </a>
    ),
    Box: ({ children }) => <div>{children}</div>,
    Button: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Group: ({ children }) => <div>{children}</div>,
    Paper: ({ children }) => <div>{children}</div>,
    Table: TableStub,
    Text: ({ children }) => <span>{children}</span>,
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
