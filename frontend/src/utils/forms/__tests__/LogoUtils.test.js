import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  uploadLogo,
  createLogo,
  updateLogo,
  getResolver,
  getUploadErrorMessage,
  getUpdateLogoErrorMessage,
  validateFileSize,
  releaseUrl,
  getFilenameWithoutExtension,
} from '../LogoUtils.js';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    uploadLogo: vi.fn(),
    createLogo: vi.fn(),
    updateLogo: vi.fn(),
  },
}));

// ── @hookform/resolvers/yup mock ───────────────────────────────────────────────
vi.mock('@hookform/resolvers/yup', () => ({
  yupResolver: vi.fn((schema) => ({ __resolver: true, schema })),
}));

import API from '../../../api.js';
import { yupResolver } from '@hookform/resolvers/yup';

describe('LogoUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── uploadLogo ─────────────────────────────────────────────────────────────

  describe('uploadLogo', () => {
    const makeFile = () =>
      new File(['content'], 'logo.png', { type: 'image/png' });
    const makeValues = (overrides = {}) => ({ name: 'My Logo', ...overrides });

    it('calls API.uploadLogo with the selected file and values.name', async () => {
      const file = makeFile();
      const values = makeValues();
      vi.mocked(API.uploadLogo).mockResolvedValue({ id: '1' });

      await uploadLogo(file, values);

      expect(API.uploadLogo).toHaveBeenCalledWith(file, 'My Logo');
    });

    it('returns the result of API.uploadLogo', async () => {
      const mockResult = { id: '1', name: 'My Logo' };
      vi.mocked(API.uploadLogo).mockResolvedValue(mockResult);

      const result = await uploadLogo(makeFile(), makeValues());

      expect(result).toEqual(mockResult);
    });

    it('calls API.uploadLogo exactly once', async () => {
      vi.mocked(API.uploadLogo).mockResolvedValue({});

      await uploadLogo(makeFile(), makeValues());

      expect(API.uploadLogo).toHaveBeenCalledTimes(1);
    });

    it('propagates rejection from API.uploadLogo', async () => {
      vi.mocked(API.uploadLogo).mockRejectedValue(new Error('Upload failed'));

      await expect(uploadLogo(makeFile(), makeValues())).rejects.toThrow(
        'Upload failed'
      );
    });
  });

  // ── createLogo ─────────────────────────────────────────────────────────────

  describe('createLogo', () => {
    const makeValues = () => ({
      name: 'New Logo',
      url: 'https://example.com/logo.png',
    });

    it('calls API.createLogo with the provided values', async () => {
      const values = makeValues();
      vi.mocked(API.createLogo).mockResolvedValue({ id: '2' });

      await createLogo(values);

      expect(API.createLogo).toHaveBeenCalledWith(values);
    });

    it('returns the result of API.createLogo', async () => {
      const mockResult = { id: '2', name: 'New Logo' };
      vi.mocked(API.createLogo).mockResolvedValue(mockResult);

      const result = await createLogo(makeValues());

      expect(result).toEqual(mockResult);
    });

    it('calls API.createLogo exactly once', async () => {
      vi.mocked(API.createLogo).mockResolvedValue({});

      await createLogo(makeValues());

      expect(API.createLogo).toHaveBeenCalledTimes(1);
    });

    it('propagates rejection from API.createLogo', async () => {
      vi.mocked(API.createLogo).mockRejectedValue(new Error('Create failed'));

      await expect(createLogo(makeValues())).rejects.toThrow('Create failed');
    });
  });

  // ── updateLogo ─────────────────────────────────────────────────────────────

  describe('updateLogo', () => {
    const makeLogo = (overrides = {}) => ({
      id: 'logo-1',
      name: 'Old Logo',
      ...overrides,
    });
    const makeValues = () => ({
      name: 'Updated Logo',
      url: 'https://example.com/new.png',
    });

    it('calls API.updateLogo with the logo id and values', async () => {
      const logo = makeLogo();
      const values = makeValues();
      vi.mocked(API.updateLogo).mockResolvedValue({ id: 'logo-1' });

      await updateLogo(logo, values);

      expect(API.updateLogo).toHaveBeenCalledWith('logo-1', values);
    });

    it('returns the result of API.updateLogo', async () => {
      const mockResult = { id: 'logo-1', name: 'Updated Logo' };
      vi.mocked(API.updateLogo).mockResolvedValue(mockResult);

      const result = await updateLogo(makeLogo(), makeValues());

      expect(result).toEqual(mockResult);
    });

    it('calls API.updateLogo exactly once', async () => {
      vi.mocked(API.updateLogo).mockResolvedValue({});

      await updateLogo(makeLogo(), makeValues());

      expect(API.updateLogo).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the logo object', async () => {
      const logo = makeLogo({ id: 'logo-99', name: 'Irrelevant' });
      vi.mocked(API.updateLogo).mockResolvedValue({});

      await updateLogo(logo, makeValues());

      expect(API.updateLogo).toHaveBeenCalledWith('logo-99', expect.anything());
    });

    it('propagates rejection from API.updateLogo', async () => {
      vi.mocked(API.updateLogo).mockRejectedValue(new Error('Update failed'));

      await expect(updateLogo(makeLogo(), makeValues())).rejects.toThrow(
        'Update failed'
      );
    });
  });

  // ── getResolver ────────────────────────────────────────────────────────────

  describe('getResolver', () => {
    it('returns the result of yupResolver', () => {
      const resolver = getResolver();

      expect(yupResolver).toHaveBeenCalledTimes(1);
      expect(resolver).toEqual(expect.objectContaining({ __resolver: true }));
    });

    it('passes a Yup schema to yupResolver', () => {
      getResolver();

      const [schema] = vi.mocked(yupResolver).mock.calls[0];
      expect(schema).toBeDefined();
      expect(typeof schema.validate).toBe('function');
    });

    it('schema validates a valid name and URL', async () => {
      getResolver();
      const [schema] = vi.mocked(yupResolver).mock.calls[0];

      await expect(
        schema.validate({
          name: 'My Logo',
          url: 'https://example.com/logo.png',
        })
      ).resolves.not.toThrow();
    });

    it('schema rejects missing name', async () => {
      getResolver();
      const [schema] = vi.mocked(yupResolver).mock.calls[0];

      await expect(
        schema.validate({ name: '', url: 'https://example.com/logo.png' })
      ).rejects.toThrow('Name is required');
    });

    it('schema rejects missing url', async () => {
      getResolver();
      const [schema] = vi.mocked(yupResolver).mock.calls[0];

      await expect(
        schema.validate({ name: 'My Logo', url: '' })
      ).rejects.toThrow('URL is required');
    });

    it('schema accepts a local /data/logos/ path as url', async () => {
      getResolver();
      const [schema] = vi.mocked(yupResolver).mock.calls[0];

      await expect(
        schema.validate({ name: 'Local Logo', url: '/data/logos/my-logo.png' })
      ).resolves.not.toThrow();
    });

    it('schema rejects an invalid url that is not a local path', async () => {
      getResolver();
      const [schema] = vi.mocked(yupResolver).mock.calls[0];

      await expect(
        schema.validate({ name: 'Bad Logo', url: 'not-a-url' })
      ).rejects.toThrow('Must be a valid URL or local file path');
    });
  });

  // ── getUploadErrorMessage ──────────────────────────────────────────────────

  describe('getUploadErrorMessage', () => {
    it('returns timeout message for NETWORK_ERROR code', () => {
      const result = getUploadErrorMessage({ code: 'NETWORK_ERROR' });
      expect(result).toBe('Upload timed out. Please try again.');
    });

    it('returns timeout message when message includes "timeout"', () => {
      const result = getUploadErrorMessage({
        message: 'request timeout occurred',
      });
      expect(result).toBe('Upload timed out. Please try again.');
    });

    it('returns file too large message for status 413', () => {
      const result = getUploadErrorMessage({ status: 413 });
      expect(result).toBe('File too large. Please choose a smaller file.');
    });

    it('returns body error message when body.error is present', () => {
      const result = getUploadErrorMessage({
        body: { error: 'Unsupported format' },
      });
      expect(result).toBe('Unsupported format');
    });

    it('returns generic message when no specific condition matches', () => {
      const result = getUploadErrorMessage({});
      expect(result).toBe('Failed to upload logo file');
    });

    it('prioritizes NETWORK_ERROR over status 413', () => {
      const result = getUploadErrorMessage({
        code: 'NETWORK_ERROR',
        status: 413,
      });
      expect(result).toBe('Upload timed out. Please try again.');
    });

    it('prioritizes status 413 over body.error', () => {
      const result = getUploadErrorMessage({
        status: 413,
        body: { error: 'Custom error' },
      });
      expect(result).toBe('File too large. Please choose a smaller file.');
    });
  });

  // ── getUpdateLogoErrorMessage ──────────────────────────────────────────────

  describe('getUpdateLogoErrorMessage', () => {
    const makeLogo = () => ({ id: 'logo-1', name: 'My Logo' });

    it('returns timeout message for NETWORK_ERROR code', () => {
      const result = getUpdateLogoErrorMessage(makeLogo(), {
        code: 'NETWORK_ERROR',
      });
      expect(result).toBe('Request timed out. Please try again.');
    });

    it('returns timeout message when message includes "timeout"', () => {
      const result = getUpdateLogoErrorMessage(makeLogo(), {
        message: 'connection timeout',
      });
      expect(result).toBe('Request timed out. Please try again.');
    });

    it('returns response data error when present', () => {
      const result = getUpdateLogoErrorMessage(makeLogo(), {
        response: { data: { error: 'Duplicate name' } },
      });
      expect(result).toBe('Duplicate name');
    });

    it('returns "Failed to update logo" when logo is provided and no specific error', () => {
      const result = getUpdateLogoErrorMessage(makeLogo(), {});
      expect(result).toBe('Failed to update logo');
    });

    it('returns "Failed to create logo" when logo is null', () => {
      const result = getUpdateLogoErrorMessage(null, {});
      expect(result).toBe('Failed to create logo');
    });

    it('returns "Failed to create logo" when logo is undefined', () => {
      const result = getUpdateLogoErrorMessage(undefined, {});
      expect(result).toBe('Failed to create logo');
    });

    it('prioritizes NETWORK_ERROR over response.data.error', () => {
      const result = getUpdateLogoErrorMessage(makeLogo(), {
        code: 'NETWORK_ERROR',
        response: { data: { error: 'Custom' } },
      });
      expect(result).toBe('Request timed out. Please try again.');
    });
  });

  // ── validateFileSize ───────────────────────────────────────────────────────

  describe('validateFileSize', () => {
    const makeFile = (sizeBytes) => ({ size: sizeBytes });

    it('returns true for a file exactly at the 5MB limit', () => {
      const file = makeFile(5 * 1024 * 1024);
      expect(validateFileSize(file)).toBe(true);
    });

    it('returns true for a file smaller than 5MB', () => {
      const file = makeFile(1024 * 1024);
      expect(validateFileSize(file)).toBe(true);
    });

    it('returns false for a file larger than 5MB', () => {
      const file = makeFile(5 * 1024 * 1024 + 1);
      expect(validateFileSize(file)).toBe(false);
    });

    it('returns true for a zero-byte file', () => {
      const file = makeFile(0);
      expect(validateFileSize(file)).toBe(true);
    });
  });

  // ── releaseUrl ─────────────────────────────────────────────────────────────

  describe('releaseUrl', () => {
    beforeEach(() => {
      URL.revokeObjectURL = vi.fn();
    });

    afterEach(() => {
      delete URL.revokeObjectURL;
    });

    it('calls URL.revokeObjectURL for a blob URL', () => {
      releaseUrl('blob:https://example.com/1234');
      expect(URL.revokeObjectURL).toHaveBeenCalledWith(
        'blob:https://example.com/1234'
      );
    });

    it('does not call URL.revokeObjectURL for a non-blob URL', () => {
      releaseUrl('https://example.com/logo.png');
      expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    });

    it('does not throw when url is null', () => {
      expect(() => releaseUrl(null)).not.toThrow();
    });

    it('does not throw when url is undefined', () => {
      expect(() => releaseUrl(undefined)).not.toThrow();
    });

    it('does not throw when url is an empty string', () => {
      expect(() => releaseUrl('')).not.toThrow();
    });
  });

  // ── getFilenameWithoutExtension ────────────────────────────────────────────

  describe('getFilenameWithoutExtension', () => {
    it('removes a single extension from a filename', () => {
      expect(getFilenameWithoutExtension('logo.png')).toBe('logo');
    });

    it('removes only the last extension from a filename with multiple dots', () => {
      expect(getFilenameWithoutExtension('my.logo.png')).toBe('my.logo');
    });

    it('handles filenames with no extension', () => {
      expect(getFilenameWithoutExtension('logo')).toBe('logo');
    });

    it('handles filenames with a .jpg extension', () => {
      expect(getFilenameWithoutExtension('channel-logo.jpg')).toBe(
        'channel-logo'
      );
    });

    it('handles filenames with a .svg extension', () => {
      expect(getFilenameWithoutExtension('icon.svg')).toBe('icon');
    });

    it('handles an empty string', () => {
      expect(getFilenameWithoutExtension('')).toBe('');
    });

    it('handles a filename that is just an extension', () => {
      expect(getFilenameWithoutExtension('.png')).toBe('');
    });
  });
});
