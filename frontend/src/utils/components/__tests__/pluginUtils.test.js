import { describe, it, expect } from 'vitest';
import {
  compareVersions,
  buildCompatibilityTooltip,
  buildVersionSelectItems,
  getInstallInfo,
} from '../pluginUtils.js';

describe('pluginUtils', () => {
  // ───────────────────────────────────────────────────────────────────────────
  // compareVersions
  // ───────────────────────────────────────────────────────────────────────────
  describe('compareVersions', () => {
    // ── basic ordering ──────────────────────────────────────────────────────────
    describe('numeric ordering', () => {
      it('returns 0 for identical versions', () => {
        expect(compareVersions('1.2.3', '1.2.3')).toBe(0);
      });

      it('returns positive when a > b (major)', () => {
        expect(compareVersions('2.0.0', '1.9.9')).toBeGreaterThan(0);
      });

      it('returns negative when a < b (major)', () => {
        expect(compareVersions('1.0.0', '2.0.0')).toBeLessThan(0);
      });

      it('returns positive when a > b (minor)', () => {
        expect(compareVersions('1.3.0', '1.2.9')).toBeGreaterThan(0);
      });

      it('returns negative when a < b (minor)', () => {
        expect(compareVersions('1.2.0', '1.3.0')).toBeLessThan(0);
      });

      it('returns positive when a > b (patch)', () => {
        expect(compareVersions('1.0.2', '1.0.1')).toBeGreaterThan(0);
      });

      it('returns negative when a < b (patch)', () => {
        expect(compareVersions('1.0.1', '1.0.2')).toBeLessThan(0);
      });

      it('handles versions with different segment counts', () => {
        expect(compareVersions('1.2', '1.2.0')).toBe(0);
        expect(compareVersions('1.3', '1.2.9')).toBeGreaterThan(0);
      });
    });

    // ── v-prefix stripping ──────────────────────────────────────────────────────
    describe('v-prefix stripping', () => {
      it('strips leading "v" before comparing', () => {
        expect(compareVersions('v1.2.3', '1.2.3')).toBe(0);
        expect(compareVersions('v2.0.0', 'v1.0.0')).toBeGreaterThan(0);
        expect(compareVersions('v1.0.0', 'v2.0.0')).toBeLessThan(0);
      });
    });

    // ── prerelease fallback ─────────────────────────────────────────────────────
    describe('prerelease fallback (string equality)', () => {
      it('returns 0 for identical prerelease strings', () => {
        expect(compareVersions('1.0.0-beta.1', '1.0.0-beta.1')).toBe(0);
      });

      it('returns non-zero for different prerelease strings', () => {
        expect(compareVersions('1.0.0-beta.1', '1.0.0-beta.2')).not.toBe(0);
      });

      it('returns non-zero when one side is prerelease and the other is not', () => {
        expect(compareVersions('1.0.0-beta', '1.0.0')).not.toBe(0);
      });

      it('falls back to string equality even when one is numerically "larger"', () => {
        // '2.0.0-rc1' contains a non-digit segment so the prerelease path is taken
        expect(compareVersions('2.0.0-rc1', '1.0.0')).not.toBe(0);
      });
    });

    // ── null / undefined guards ─────────────────────────────────────────────────
    describe('null / undefined guards', () => {
      it('returns 0 when a is null', () => {
        expect(compareVersions(null, '1.0.0')).toBe(0);
      });

      it('returns 0 when b is null', () => {
        expect(compareVersions('1.0.0', null)).toBe(0);
      });

      it('returns 0 when both are null', () => {
        expect(compareVersions(null, null)).toBe(0);
      });

      it('returns 0 when a is undefined', () => {
        expect(compareVersions(undefined, '1.0.0')).toBe(0);
      });

      it('returns 0 when b is undefined', () => {
        expect(compareVersions('1.0.0', undefined)).toBe(0);
      });
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  // buildCompatibilityTooltip
  // ───────────────────────────────────────────────────────────────────────────
  describe('buildCompatibilityTooltip', () => {
    const vd = {
      min_dispatcharr_version: '2.0.0',
      max_dispatcharr_version: '3.0.0',
    };

    it('returns min constraint when only min is not met', () => {
      expect(buildCompatibilityTooltip(false, vd, true)).toBe('2.0.0 or newer');
    });

    it('returns max constraint when only max is not met', () => {
      expect(buildCompatibilityTooltip(true, vd, false)).toBe('3.0.0 or older');
    });

    it('returns both constraints joined by " and " when neither is met', () => {
      expect(buildCompatibilityTooltip(false, vd, false)).toBe(
        '2.0.0 or newer and 3.0.0 or older'
      );
    });

    it('returns an empty string when both constraints are met', () => {
      expect(buildCompatibilityTooltip(true, vd, true)).toBe('');
    });

    it('uses the actual version values from selectedVersionData', () => {
      const custom = {
        min_dispatcharr_version: '1.5.0',
        max_dispatcharr_version: '4.0.0',
      };
      expect(buildCompatibilityTooltip(false, custom, false)).toBe(
        '1.5.0 or newer and 4.0.0 or older'
      );
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  // buildVersionSelectItems
  // ───────────────────────────────────────────────────────────────────────────
  describe('buildVersionSelectItems', () => {
    // ── basic label building ────────────────────────────────────────────────────
    describe('label building', () => {
      it('prefixes every version value with "v" in the label', () => {
        const items = buildVersionSelectItems(
          [{ version: '1.0.0', prerelease: false }],
          '1.0.0',
          null,
          false
        );
        expect(items[0].label).toMatch(/^v1\.0\.0/);
      });

      it('appends "(latest)" for the latest version', () => {
        const items = buildVersionSelectItems(
          [{ version: '2.0.0', prerelease: false }],
          '2.0.0',
          null,
          false
        );
        expect(items[0].label).toContain('(latest)');
      });

      it('does not append "(latest)" for non-latest versions', () => {
        const items = buildVersionSelectItems(
          [
            { version: '2.0.0', prerelease: false },
            { version: '1.0.0', prerelease: false },
          ],
          '2.0.0',
          null,
          false
        );
        expect(items[1].label).not.toContain('(latest)');
      });

      it('appends "(installed)" for the currently installed version', () => {
        const items = buildVersionSelectItems(
          [
            { version: '2.0.0', prerelease: false },
            { version: '1.0.0', prerelease: false },
          ],
          '2.0.0',
          '1.0.0',
          false
        );
        const installed = items.find((i) => i.value === '1.0.0');
        expect(installed.label).toContain('(installed)');
      });

      it('does not append "(installed)" when installedVersion is null', () => {
        const items = buildVersionSelectItems(
          [{ version: '1.0.0', prerelease: false }],
          '1.0.0',
          null,
          false
        );
        expect(items[0].label).not.toContain('(installed)');
      });

      it('appends "(prerelease)" for prerelease versions', () => {
        const items = buildVersionSelectItems(
          [{ version: '2.0.0-beta', prerelease: true }],
          null,
          null,
          false
        );
        expect(items[0].label).toContain('(prerelease)');
      });

      it('does not append "(prerelease)" for stable versions', () => {
        const items = buildVersionSelectItems(
          [{ version: '1.0.0', prerelease: false }],
          null,
          null,
          false
        );
        expect(items[0].label).not.toContain('(prerelease)');
      });

      it('can combine multiple suffixes on one item (installed + latest)', () => {
        const items = buildVersionSelectItems(
          [{ version: '1.0.0', prerelease: false }],
          '1.0.0',
          '1.0.0',
          false
        );
        expect(items[0].label).toContain('(latest)');
        expect(items[0].label).toContain('(installed)');
      });

      it('all regular items have disabled: false', () => {
        const items = buildVersionSelectItems(
          [
            { version: '2.0.0', prerelease: false },
            { version: '1.0.0', prerelease: false },
          ],
          '2.0.0',
          null,
          false
        );
        items.forEach((item) => expect(item.disabled).toBe(false));
      });

      it('value property equals the raw version string (no "v" prefix)', () => {
        const items = buildVersionSelectItems(
          [{ version: '1.2.3', prerelease: false }],
          null,
          null,
          false
        );
        expect(items[0].value).toBe('1.2.3');
      });
    });

    // ── sort order (installedVersionIsPrerelease flag) ──────────────────────────
    describe('sort order', () => {
      const versions = [
        { version: '2.0.0', prerelease: false },
        { version: '2.0.0-beta', prerelease: true },
        { version: '1.0.0', prerelease: false },
      ];

      it('preserves manifest order when installedVersionIsPrerelease is false', () => {
        const items = buildVersionSelectItems(versions, '2.0.0', null, false);
        expect(items.map((i) => i.value)).toEqual([
          '2.0.0',
          '2.0.0-beta',
          '1.0.0',
        ]);
      });

      it('floats prereleases to the top when installedVersionIsPrerelease is true', () => {
        const items = buildVersionSelectItems(versions, '2.0.0', null, true);
        expect(items[0].value).toBe('2.0.0-beta');
      });

      it('stable versions follow all prereleases when installedVersionIsPrerelease is true', () => {
        const items = buildVersionSelectItems(versions, '2.0.0', null, true);
        const stableValues = items
          .filter((i) => !i.label.includes('(prerelease)'))
          .map((i) => i.value);
        expect(stableValues).toEqual(['2.0.0', '1.0.0']);
      });
    });

    // ── ghost item (installed version missing from manifest) ───────────────────
    describe('ghost item for missing installed version', () => {
      it('inserts a disabled ghost item when installed version is absent from manifest', () => {
        const items = buildVersionSelectItems(
          [
            { version: '2.0.0', prerelease: false },
            { version: '1.0.0', prerelease: false },
          ],
          '2.0.0',
          '1.5.0',
          false
        );
        const ghost = items.find((i) => i.value === '1.5.0');
        expect(ghost).toBeDefined();
        expect(ghost.disabled).toBe(true);
      });

      it('ghost item label is "v<version> (installed)"', () => {
        const items = buildVersionSelectItems(
          [
            { version: '2.0.0', prerelease: false },
            { version: '1.0.0', prerelease: false },
          ],
          '2.0.0',
          '1.5.0',
          false
        );
        const ghost = items.find((i) => i.value === '1.5.0');
        expect(ghost.label).toBe('v1.5.0 (installed)');
      });

      it('ghost item is inserted between the first newer and first older item', () => {
        const items = buildVersionSelectItems(
          [
            { version: '2.0.0', prerelease: false },
            { version: '1.0.0', prerelease: false },
          ],
          '2.0.0',
          '1.5.0',
          false
        );
        const values = items.map((i) => i.value);
        const ghostIdx = values.indexOf('1.5.0');
        const newerIdx = values.indexOf('2.0.0');
        const olderIdx = values.indexOf('1.0.0');
        expect(ghostIdx).toBeGreaterThan(newerIdx);
        expect(ghostIdx).toBeLessThan(olderIdx);
      });

      it('ghost item is appended at the end when installed is older than all manifest versions', () => {
        const items = buildVersionSelectItems(
          [
            { version: '3.0.0', prerelease: false },
            { version: '2.0.0', prerelease: false },
          ],
          '3.0.0',
          '1.0.0',
          false
        );
        const values = items.map((i) => i.value);
        expect(values[values.length - 1]).toBe('1.0.0');
      });

      it('does not insert a ghost item when installed version IS in the manifest', () => {
        const items = buildVersionSelectItems(
          [
            { version: '2.0.0', prerelease: false },
            { version: '1.0.0', prerelease: false },
          ],
          '2.0.0',
          '1.0.0',
          false
        );
        expect(items.filter((i) => i.disabled)).toHaveLength(0);
      });

      it('does not insert a ghost item when installedVersion is null', () => {
        const items = buildVersionSelectItems(
          [{ version: '1.0.0', prerelease: false }],
          '1.0.0',
          null,
          false
        );
        expect(items.filter((i) => i.disabled)).toHaveLength(0);
      });
    });

    // ── edge cases ──────────────────────────────────────────────────────────────
    describe('edge cases', () => {
      it('returns an empty array when versions is empty', () => {
        expect(buildVersionSelectItems([], null, null, false)).toEqual([]);
      });

      it('handles latestVersion being null — no "(latest)" label appended', () => {
        const items = buildVersionSelectItems(
          [{ version: '1.0.0', prerelease: false }],
          null,
          null,
          false
        );
        expect(items[0].label).not.toContain('(latest)');
      });

      it('does not mutate the original versions array', () => {
        const versions = [
          { version: '2.0.0', prerelease: false },
          { version: '2.0.0-beta', prerelease: true },
        ];
        const original = [...versions];
        buildVersionSelectItems(versions, '2.0.0', null, true);
        expect(versions).toEqual(original);
      });

      it('returns one item per version when no ghost is needed', () => {
        const versions = [
          { version: '3.0.0', prerelease: false },
          { version: '2.0.0', prerelease: false },
          { version: '1.0.0', prerelease: false },
        ];
        const items = buildVersionSelectItems(
          versions,
          '3.0.0',
          '2.0.0',
          false
        );
        expect(items).toHaveLength(3);
      });

      it('returns versions.length + 1 items when a ghost is inserted', () => {
        const versions = [
          { version: '2.0.0', prerelease: false },
          { version: '1.0.0', prerelease: false },
        ];
        const items = buildVersionSelectItems(
          versions,
          '2.0.0',
          '1.5.0',
          false
        );
        expect(items).toHaveLength(3);
      });
    });
  });

  // ───────────────────────────────────────────────────────────────────────────
  // getInstallInfo
  // ───────────────────────────────────────────────────────────────────────────
  describe('getInstallInfo', () => {
    it('returns isDowngrade true when pendingInstall is lower than installed_version', () => {
      const pendingInstall = { version: '1.0.0' };
      const plugin = { installed_version: '2.0.0', signature_verified: true };
      const info = getInstallInfo(pendingInstall, plugin);
      expect(info.isDowngrade).toBe(true);
      expect(info.isUpdate).toBe(false);
      expect(info.isBadSig).toBe(false);
    });

    it('returns isUpdate true when pendingInstall is higher than installed_version', () => {
      const pendingInstall = { version: '3.0.0' };
      const plugin = { installed_version: '2.0.0', signature_verified: true };
      const info = getInstallInfo(pendingInstall, plugin);
      expect(info.isDowngrade).toBe(false);
      expect(info.isUpdate).toBe(true);
      expect(info.isBadSig).toBe(false);
    });

    it('returns isBadSig true when signature_verified is false', () => {
      const pendingInstall = { version: '2.0.0' };
      const plugin = { installed_version: '2.0.0', signature_verified: false };
      const info = getInstallInfo(pendingInstall, plugin);
      expect(info.isDowngrade).toBe(false);
      expect(info.isUpdate).toBe(false);
      expect(info.isBadSig).toBe(true);
    });

    it('returns all false when no conditions are met', () => {
      const pendingInstall = { version: '2.0.0' };
      const plugin = { installed_version: '2.0.0', signature_verified: true };
      const info = getInstallInfo(pendingInstall, plugin);
      expect(info.isDowngrade).toBe(false);
      expect(info.isUpdate).toBe(false);
      expect(info.isBadSig).toBe(false);
    });
  });
});
