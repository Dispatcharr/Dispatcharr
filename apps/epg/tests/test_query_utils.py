"""Tests for the shared EPG / series-rule text query parser."""

from datetime import timedelta

from django.db.models import Q
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.epg.models import EPGData, EPGSource, ProgramData
from apps.epg.query_utils import (
    _mask_regex_groups,
    _paren_matches,
    build_q_object,
    match_none,
    parse_text_query,
    validate_program_text_query,
)


class ParenMatchesTests(SimpleTestCase):
    def test_pairs_nested_parentheses(self):
        self.assertEqual(_paren_matches('(a(b)c)'), {0: 6, 2: 4})

    def test_escaped_parentheses_are_ignored(self):
        self.assertEqual(_paren_matches(r'\(a\)(b)'), {5: 7})

    def test_escaped_backslash_does_not_escape_the_paren(self):
        self.assertEqual(_paren_matches(r'\\(a)'), {2: 4})

    def test_unbalanced_parentheses_are_left_out(self):
        self.assertEqual(_paren_matches('(a(b)'), {2: 4})
        self.assertEqual(_paren_matches('a)b'), {})


class MaskRegexGroupsTests(SimpleTestCase):
    def mask(self, text, quoted=None):
        groups = {}
        return _mask_regex_groups(text, quoted or {}, groups), groups

    def test_masks_only_groups_that_start_with_question_mark(self):
        masked, groups = self.mask('a(?:b)c(d)')
        self.assertEqual(list(groups.values()), ['(?:b)'])
        self.assertEqual(masked, 'a' + next(iter(groups)) + 'c(d)')

    def test_nested_group_is_masked_as_one_unit(self):
        _, groups = self.mask('(?:a(?!b)c)')
        self.assertEqual(list(groups.values()), ['(?:a(?!b)c)'])

    def test_escaped_parens_are_masked_individually(self):
        masked, groups = self.mask(r'Show \(?2024\)?')
        self.assertEqual(list(groups.values()), [r'\(', r'\)'])
        first, second = groups
        self.assertEqual(masked, f'Show {first}?2024{second}?')

    def test_escaped_backslash_does_not_escape_the_paren(self):
        masked, groups = self.mask(r'\\(a)')
        self.assertEqual(masked, r'\\(a)')
        self.assertEqual(groups, {})

    def test_group_followed_by_a_quantifier_is_masked(self):
        for pattern, group in (
            ('^(The )?Daily', '(The )'),
            ('(foo)+bar', '(foo)'),
            ('a(b|c)*d', '(b|c)'),
            (r'(\d+){2}', r'(\d+)'),
        ):
            with self.subTest(pattern=pattern):
                masked, groups = self.mask(pattern)
                self.assertEqual(list(groups.values()), [group])
                self.assertNotIn('(', masked)

    def test_group_without_a_quantifier_is_left_for_the_parser(self):
        for pattern in ('(Devils|Rangers)', '^(Devils|Rangers)', 'Show (2024)',
                        '(a OR b)', '(foo) bar'):
            with self.subTest(pattern=pattern):
                masked, groups = self.mask(pattern)
                self.assertEqual(masked, pattern)
                self.assertEqual(groups, {})

    def test_quantified_group_inside_a_boolean_group_is_masked_alone(self):
        masked, groups = self.mask('(foo OR (bar)?)')
        self.assertEqual(list(groups.values()), ['(bar)'])
        self.assertTrue(masked.startswith('(foo OR '))

    def test_parentheses_inside_a_bracket_expression_are_masked_with_it(self):
        for pattern, span in (
            ('foo[(]bar', '[(]'),
            ('a[()]b', '[()]'),
            ('a[^](]b', '[^](]'),
            (r'a[\(]b', r'[\(]'),
            ('x[[:digit:]()]y', '[[:digit:]()]'),
        ):
            with self.subTest(pattern=pattern):
                masked, groups = self.mask(pattern)
                self.assertEqual(list(groups.values()), [span])
                self.assertNotIn('(', masked)
                self.assertNotIn(')', masked)

    def test_a_bracket_expression_without_parentheses_is_left_alone(self):
        masked, groups = self.mask('a[bc]d OR e')
        self.assertEqual(masked, 'a[bc]d OR e')
        self.assertEqual(groups, {})

    def test_an_unclosed_bracket_expression_is_left_alone(self):
        masked, groups = self.mask('foo[(bar')
        self.assertEqual(masked, 'foo[(bar')
        self.assertEqual(groups, {})

    def test_parentheses_free_text_is_returned_unchanged(self):
        masked, groups = self.mask('^Devils OR Rangers$')
        self.assertEqual(masked, '^Devils OR Rangers$')
        self.assertEqual(groups, {})

    def test_group_after_an_escaped_backslash_is_masked(self):
        _, groups = self.mask(r'\\(?!x)')
        self.assertEqual(list(groups.values()), ['(?!x)'])

    def test_unbalanced_group_is_left_alone(self):
        masked, groups = self.mask('^(?!foo')
        self.assertEqual(masked, '^(?!foo')
        self.assertEqual(groups, {})

    def test_a_balanced_group_after_an_unbalanced_one_is_still_masked(self):
        _, groups = self.mask('(?foo (?!bar)')
        self.assertEqual(list(groups.values()), ['(?!bar)'])

    def test_quoted_phrase_inside_a_group_is_restored_as_typed(self):
        _, groups = self.mask('(?<=\x00P0\x00)', quoted={'\x00P0\x00': 'foo'})
        self.assertEqual(list(groups.values()), ['(?<="foo")'])


class ParseTextQueryRegexTests(SimpleTestCase):
    """Regex mode keeps `(?...)` groups inside a term and still parses AND/OR."""

    def parse(self, value):
        return parse_text_query('title', value, use_regex=True)

    def test_lookahead_is_a_single_regex(self):
        pattern = r'^(?!.*upcoming).*Devils'
        self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_noncapturing_group_stays_in_the_term(self):
        pattern = r'a(?:b|c)d'
        self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_nested_extension_group_is_one_regex(self):
        pattern = r'(?:a(?!b)c)'
        self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_flag_group_stays_with_its_term_when_or_is_used(self):
        self.assertEqual(
            self.parse(r'(?i)devils OR rangers'),
            Q(title__iregex='(?i)devils') | Q(title__iregex='rangers'),
        )

    def test_lookahead_or_other_term_keeps_both(self):
        self.assertEqual(
            self.parse(r'^(?!.*upcoming).*Devils OR Rangers'),
            Q(title__iregex=r'^(?!.*upcoming).*Devils') | Q(title__iregex='Rangers'),
        )

    def test_and_or_inside_a_group_are_regex_text(self):
        pattern = r'(?!.*upcoming OR live).*Devils'
        self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_quoted_pattern_is_one_regex(self):
        self.assertEqual(
            self.parse(r'"^(?!.*upcoming).*Devils"'),
            Q(title__iregex=r'^(?!.*upcoming).*Devils'),
        )

    def test_quoted_phrase_inside_a_group_keeps_its_quotes(self):
        pattern = r'(?<="foo")'
        self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_parentheses_inside_a_bracket_expression_are_one_regex(self):
        for pattern in ('foo[(]bar', 'a[()]b', 'a[^](]b', 'foo[(]bar OR baz'):
            with self.subTest(pattern=pattern):
                if pattern.endswith('OR baz'):
                    self.assertEqual(
                        self.parse(pattern),
                        Q(title__iregex='foo[(]bar') | Q(title__iregex='baz'),
                    )
                else:
                    self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_contains_mode_still_splits_parentheses_inside_brackets(self):
        self.assertEqual(
            parse_text_query('title', 'foo[(]bar'),
            match_none(),
        )

    def test_escaped_parens_are_literal_regex_text(self):
        for pattern in (
            r'Show \(2024\)',
            r'\(Live\)$',
            r'Game \d+ \(Live\)',
            r'Show \(?2024\)?',
        ):
            with self.subTest(pattern=pattern):
                self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_escaped_parens_still_split_on_or(self):
        self.assertEqual(
            self.parse(r'\(Live\) OR Replay'),
            Q(title__iregex=r'\(Live\)') | Q(title__iregex='Replay'),
        )

    def test_group_followed_by_a_quantifier_is_one_regex(self):
        for pattern in (
            r'^(The )?Daily Show',
            r'(foo)+bar',
            r'(\d+){2}',
            r'a(b|c)*d',
        ):
            with self.subTest(pattern=pattern):
                self.assertEqual(self.parse(pattern), Q(title__iregex=pattern))

    def test_quantified_group_with_or_keeps_both_terms(self):
        self.assertEqual(
            self.parse(r'^(The )?Daily Show OR Rangers'),
            Q(title__iregex=r'^(The )?Daily Show') | Q(title__iregex='Rangers'),
        )

    def test_alternation_parens_without_extension_syntax_are_unchanged(self):
        self.assertEqual(
            self.parse(r'(Devils|Rangers)'), Q(title__iregex='Devils|Rangers')
        )

    def test_anchor_outside_a_plain_group_is_unchanged(self):
        self.assertEqual(
            self.parse(r'^(Devils|Rangers)'),
            Q(title__iregex='^') & Q(title__iregex='Devils|Rangers'),
        )

    def test_implicit_and_around_plain_parens_is_unchanged(self):
        self.assertEqual(
            self.parse('Show (2024)'),
            Q(title__iregex='Show') & Q(title__iregex='2024'),
        )

    def test_boolean_groups_are_unchanged(self):
        self.assertEqual(
            self.parse('(Newcastle OR NEW) AND (Villa OR AST)'),
            (Q(title__iregex='Newcastle') | Q(title__iregex='NEW'))
            & (Q(title__iregex='Villa') | Q(title__iregex='AST')),
        )

    def test_question_mark_outside_a_group_does_not_mask_boolean_parens(self):
        self.assertEqual(
            self.parse('what? (foo OR bar)'),
            Q(title__iregex='what?')
            & (Q(title__iregex='foo') | Q(title__iregex='bar')),
        )


class ParseTextQueryOtherModesTests(SimpleTestCase):
    """Only regex mode keeps `(?...)` together. Other modes are unchanged."""

    def test_contains_mode_still_treats_the_parens_as_a_group(self):
        self.assertEqual(
            parse_text_query('title', '(?!foo)'), Q(title__icontains='?!foo')
        )

    def test_contains_boolean_groups_are_unchanged(self):
        self.assertEqual(
            parse_text_query('title', '(Newcastle OR Football) AND (Villa OR League)'),
            (Q(title__icontains='Newcastle') | Q(title__icontains='Football'))
            & (Q(title__icontains='Villa') | Q(title__icontains='League')),
        )

    def test_whole_word_mode_still_treats_the_parens_as_a_group(self):
        self.assertEqual(
            parse_text_query('title', '(?i)devils', whole_words=True),
            build_q_object('title', '?i', whole_words=True)
            & build_q_object('title', 'devils', whole_words=True),
        )

    def test_quantifier_after_a_group_is_not_regex_outside_regex_mode(self):
        self.assertEqual(
            parse_text_query('title', '(foo)?'),
            Q(title__icontains='foo') & Q(title__icontains='?'),
        )

    def test_quoted_phrase_next_to_other_text_expands_in_the_term(self):
        self.assertEqual(
            parse_text_query('title', '"foo" bar'),
            Q(title__icontains='foo bar'),
        )

    def test_quoted_phrase_with_and_still_splits_on_the_operator(self):
        self.assertEqual(
            parse_text_query('title', '"Law and Order" AND crime'),
            Q(title__icontains='Law and Order') & Q(title__icontains='crime'),
        )

    def test_unbalanced_paren_matches_nothing(self):
        self.assertEqual(parse_text_query('title', '(foo'), match_none())
        self.assertEqual(parse_text_query('title', 'Devils ('), match_none())
        self.assertEqual(
            parse_text_query('title', r'^(?!foo', use_regex=True), match_none()
        )


class RegexExtensionPostgresTests(TestCase):
    """Patterns that used to fail in the database are valid once groups stay intact."""

    TITLES = frozenset((
        'Devils at the Garden',
        'upcoming Devils preview',
        'Rangers at home',
        'abd',
        'acd',
        'a b d',
        'Show (2024)',
        'Show 2024',
        'The Daily Show',
        'Daily Show',
        'Late Night Daily Show',
        'foo(bar',
        'a(b',
        'a)b',
        'foobar',
    ))

    @classmethod
    def setUpTestData(cls):
        source = EPGSource.objects.create(name='query-utils-regex', source_type='xmltv')
        epg = EPGData.objects.create(
            name='Query Utils EPG', tvg_id='query-utils-regex', epg_source=source
        )
        now = timezone.now()
        for title in cls.TITLES:
            ProgramData.objects.create(
                epg=epg,
                title=title,
                start_time=now,
                end_time=now + timedelta(hours=1),
            )

    def _titles(self, pattern):
        """Titles from this class's fixtures that the regex query matches."""
        query = parse_text_query('title', pattern, use_regex=True)
        found = ProgramData.objects.filter(query).values_list('title', flat=True)
        return set(found) & self.TITLES

    def test_lookahead_matches_only_titles_that_fit_the_pattern(self):
        titles = self._titles(r'^(?!.*upcoming).*Devils')
        self.assertIn('Devils at the Garden', titles)
        self.assertNotIn('upcoming Devils preview', titles)

    def test_noncapturing_group_matches_the_regex_not_separate_letters(self):
        titles = self._titles(r'a(?:b|c)d')
        self.assertEqual(titles & {'abd', 'acd', 'a b d'}, {'abd', 'acd'})

    def test_flag_group_or_matches_either_term(self):
        titles = self._titles(r'(?i)devils OR rangers')
        self.assertIn('Devils at the Garden', titles)
        self.assertIn('Rangers at home', titles)
        self.assertNotIn('abd', titles)

    def test_or_inside_a_lookahead_is_regex_text(self):
        titles = self._titles(r'^(?!.*(?:upcoming|home)).*(?:Devils|Rangers)')
        self.assertIn('Devils at the Garden', titles)
        self.assertNotIn('upcoming Devils preview', titles)
        self.assertNotIn('Rangers at home', titles)

    def test_bracket_expression_matches_a_literal_parenthesis(self):
        self.assertEqual(self._titles('foo[(]bar'), {'foo(bar'})
        self.assertEqual(self._titles('a[()]b'), {'a(b', 'a)b'})

    def test_escaped_parens_match_literal_parentheses(self):
        self.assertEqual(self._titles(r'Show \(2024\)'), {'Show (2024)'})

    def test_optional_group_matches_with_and_without_the_prefix(self):
        self.assertEqual(
            self._titles(r'^(The )?Daily Show'), {'The Daily Show', 'Daily Show'}
        )

    def test_quantified_group_containing_escaped_parens_matches_the_regex(self):
        self.assertEqual(
            self._titles(r'^Show (\(?2024\)?)?$'), {'Show (2024)', 'Show 2024'}
        )

    def test_quoted_phrase_next_to_other_text_does_not_raise(self):
        # The joined term is "Devils at the", which is a substring of the title.
        titles = set(
            ProgramData.objects.filter(
                parse_text_query('title', '"Devils at" the')
            ).values_list('title', flat=True)
        )
        self.assertIn('Devils at the Garden', titles)

    def test_unbalanced_paren_matches_no_rows(self):
        self.assertEqual(self._titles('Devils ('), set())

    def test_validate_rejects_an_invalid_regex(self):
        error = validate_program_text_query(
            'title', r'(?<league>x)', use_regex=True
        )
        self.assertIsNotNone(error)
        # A valid pattern that matches no row still compiles.
        self.assertIsNone(
            validate_program_text_query(
                'title', r'^no-such-program-title$', use_regex=True
            )
        )

    def test_validate_ignores_contains_terms(self):
        self.assertIsNone(validate_program_text_query('title', 'Devils ('))
