"""Shared query parsing helpers for EPG program text search.

Used by the EPG search API and the DVR series rule evaluator to apply
the same boolean / quoted-phrase / regex / whole-word matching semantics.

Public API:
    parse_text_query(field, raw_value, use_regex=False, whole_words=False) -> Q
"""

import re

from django.db.models import Q


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
      - Double-quoted phrases (atomic; never split on operators).
      - Parenthetical grouping with arbitrary nesting.
      - Regex mode (entire raw value is treated as a single regex).
      - Whole-word mode (each bare term anchored with word boundaries).

    A bare value with no operators is matched as a single phrase via
    icontains (or regex / whole-word as configured).
    """
    phrases = {}

    def extract_quoted(text):
        def replacer(m):
            key = f'\x00P{len(phrases)}\x00'
            phrases[key] = m.group(1)
            return key
        return re.sub(r'"([^"]*)"', replacer, text)

    processed = extract_quoted(raw_value)

    def build_q(token):
        return build_q_object(field_name, phrases.get(token, token), use_regex, whole_words)

    def parse_expression(expr):
        expr = expr.strip()

        if '(' in expr:
            paren_start = expr.rfind('(')
            paren_end = expr.find(')', paren_start)
            if paren_end == -1:
                return Q()

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
