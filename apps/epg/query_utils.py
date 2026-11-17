"""Shared query parsing helpers for EPG program text search.

Used by the EPG search API and the DVR series rule evaluator to apply
the same boolean / quoted-phrase / regex / whole-word matching semantics.

Public API:
    parse_text_query(field, raw_value, use_regex=False, whole_words=False) -> Q
    validate_program_text_query(field, raw_value, use_regex=False, whole_words=False) -> str|None
    match_none() -> Q
"""

import re

from django.db.models import Q


def match_none():
    """A Q object that never matches a row.

    Django's empty ``Q()`` is a match-all identity, so callers that need
    "no results" (for example an unbalanced parenthesis) must use this.
    """
    return Q(pk__in=[])


def _paren_matches(text):
    """Map the index of each unescaped `(` to the index of its closing `)`.

    A backslash escapes the next character, so `\\(` and `\\)` are skipped.
    Unbalanced parentheses are left out of the map.
    """
    matches = {}
    stack = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == '\\':
            i += 2
            continue
        if char == '(':
            stack.append(i)
        elif char == ')' and stack:
            matches[stack.pop()] = i
        i += 1
    return matches


_QUANTIFIERS = ('?', '*', '+', '{')


def _bracket_end(text, open_index):
    """Index of the `]` that closes the `[` at open_index, or -1.

    A `]` right after `[` or `[^` is a member of the class, not the closer.
    `[:name:]`, `[=x=]`, and `[.x.]` inside the class do not close it.
    A backslash escapes the next character.
    """
    i = open_index + 1
    if i < len(text) and text[i] == '^':
        i += 1
    if i < len(text) and text[i] == ']':
        i += 1
    while i < len(text):
        if text[i] == '\\':
            i += 2
            continue
        if text[i] == '[' and i + 1 < len(text) and text[i + 1] in ':=.':
            closer = text[i + 1] + ']'
            end = text.find(closer, i + 2)
            if end == -1:
                return -1
            i = end + len(closer)
            continue
        if text[i] == ']':
            return i
        i += 1
    return -1


def _mask_regex_groups(text, quoted, groups):
    """Replace regex-only parentheses in text with placeholder keys.

    The expression parser treats `(...)` as a boolean group. These forms are
    regex syntax, so splitting on them leaves fragments that are not valid
    patterns. They are masked here and restored inside their term:

      - `(?...)` groups: lookaheads, lookbehinds, non-capturing groups,
        inline flags.
      - A `(...)` group immediately followed by a quantifier (`?`, `*`,
        `+`, `{`). A boolean group is never followed by one.
      - Escaped parentheses, `\\(` and `\\)`.
      - Parentheses inside a bracket expression, such as `[(]`. The whole
        expression is one literal class.

    Boolean groups such as `(Devils OR Rangers)` and plain groups such as
    `(Devils|Rangers)` are left for the parser.

    Masked text is stored in `groups` under the placeholder. A quoted phrase
    inside a masked span is restored exactly as typed, quotes included.
    """
    if '(' not in text and ')' not in text:
        return text

    def mask(raw):
        key = f'\x00R{len(groups)}\x00'
        groups[key] = raw
        return key

    matches = _paren_matches(text)
    parts = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == '\\':
            pair = text[i:i + 2]
            parts.append(mask(pair) if pair in ('\\(', '\\)') else pair)
            i += 2
            continue
        if char == '[':
            end = _bracket_end(text, i)
            span = text[i:end + 1] if end != -1 else ''
            if end != -1 and ('(' in span or ')' in span):
                for key, phrase in quoted.items():
                    span = span.replace(key, f'"{phrase}"')
                parts.append(mask(span))
                i = end + 1
                continue
        end = matches.get(i)
        if end is not None and (
            text.startswith('(?', i)
            or text[end + 1:end + 2] in _QUANTIFIERS
        ):
            group = text[i:end + 1]
            for key, phrase in quoted.items():
                group = group.replace(key, f'"{phrase}"')
            parts.append(mask(group))
            i = end + 1
        else:
            parts.append(char)
            i += 1
    return ''.join(parts)


def _expand_placeholders(token, phrases, regex_groups):
    """Restore quoted phrases and masked regex groups inside a term.

    Placeholders may be the whole token (`"foo"`) or sit next to other text
    (`"foo" bar`). Both forms must expand; leaving a NUL placeholder in the
    term makes PostgreSQL reject the query.
    """
    term = token
    for key, phrase in phrases.items():
        if key in term:
            term = term.replace(key, phrase)
    for key, group in regex_groups.items():
        if key in term:
            term = term.replace(key, group)
    return term


def build_q_object(field_name, term, use_regex=False, whole_words=False):
    """Build a single Q object for one search term.

    `whole_words` uses `\\y` on PostgreSQL and `\\b` everywhere else so the
    pattern actually anchors on a word boundary regardless of backend.
    """
    term = term.strip()
    if not term:
        return Q()

    if use_regex:
        return Q(**{f'{field_name}__iregex': term})
    if whole_words:
        from django.db import connection
        boundary = r'\y' if connection.vendor == 'postgresql' else r'\b'
        pattern = boundary + re.escape(term) + boundary
        return Q(**{f'{field_name}__iregex': pattern})
    return Q(**{f'{field_name}__icontains': term})


def parse_text_query(field_name, raw_value, use_regex=False, whole_words=False):
    """Parse a search expression into a Q object.

    Supports:
      - AND / OR (case-insensitive) between bare terms.
      - Double-quoted phrases (atomic; never split on operators). A quote
        may be the whole term or sit next to other text in the same term.
      - Parenthetical grouping with arbitrary nesting. An unclosed `(`
        matches nothing.
      - Regex mode (each term is a regex). Regex-only parentheses stay inside
        their term and reach the database         intact: `(?...)` groups, a group followed by a quantifier, escaped
        `\\(` / `\\)`, and parentheses inside a bracket expression such as
        `[(]`. Other parentheses are still boolean groups.
      - Whole-word mode (each bare term anchored with word boundaries).

    A bare value with no operators is matched as a single phrase via
    icontains (or regex / whole-word as configured).
    """
    phrases = {}
    regex_groups = {}

    def extract_quoted(text):
        def replacer(m):
            key = f'\x00P{len(phrases)}\x00'
            phrases[key] = m.group(1)
            return key
        return re.sub(r'"([^"]*)"', replacer, text)

    processed = extract_quoted(raw_value)
    if use_regex:
        processed = _mask_regex_groups(processed, phrases, regex_groups)

    def build_q(token):
        term = _expand_placeholders(token, phrases, regex_groups)
        return build_q_object(field_name, term, use_regex, whole_words)

    def parse_expression(expr):
        expr = expr.strip()

        if '(' in expr:
            paren_start = expr.rfind('(')
            paren_end = expr.find(')', paren_start)
            if paren_end == -1:
                return match_none()

            group_q = parse_expression(expr[paren_start + 1:paren_end])

            before_str = expr[:paren_start].rstrip()
            after_str = expr[paren_end + 1:].lstrip()

            before_op = '&'
            if before_str.upper().endswith(' AND'):
                before_str = before_str[:-4].rstrip()
            elif before_str.upper().endswith(' OR'):
                before_str = before_str[:-3].rstrip()
                before_op = '|'

            after_op = '&'
            after_upper = after_str.upper()
            if after_upper.startswith('AND '):
                after_str = after_str[4:].lstrip()
            elif after_upper.startswith('OR '):
                after_str = after_str[3:].lstrip()
                after_op = '|'

            result = group_q
            if before_str:
                before_q = parse_expression(before_str)
                result = (before_q | result) if before_op == '|' else (before_q & result)
            if after_str:
                after_q = parse_expression(after_str)
                result = (result | after_q) if after_op == '|' else (result & after_q)
            return result

        tokens = []
        operators = []
        remaining = expr

        while remaining:
            upper = remaining.upper()
            and_pos = upper.find(' AND ')
            or_pos = upper.find(' OR ')

            if and_pos == -1 and or_pos == -1:
                tokens.append(remaining.strip())
                break

            if and_pos == -1:
                pos, op, op_len = or_pos, '|', 4
            elif or_pos == -1:
                pos, op, op_len = and_pos, '&', 5
            elif and_pos < or_pos:
                pos, op, op_len = and_pos, '&', 5
            else:
                pos, op, op_len = or_pos, '|', 4

            token = remaining[:pos].strip()
            if token:
                tokens.append(token)
                operators.append(op)
            remaining = remaining[pos + op_len:]

        if not tokens:
            return Q()

        result = build_q(tokens[0])
        for i, op in enumerate(operators):
            next_q = build_q(tokens[i + 1])
            result = (result & next_q) if op == '&' else (result | next_q)
        return result

    return parse_expression(processed)


def _iregex_terms(query):
    """Regex strings from a parsed Q, in left-to-right order."""
    terms = []

    def walk(node):
        if isinstance(node, tuple):
            lookup, value = node
            if isinstance(lookup, str) and lookup.endswith('__iregex'):
                terms.append(value)
            return
        for child in getattr(node, 'children', ()):
            walk(child)

    walk(query)
    return terms


def validate_program_text_query(field_name, raw_value, use_regex=False, whole_words=False):
    """Return an error message if a regex term cannot compile, else None.

    PostgreSQL is asked to compile each regex against an empty string, inside
    a savepoint, so a bad pattern does not abort the caller's transaction and
    a valid pattern does not scan program rows. Contains terms are not regexes
    and are not checked.
    """
    terms = _iregex_terms(parse_text_query(
        field_name, raw_value, use_regex=use_regex, whole_words=whole_words
    ))
    if not terms:
        return None

    from django.db import DataError, connection, transaction

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                for term in terms:
                    cursor.execute("SELECT '' ~* %s", [term])
                    cursor.fetchone()
    except DataError as exc:
        return str(exc)
    return None
