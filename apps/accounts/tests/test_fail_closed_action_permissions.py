"""Fail-closed custom-action permission helpers and source guardrails."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from django.test import SimpleTestCase
from rest_framework.permissions import AllowAny

from apps.accounts.permissions import (
    Authenticated,
    IsAdmin,
    IsStandardUser,
    permission_classes_by_action,
    permissions_for_action,
    permissions_for_method,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PERMISSIONS_MODULE = REPO_ROOT / "apps" / "accounts" / "permissions.py"
SOURCE_ROOTS = ("apps", "core", "dispatcharr")
PERMISSION_MAP_NAMES = frozenset(
    {"permission_classes_by_action", "permission_classes_by_method"}
)
HELPER_NAME = "permissions_for_action"


def _production_python_files():
    paths = []
    for root in SOURCE_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            parts = set(path.parts)
            if "tests" in parts or "migrations" in parts:
                continue
            if path.name.startswith("test_") or path == PERMISSIONS_MODULE:
                continue
            paths.append(path)
    return sorted(paths)


# Checkers are pure functions over source text so the self-tests below can
# prove they flag known-bad code.


def find_permission_map_references(source):
    """Line numbers where the raw permission maps are imported or used.

    Only ``apps/accounts/permissions.py`` may touch the maps. Everywhere else
    must go through ``permissions_for_action`` / ``permissions_for_method`` so
    unlisted actions fail closed in one place.
    """
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in PERMISSION_MAP_NAMES:
            hits.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr in PERMISSION_MAP_NAMES:
            hits.append(node.lineno)
        elif isinstance(node, ast.alias) and node.name in PERMISSION_MAP_NAMES:
            hits.append(getattr(node, "lineno", 0))
    return sorted(hits)


def find_get_permissions_exception_handlers(source):
    """Line numbers of try/except handlers inside any ``get_permissions``.

    An exception handler in ``get_permissions`` is how a fail-open fallback
    gets written (``except KeyError: return [Authenticated()]``), whatever
    class it returns.
    """
    hits = []
    for fn in ast.walk(ast.parse(source)):
        if isinstance(fn, ast.FunctionDef) and fn.name == "get_permissions":
            hits.extend(
                node.lineno
                for node in ast.walk(fn)
                if isinstance(node, ast.ExceptHandler)
            )
    return sorted(hits)


def find_action_permission_problems(*sources):
    """``(kind, "Class.action")`` problems for viewsets overriding get_permissions.

    Pass every source together. Actions inherited from a mixin (for example
    ``SchedulesDirectPosterMixin.poster``) are checked on the subclass that
    actually enforces ``get_permissions``.

    ``undeclared-action``: a custom ``@action`` that is not decorated with
    ``permission_classes``, not a shared CRUD action, and whose method name is
    not named in ``get_permissions``. It silently inherits the fallback. The
    method name is what DRF sets as ``view.action``; a matching ``url_path``
    does not count.

    ``inert-decorator``: an ``@action(permission_classes=...)`` on a viewset
    whose ``get_permissions`` never calls ``permissions_for_action``. DRF
    ignores the decorator there, so it only looks like a policy.

    Viewsets that do not override ``get_permissions`` are skipped: DRF applies
    the class-level policy (or the project default, admin) to every action and
    honors action decorators natively.
    """
    records = []
    for source in sources:
        for cls in (n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)):
            records.append(cls)

    by_name = {}
    for cls in records:
        by_name.setdefault(cls.name, []).append(cls)

    def inherited_classes(cls, seen):
        found = [cls]
        for base in cls.bases:
            if not isinstance(base, ast.Name) or base.id in seen:
                continue
            for parent in by_name.get(base.id, []):
                found.extend(inherited_classes(parent, seen | {base.id}))
        return found

    problems = []
    for cls in records:
        get_perms = _find_method(cls, "get_permissions")
        if get_perms is None:
            continue
        uses_helper = _calls_name(get_perms, HELPER_NAME)
        referenced = _string_literals_in(get_perms)
        for owner in inherited_classes(cls, {cls.name}):
            for method in (n for n in owner.body if isinstance(n, ast.FunctionDef)):
                call = _action_decorator(method)
                if call is None:
                    continue
                label = f"{cls.name}.{method.name}"
                decorated = _decorator_has_permission_classes(call)
                if decorated and not uses_helper:
                    problems.append(("inert-decorator", label))
                    continue
                if decorated or method.name in permission_classes_by_action:
                    continue
                if method.name in referenced:
                    continue
                problems.append(("undeclared-action", label))
    return problems


class PermissionsForActionHelperTests(SimpleTestCase):
    def test_honors_action_decorator_permission_classes(self):
        def search(self, request):
            return None

        search.kwargs = {"permission_classes": [IsStandardUser]}
        view = SimpleNamespace(action="search", search=search)

        perms = permissions_for_action(view)
        self.assertEqual(len(perms), 1)
        self.assertIsInstance(perms[0], IsStandardUser)

    def test_uses_shared_crud_map(self):
        view = SimpleNamespace(action="list")
        perms = permissions_for_action(view)
        self.assertEqual(len(perms), 1)
        self.assertIsInstance(perms[0], IsStandardUser)

        view = SimpleNamespace(action="destroy")
        perms = permissions_for_action(view)
        self.assertIsInstance(perms[0], IsAdmin)

    def test_unlisted_action_fails_closed_to_admin(self):
        view = SimpleNamespace(action="bulk_delete")
        perms = permissions_for_action(view)
        self.assertEqual(len(perms), 1)
        self.assertIsInstance(perms[0], IsAdmin)

    def test_unlisted_action_can_override_default(self):
        view = SimpleNamespace(action="mystery")
        perms = permissions_for_action(view, default=Authenticated)
        self.assertIsInstance(perms[0], Authenticated)

    def test_decorator_allow_any_beats_fail_closed_default(self):
        def cache(self, request, pk=None):
            return None

        cache.kwargs = {"permission_classes": [AllowAny]}
        view = SimpleNamespace(action="cache", cache=cache)
        perms = permissions_for_action(view)
        self.assertIsInstance(perms[0], AllowAny)


class PermissionsForMethodHelperTests(SimpleTestCase):
    def test_known_methods(self):
        self.assertIsInstance(
            permissions_for_method(SimpleNamespace(method="GET"))[0],
            IsStandardUser,
        )
        self.assertIsInstance(
            permissions_for_method(SimpleNamespace(method="POST"))[0],
            IsAdmin,
        )

    def test_unknown_method_fails_closed(self):
        perms = permissions_for_method(SimpleNamespace(method="TRACE"))
        self.assertIsInstance(perms[0], IsAdmin)

    def test_options_fails_closed(self):
        perms = permissions_for_method(SimpleNamespace(method="OPTIONS"))
        self.assertIsInstance(perms[0], IsAdmin)

    def test_head_is_authorized_like_get(self):
        get_perms = permissions_for_method(SimpleNamespace(method="GET"))
        head_perms = permissions_for_method(SimpleNamespace(method="HEAD"))
        self.assertEqual(
            [type(p) for p in head_perms], [type(p) for p in get_perms]
        )
        self.assertIsInstance(head_perms[0], IsStandardUser)


class FailOpenSourceGuardrailTests(TestCase):
    """The shipped source must satisfy the fail-closed rules."""

    def test_permission_maps_only_used_by_helpers(self):
        offenders = []
        for path in _production_python_files():
            text = path.read_text(encoding="utf-8")
            if not any(name in text for name in PERMISSION_MAP_NAMES):
                continue
            offenders.extend(
                f"{path.relative_to(REPO_ROOT)}:{line}"
                for line in find_permission_map_references(text)
            )
        self.assertEqual(
            offenders,
            [],
            "Use permissions_for_action / permissions_for_method instead of "
            "the raw permission maps:\n" + "\n".join(offenders),
        )

    def test_get_permissions_has_no_exception_fallbacks(self):
        offenders = []
        for path in _production_python_files():
            text = path.read_text(encoding="utf-8")
            if "def get_permissions" not in text:
                continue
            offenders.extend(
                f"{path.relative_to(REPO_ROOT)}:{line}"
                for line in find_get_permissions_exception_handlers(text)
            )
        self.assertEqual(
            offenders,
            [],
            "get_permissions must not catch exceptions to pick a fallback "
            "policy:\n" + "\n".join(offenders),
        )

    def test_custom_actions_are_explicitly_permissioned(self):
        sources = [
            path.read_text(encoding="utf-8") for path in _production_python_files()
        ]
        offenders = [
            label
            for kind, label in find_action_permission_problems(*sources)
            if kind == "undeclared-action"
        ]
        self.assertEqual(
            offenders,
            [],
            "Custom @actions need permission_classes on the decorator, or a "
            "named branch in get_permissions:\n" + "\n".join(offenders),
        )

    def test_action_decorators_are_not_inert(self):
        sources = [
            path.read_text(encoding="utf-8") for path in _production_python_files()
        ]
        offenders = [
            label
            for kind, label in find_action_permission_problems(*sources)
            if kind == "inert-decorator"
        ]
        self.assertEqual(
            offenders,
            [],
            "These @action(permission_classes=...) decorators are ignored "
            "because get_permissions does not call permissions_for_action. "
            "Route get_permissions through the helper or drop the "
            "decorator:\n" + "\n".join(offenders),
        )


class GuardrailCheckerSelfTests(SimpleTestCase):
    """The checkers must flag known-bad code, or the guardrail proves nothing."""

    def test_map_references_flagged_in_every_shape(self):
        bad_sources = {
            "subscript": "def f(self):\n    return permission_classes_by_action[self.action]\n",
            "get fallback": "def f(self):\n    return permission_classes_by_action.get(self.action, [Authenticated])\n",
            "membership": "def f(self):\n    return self.action in permission_classes_by_method\n",
            "import": "from apps.accounts.permissions import permission_classes_by_action\n",
            "attribute": "def f(self):\n    return perms.permission_classes_by_method['GET']\n",
        }
        for name, source in bad_sources.items():
            with self.subTest(name):
                self.assertTrue(find_permission_map_references(source))

    def test_map_references_absent_in_clean_code(self):
        source = (
            "from apps.accounts.permissions import permissions_for_action\n"
            "def get_permissions(self):\n    return permissions_for_action(self)\n"
        )
        self.assertEqual(find_permission_map_references(source), [])

    def test_exception_fallbacks_in_get_permissions_flagged(self):
        for fallback in ("[Authenticated()]", "[AllowAny()]", "[IsAuthenticated]"):
            for exc in ("KeyError", "Exception", "(KeyError, AttributeError)"):
                source = (
                    "def get_permissions(self):\n"
                    "    try:\n        return lookup(self.action)\n"
                    f"    except {exc}:\n        return {fallback}\n"
                )
                with self.subTest(fallback=fallback, exc=exc):
                    self.assertTrue(find_get_permissions_exception_handlers(source))

    def test_exception_handlers_outside_get_permissions_not_flagged(self):
        source = (
            "def helper(self):\n    try:\n        return 1\n    except KeyError:\n        return 2\n"
        )
        self.assertEqual(find_get_permissions_exception_handlers(source), [])

    def test_undeclared_action_flagged(self):
        source = (
            "class V:\n"
            "    def get_permissions(self):\n"
            "        return permissions_for_action(self)\n"
            "    @action(detail=False, methods=['post'])\n"
            "    def wipe(self, request):\n        pass\n"
        )
        self.assertEqual(
            find_action_permission_problems(source),
            [("undeclared-action", "V.wipe")],
        )

    def test_inert_decorator_flagged(self):
        source = (
            "class V:\n"
            "    def get_permissions(self):\n"
            "        return [IsAdmin()]\n"
            "    @action(detail=False, methods=['post'], permission_classes=[IsAdmin])\n"
            "    def wipe(self, request):\n        pass\n"
        )
        self.assertEqual(
            find_action_permission_problems(source),
            [("inert-decorator", "V.wipe")],
        )

    def test_declared_actions_pass(self):
        source = (
            "class V:\n"
            "    def get_permissions(self):\n"
            "        if self.action in ('named_branch',):\n"
            "            return [IsAdmin()]\n"
            "        return permissions_for_action(self)\n"
            "    @action(detail=False, permission_classes=[IsStandardUser])\n"
            "    def decorated(self, request):\n        pass\n"
            "    @action(detail=False)\n"
            "    def named_branch(self, request):\n        pass\n"
        )
        self.assertEqual(find_action_permission_problems(source), [])

    def test_url_path_does_not_count_as_a_declaration(self):
        # DRF sets view.action to the method name. Matching only the url_path
        # is how channels/by-uuids was left admin-only: the branch said
        # "by_uuids" while the method was get_by_uuids.
        source = (
            "class V:\n"
            "    def get_permissions(self):\n"
            "        if self.action == 'by_uuids':\n"
            "            return [IsStandardUser()]\n"
            "        return permissions_for_action(self)\n"
            "    @action(detail=False, url_path='by-uuids')\n"
            "    def get_by_uuids(self, request):\n        pass\n"
        )
        self.assertEqual(
            find_action_permission_problems(source),
            [("undeclared-action", "V.get_by_uuids")],
        )

    def test_mixin_action_is_checked_on_the_subclass(self):
        mixin = (
            "class PosterMixin:\n"
            "    @action(detail=True, methods=['get'])\n"
            "    def poster(self, request):\n        pass\n"
        )
        view = (
            "class ProgramViewSet(PosterMixin):\n"
            "    def get_permissions(self):\n"
            "        return permissions_for_action(self)\n"
        )
        self.assertEqual(
            find_action_permission_problems(mixin, view),
            [("undeclared-action", "ProgramViewSet.poster")],
        )

    def test_mixin_action_named_by_subclass_passes(self):
        mixin = (
            "class SourceMixin:\n"
            "    @action(detail=True, methods=['get', 'post'])\n"
            "    def sd_lineups(self, request):\n        pass\n"
        )
        view = (
            "class EPGSourceViewSet(SourceMixin):\n"
            "    def get_permissions(self):\n"
            "        if self.action == 'sd_lineups':\n"
            "            return [IsAdmin()]\n"
            "        return permissions_for_action(self)\n"
        )
        self.assertEqual(find_action_permission_problems(mixin, view), [])

    def test_viewsets_without_override_are_skipped(self):
        source = (
            "class V:\n"
            "    permission_classes = [IsAdmin]\n"
            "    @action(detail=False)\n"
            "    def wipe(self, request):\n        pass\n"
        )
        self.assertEqual(find_action_permission_problems(source), [])


def _find_method(class_node, name):
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _calls_name(node, name):
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == name
        for child in ast.walk(node)
    )


def _string_literals_in(node):
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def _action_decorator(method):
    for dec in method.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        if isinstance(func, ast.Name) and func.id == "action":
            return dec
        if isinstance(func, ast.Attribute) and func.attr == "action":
            return dec
    return None


def _decorator_has_permission_classes(call):
    return any(kw.arg == "permission_classes" for kw in call.keywords)
