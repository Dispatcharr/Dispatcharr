import { MantineProvider } from '@mantine/core';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import API from '../../api';
import SafeDirectoryBrowser from '../SafeDirectoryBrowser';

vi.mock('../../api', () => ({
  default: {
    browseSafeDirectories: vi.fn(),
    createSafeDirectory: vi.fn(),
  },
}));

const listing = (path) => ({
  configured: true,
  allows_create: true,
  can_create: true,
  path,
  parent: path === '/media' ? null : '/media',
  root: { name: 'media', path: '/media' },
  entries: [],
});

describe('SafeDirectoryBrowser', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.browseSafeDirectories.mockImplementation((_scope, path) =>
      Promise.resolve(listing(path || '/media'))
    );
  });

  it('creates a folder below the directory shown in the breadcrumbs', async () => {
    const user = userEvent.setup();
    API.createSafeDirectory.mockResolvedValue({
      name: 'STRM Library',
      path: '/media/STRM Library',
    });

    render(
      <MantineProvider>
        <SafeDirectoryBrowser
          opened
          onClose={vi.fn()}
          onSelect={vi.fn()}
          scope="media-library-export"
          initialPath="/media"
        />
      </MantineProvider>
    );

    await user.click(
      await screen.findByRole('button', { name: 'Create Folder' })
    );
    const nameInput = await screen.findByLabelText('Folder name');
    await user.type(nameInput, 'STRM Library');
    await user.click(
      within(nameInput.closest('form')).getByRole('button', {
        name: 'Create Folder',
      })
    );

    await waitFor(() =>
      expect(API.createSafeDirectory).toHaveBeenCalledWith(
        'media-library-export',
        '/media',
        'STRM Library'
      )
    );
    await waitFor(() =>
      expect(API.browseSafeDirectories).toHaveBeenLastCalledWith(
        'media-library-export',
        '/media/STRM Library'
      )
    );
  });

  it('selects a file from a file-selection scope', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    API.browseSafeDirectories.mockResolvedValue({
      ...listing('/app/docker'),
      allows_create: false,
      can_create: false,
      selection_mode: 'file',
      selected_path: null,
      root: { name: '/', path: '/' },
      entries: [
        {
          name: 'configs',
          path: '/app/docker/configs',
          type: 'directory',
        },
        {
          name: 'comskip.ini',
          path: '/app/docker/comskip.ini',
          type: 'file',
        },
      ],
    });

    render(
      <MantineProvider>
        <SafeDirectoryBrowser
          opened
          onClose={vi.fn()}
          onSelect={onSelect}
          scope="dvr-comskip"
          initialPath="/app/docker"
        />
      </MantineProvider>
    );

    await user.click(await screen.findByText('comskip.ini'));
    await user.click(screen.getByRole('button', { name: 'Use this file' }));

    expect(onSelect).toHaveBeenCalledWith('/app/docker/comskip.ini');
  });

  it('uploads and selects a file when the scope provides an uploader', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onUpload = vi.fn().mockResolvedValue({
      path: '/data/comskip/comskip.ini',
    });
    API.browseSafeDirectories.mockResolvedValue({
      ...listing('/data/comskip'),
      selection_mode: 'file',
      selected_path: null,
    });

    render(
      <MantineProvider>
        <SafeDirectoryBrowser
          opened
          onClose={vi.fn()}
          onSelect={onSelect}
          scope="dvr-comskip"
          initialPath="/data/comskip"
          onUpload={onUpload}
          uploadAccept=".ini"
          uploadLabel="Upload comskip.ini"
        />
      </MantineProvider>
    );

    const file = new File(['detect_method=43'], 'custom.ini', {
      type: 'text/plain',
    });
    await screen.findByLabelText('Upload comskip.ini');
    await user.upload(document.querySelector('input[type="file"]'), file);
    await user.click(screen.getByRole('button', { name: 'Upload' }));

    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file));
    expect(onSelect).toHaveBeenCalledWith('/data/comskip/comskip.ini');
  });

  it.each([
    ['media-library-import', '/imports'],
    ['media-library-export', '/exports'],
  ])(
    'opens %s at its configured root when the form path is outside the scope',
    async (scope, rootPath) => {
      API.browseSafeDirectories.mockImplementation((_scope, path) => {
        if (path === '/outside') {
          return Promise.reject({
            body: {
              detail:
                'The resolved directory is outside the configured allowed roots.',
            },
          });
        }
        if (!path) {
          return Promise.resolve({
            configured: true,
            roots: [
              {
                name: rootPath.slice(1),
                path: rootPath,
                available: true,
                readable: true,
              },
            ],
          });
        }
        return Promise.resolve({
          ...listing(rootPath),
          path: rootPath,
          root: { name: rootPath.slice(1), path: rootPath },
        });
      });

      render(
        <MantineProvider>
          <SafeDirectoryBrowser
            opened
            onClose={vi.fn()}
            onSelect={vi.fn()}
            scope={scope}
            initialPath="/outside"
          />
        </MantineProvider>
      );

      await waitFor(() =>
        expect(API.browseSafeDirectories).toHaveBeenCalledWith(scope, rootPath)
      );
      expect(
        screen.queryByText('Unable to open directory')
      ).not.toBeInTheDocument();
    }
  );
});
