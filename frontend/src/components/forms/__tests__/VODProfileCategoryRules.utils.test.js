import { describe, expect, it } from 'vitest';
import { resolveProfileCategoryRows } from '../VODProfileCategoryRules.utils.js';

const categories = {
  1: {
    id: 1,
    name: 'Hindi Movies',
    category_type: 'movie',
    m3u_accounts: [
      {
        id: 101,
        m3u_account: 10,
        account_name: 'Provider A',
        enabled: true,
        metadata_defaults: {},
      },
    ],
  },
  2: {
    id: 2,
    name: 'English Movies',
    category_type: 'movie',
    m3u_accounts: [
      {
        id: 102,
        m3u_account: 20,
        account_name: 'Provider B',
        enabled: true,
        metadata_defaults: {},
      },
    ],
  },
};

describe('resolveProfileCategoryRows', () => {
  it('keeps the legacy all-enabled behavior without a saved allowlist', () => {
    const rows = resolveProfileCategoryRows(
      categories,
      { hard_constraints: {}, category_rules: [] },
      'movie'
    );

    expect(rows.map((row) => row.enabled)).toEqual([true, true]);
  });

  it('keeps a legacy exact allowlist until dynamic rules are configured', () => {
    const rows = resolveProfileCategoryRows(
      categories,
      {
        hard_constraints: {},
        category_rules: [{ category_relation: 101, enabled: true }],
      },
      'movie'
    );

    expect(
      Object.fromEntries(rows.map((row) => [row.relation_id, row.enabled]))
    ).toEqual({ 101: true, 102: false });
  });

  it('applies first-match provider rules and blocks unmatched categories', () => {
    const profile = {
      hard_constraints: {
        category_import_rules: [
          {
            id: 'provider-a-hindi',
            scope: 'movie',
            m3u_account_id: 10,
            regex_pattern: 'hindi',
            action: 'enable',
          },
          {
            id: 'block-hindi-later',
            scope: 'movie',
            regex_pattern: 'hindi',
            action: 'disable',
          },
        ],
      },
      category_rules: [],
    };

    const rows = resolveProfileCategoryRows(categories, profile, 'movie');

    expect(
      Object.fromEntries(rows.map((row) => [row.relation_id, row.enabled]))
    ).toEqual({ 101: true, 102: false });
    expect(rows.find((row) => row.relation_id === 101).decision_source).toBe(
      'Import rule'
    );
  });

  it('lets a manual choice override a dynamic rule', () => {
    const rows = resolveProfileCategoryRows(
      categories,
      {
        hard_constraints: {
          category_import_rules: [
            {
              id: 'allow-all',
              scope: 'movie',
              regex_pattern: '.*',
              action: 'enable',
            },
          ],
        },
        category_rules: [{ category_relation: 101, enabled: false }],
      },
      'movie'
    );

    expect(rows.find((row) => row.relation_id === 101)).toMatchObject({
      enabled: false,
      decision_source: 'Manual override',
    });
  });
});
