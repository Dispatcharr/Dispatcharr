import { describe, it, expect } from 'vitest';
import { getConfirmationDetails } from '../PluginCardUtils';

describe('PluginCardUtils', () => {
  describe('getConfirmationDetails', () => {
    it('requires confirmation when action.confirm is true', () => {
      const action = { label: 'Test Action', confirm: true };
      const plugin = { name: 'Test Plugin' };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result).toEqual({
        requireConfirm: true,
        confirmTitle: 'Run Test Action?',
        confirmMessage:
          'You\'re about to run "Test Action" from "Test Plugin".',
      });
    });

    it('does not require confirmation when action.confirm is false', () => {
      const action = { label: 'Test Action', confirm: false };
      const plugin = { name: 'Test Plugin' };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(false);
    });

    it('uses custom title and message from action.confirm object', () => {
      const action = {
        label: 'Test Action',
        confirm: {
          required: true,
          title: 'Custom Title',
          message: 'Custom message',
        },
      };
      const plugin = { name: 'Test Plugin' };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result).toEqual({
        requireConfirm: true,
        confirmTitle: 'Custom Title',
        confirmMessage: 'Custom message',
      });
    });

    it('requires confirmation when action.confirm.required is not explicitly false', () => {
      const action = {
        label: 'Test Action',
        confirm: {
          title: 'Custom Title',
        },
      };
      const plugin = { name: 'Test Plugin' };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(true);
    });

    it('does not require confirmation when action.confirm.required is false', () => {
      const action = {
        label: 'Test Action',
        confirm: {
          required: false,
          title: 'Custom Title',
        },
      };
      const plugin = { name: 'Test Plugin' };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(false);
    });

    it('uses confirm field from plugin when action.confirm is undefined', () => {
      const action = { label: 'Test Action' };
      const plugin = {
        name: 'Test Plugin',
        fields: [{ id: 'confirm', default: true }],
      };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(true);
    });

    it('uses settings value over field default', () => {
      const action = { label: 'Test Action' };
      const plugin = {
        name: 'Test Plugin',
        fields: [{ id: 'confirm', default: false }],
      };
      const settings = { confirm: true };
      const result = getConfirmationDetails(action, plugin, settings);

      expect(result.requireConfirm).toBe(true);
    });

    it('uses field default when settings value is undefined', () => {
      const action = { label: 'Test Action' };
      const plugin = {
        name: 'Test Plugin',
        fields: [{ id: 'confirm', default: true }],
      };
      const settings = {};
      const result = getConfirmationDetails(action, plugin, settings);

      expect(result.requireConfirm).toBe(true);
    });

    it('does not require confirmation when no confirm configuration exists', () => {
      const action = { label: 'Test Action' };
      const plugin = { name: 'Test Plugin' };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(false);
    });

    it('handles plugin without fields array', () => {
      const action = { label: 'Test Action' };
      const plugin = { name: 'Test Plugin' };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(false);
    });

    it('handles null or undefined settings', () => {
      const action = { label: 'Test Action' };
      const plugin = {
        name: 'Test Plugin',
        fields: [{ id: 'confirm', default: true }],
      };
      const result = getConfirmationDetails(action, plugin, null);

      expect(result.requireConfirm).toBe(true);
    });

    it('converts truthy confirm field values to boolean', () => {
      const action = { label: 'Test Action' };
      const plugin = {
        name: 'Test Plugin',
        fields: [{ id: 'confirm', default: 1 }],
      };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(true);
    });

    it('handles confirm field with null default', () => {
      const action = { label: 'Test Action' };
      const plugin = {
        name: 'Test Plugin',
        fields: [{ id: 'confirm', default: null }],
      };
      const result = getConfirmationDetails(action, plugin, {});

      expect(result.requireConfirm).toBe(false);
    });
  });
});
