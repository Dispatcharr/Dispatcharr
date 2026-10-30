import { describe, expect, it } from 'vitest';
import {
  findDuplicateRule,
  getRuleCoverage,
  ruleCheckSignature,
} from '../M3URulesEditor.utils.js';
const rule = (id, regex_pattern, props = {}) => ({
  id,
  regex_pattern,
  enabled: true,
  match_field: 'group_name',
  case_sensitive: false,
  ...props,
});
describe('save-time duplicate validation', () => {
  it('excludes paused stream filters from duplicate checks, coverage and cached signatures', () => {
    const active = rule(1, '.*', { filter_type: 'name' });
    const paused = rule(2, '.*', { filter_type: 'name', enabled: false });
    expect(findDuplicateRule(paused, [active], true)).toBeUndefined();
    expect(findDuplicateRule(active, [paused], true)).toBeUndefined();
    expect(ruleCheckSignature([active], true)).not.toBe(
      ruleCheckSignature([{ ...active, enabled: false }], true)
    );
    expect(
      getRuleCoverage(
        [paused, active],
        {
          inventory_count: 10,
          rule_coverage: [
            { rule_id: '2', count: 0 },
            { rule_id: '1', count: 10 },
          ],
        },
        true
      ).coveredBy
    ).toEqual({});
  });
  it.each(['keep'])(
    'does not let a paused %s rule block supported predicates or affect coverage',
    (action) => {
      const retired = rule(1, 'News', { action });
      expect(
        findDuplicateRule(rule(2, 'News', { action: 'enable' }), [retired])
      ).toBeUndefined();
      expect(
        getRuleCoverage([retired], {
          inventory_count: 1,
          rule_coverage: [{ rule_id: '1', count: 1 }],
        })
      ).toEqual({ causes: {}, coveredBy: {} });
    }
  );
  it('rejects duplicate import predicates even for different metadata and invalidates cached checks', () => {
    const audio = rule(1, 'GER', {
      action: 'enable',
      metadata_defaults: { audio_languages: ['ger'] },
    });
    const resolution = rule(2, 'GER', {
      action: 'enable',
      metadata_defaults: { resolution: '1080p' },
    });
    expect(findDuplicateRule(resolution, [audio])).toBe(audio);
    expect(
      findDuplicateRule(
        { ...resolution, metadata_defaults: { audio_languages: ['eng'] } },
        [audio]
      )
    ).toBe(audio);
    expect(ruleCheckSignature([audio])).not.toBe(
      ruleCheckSignature([
        { ...audio, metadata_defaults: { audio_languages: ['eng'] } },
      ])
    );
  });
  it('finds identical active predicates even with different results, excluding itself', () => {
    const saved = rule(1, 'News', { action: 'enable' });
    expect(
      findDuplicateRule(rule(2, 'News', { action: 'disable' }), [saved])
    ).toBe(saved);
    expect(findDuplicateRule(saved, [saved])).toBeUndefined();
  });
  it('distinguishes content scopes, case and disabled rules', () => {
    const saved = rule(1, 'News');
    for (const values of [
      { case_sensitive: true },
      { enabled: false },
      { scope: 'movie' },
    ])
      expect(
        findDuplicateRule(rule(2, 'News', values), [saved])
      ).toBeUndefined();
    expect(
      findDuplicateRule(rule(2, 'News'), [rule(1, 'News', { enabled: false })])
    ).toBeUndefined();
  });
  it('does not block Python-only or invalid regex syntax', () => {
    expect(
      findDuplicateRule(rule(1, '(?i)News'), [rule(2, '[')])
    ).toBeUndefined();
  });
  it('distinguishes stream filter targets', () => {
    expect(
      findDuplicateRule(
        rule(1, 'News', { filter_type: 'name' }),
        [rule(2, 'News', { filter_type: 'url' })],
        true
      )
    ).toBeUndefined();
  });
  it('does not evaluate arbitrary potentially expensive regexes in the UI', () => {
    expect(
      findDuplicateRule(rule(1, '(a?){100000000}'), [rule(2, 'News')])
    ).toBeUndefined();
  });
  it('signs only relevant matching fields, results, identities and order', () => {
    const saved = rule(1, 'News', {
      filter_type: 'name',
      order: 0,
      custom_properties: { case_sensitive: false, note: 'one' },
    });
    expect(ruleCheckSignature([saved], true)).toBe(
      ruleCheckSignature(
        [
          {
            ...saved,
            custom_properties: { note: 'two', case_sensitive: false },
          },
        ],
        true
      )
    );
    expect(ruleCheckSignature([saved], true)).not.toBe(
      ruleCheckSignature([{ ...saved, order: 1 }], true)
    );
  });
});

describe('inventory-based regex coverage', () => {
  it('marks all fields as covered even when different earlier rules win them', () => {
    const rows = [
      rule(1, '.*', {
        action: 'enable',
        metadata_defaults: { audio_languages: ['ger'] },
      }),
      rule(2, '.*', {
        action: 'enable',
        metadata_defaults: { resolution: '1080p' },
      }),
      rule(3, 'GER', {
        action: 'enable',
        metadata_defaults: { audio_languages: ['eng'], resolution: '720p' },
      }),
    ];
    expect(
      getRuleCoverage(rows, {
        inventory_count: 10,
        rule_coverage: [
          {
            rule_id: '1',
            count: 10,
            field_counts: { import: 10, audio_languages: 10 },
          },
          {
            rule_id: '2',
            count: 10,
            field_counts: { import: 0, resolution: 10 },
          },
          {
            rule_id: '3',
            count: 0,
            field_counts: { import: 0, audio_languages: 0, resolution: 0 },
          },
        ],
      }).coveredBy
    ).toEqual({ 3: [1, 2] });
  });
  it('does not mark metadata rules as covered by an import catch-all, but covers the same metadata field', () => {
    const rows = [
      rule(1, '.*', { action: 'enable' }),
      rule(2, '.*', {
        action: 'enable',
        metadata_defaults: { audio_languages: ['ger'] },
      }),
      rule(3, 'GER', {
        action: 'enable',
        metadata_defaults: { audio_languages: ['eng'], resolution: '1080p' },
      }),
      rule(4, 'GER', {
        action: 'enable',
        metadata_defaults: { audio_languages: ['eng'] },
      }),
    ];
    const coverage = getRuleCoverage(rows, {
      inventory_count: 10,
      rule_coverage: [
        { rule_id: '1', count: 10, field_counts: { import: 10 } },
        { rule_id: '2', count: 10, field_counts: { audio_languages: 10 } },
        {
          rule_id: '3',
          count: 3,
          field_counts: { audio_languages: 0, resolution: 3 },
        },
        { rule_id: '4', count: 0, field_counts: { audio_languages: 0 } },
      ],
    });
    expect(coverage.coveredBy).toEqual({ 4: [1, 2] });
    expect(coverage.causes[2].summary).toContain('DUB');
    expect(coverage.causes[2].message).not.toContain('DUB');
    expect(coverage.causes[2].message).not.toContain(
      'Later rules have no matches'
    );
  });
  it('deduplicates the regex notice across fields while retaining detailed markers and blockers', () => {
    const metadata_defaults = {
      audio_languages: ['eng'],
      subtitle_languages: ['ger'],
      resolution: '1080p',
      video_features: ['hdr'],
    };
    const rows = [
      rule(1, '.*', { action: 'enable', metadata_defaults }),
      rule(2, 'News', { action: 'enable', metadata_defaults }),
    ];
    const coverage = getRuleCoverage(rows, {
      inventory_count: 500,
      rule_coverage: [
        {
          rule_id: '1',
          count: 500,
          field_counts: Object.fromEntries(
            ['import', ...Object.keys(metadata_defaults)].map((field) => [
              field,
              500,
            ])
          ),
        },
        {
          rule_id: '2',
          count: 0,
          field_counts: Object.fromEntries(
            ['import', ...Object.keys(metadata_defaults)].map((field) => [
              field,
              0,
            ])
          ),
        },
      ],
    });
    expect(coverage.causes[1].message).toBe(
      'Matches all 500 categories from the last refresh. Check whether this is intended. Later rules may have no effect.'
    );
    expect(coverage.causes[1].details.match(/Matches all 500/g)).toHaveLength(
      1
    );
    for (const label of [
      'Import selection',
      'DUB',
      'SUB',
      'Resolution',
      'Features',
    ]) {
      expect(coverage.causes[1].summary).toContain(`${label}:`);
      expect(coverage.causes[1].message).not.toContain(`${label}:`);
    }
    expect(coverage.coveredBy).toEqual({ 2: 1 });
  });

  it('keeps genuinely different remaining-inventory warnings instead of merging their counts', () => {
    const rows = [
      rule(1, '^A', {
        action: 'enable',
        metadata_defaults: { audio_languages: ['eng'] },
      }),
      rule(2, '^B', {
        action: 'enable',
        metadata_defaults: { subtitle_languages: ['eng'] },
      }),
      rule(3, '.*', {
        action: 'enable',
        metadata_defaults: {
          audio_languages: ['ger'],
          subtitle_languages: ['ger'],
        },
      }),
      rule(4, 'News', {
        action: 'enable',
        metadata_defaults: {
          audio_languages: ['fre'],
          subtitle_languages: ['fre'],
        },
      }),
    ];
    const coverage = getRuleCoverage(rows, {
      inventory_count: 10,
      rule_coverage: [
        {
          rule_id: '1',
          count: 5,
          field_counts: { import: 5, audio_languages: 5 },
        },
        {
          rule_id: '2',
          count: 3,
          field_counts: { import: 3, subtitle_languages: 3 },
        },
        {
          rule_id: '3',
          count: 7,
          field_counts: {
            import: 2,
            audio_languages: 5,
            subtitle_languages: 7,
          },
        },
        {
          rule_id: '4',
          count: 0,
          field_counts: {
            import: 0,
            audio_languages: 0,
            subtitle_languages: 0,
          },
        },
      ],
    });
    for (const count of [2, 5, 7])
      expect(coverage.causes[3].message).toContain(`all ${count} remaining`);
    expect(coverage.causes[3].message.match(/Check whether/g)).toHaveLength(1);
    expect(coverage.coveredBy[4]).toBe(3);
  });
  const preview = (counts) => ({
    inventory_count: 10,
    rule_coverage: counts.map((count, index) => ({
      rule_id: String(index + 1),
      count,
    })),
  });
  it.each(['News|Sport', '[\\s\\S]+', '.*', '(?i)news|sport'])(
    'uses actual counts, not a special pattern check: %s',
    (pattern) => {
      const coverage = getRuleCoverage(
        [rule(1, pattern), rule(2, 'Sport')],
        preview([10, 0])
      );
      expect(coverage.causes[1].summary).toContain('Matches all 10 categories');
      expect(coverage.causes[2]).toBeUndefined();
      expect(coverage.coveredBy).toEqual({ 2: 1 });
    }
  );
  it('does not infer universality or warn about ordinary partial matches', () => {
    expect(
      getRuleCoverage([rule(1, '.*'), rule(2, 'Sport')], preview([3, 4]))
    ).toEqual({ causes: {}, coveredBy: {} });
    expect(
      getRuleCoverage([rule(1, '.*')], {
        inventory_count: 0,
        rule_coverage: [],
      })
    ).toEqual({ causes: {}, coveredBy: {} });
  });
  it('warns when a non-final rule consumes the remaining inventory, not a normal final fallback', () => {
    const rows = [rule(1, 'News'), rule(2, 'Sport'), rule(3, 'Events')];
    expect(
      getRuleCoverage(rows, preview([3, 7, 0])).causes[2].summary
    ).toContain('all 7 remaining');
    expect(getRuleCoverage(rows.slice(0, 2), preview([3, 7]))).toEqual({
      causes: {},
      coveredBy: {},
    });
  });
  it('does not mark disabled rules as covered', () => {
    const coverage = getRuleCoverage(
      [
        rule(1, 'News|Sport'),
        rule(2, 'Sport', { enabled: false }),
        rule(3, 'News'),
      ],
      preview([10, 0, 0])
    );
    expect(coverage.coveredBy).toEqual({ 3: 1 });
  });
  it('keeps the cause identity stable when only covered rows move', () => {
    const rows = [rule(1, 'News|Sport'), rule(2, 'Sport'), rule(3, 'News')];
    const first = getRuleCoverage(rows, preview([10, 0, 0]));
    const second = getRuleCoverage(
      [rows[0], rows[2], rows[1]],
      preview([10, 0, 0])
    );
    expect(first.causes[1].key).toBe(second.causes[1].key);
  });
});
