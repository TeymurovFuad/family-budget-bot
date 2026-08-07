"""
test_web_macros.py — shared Jinja macros for the web UI v2 redesign
(web/templates/_macros.html): amount, pagination, chip. Pure template
render tests, no app/routes involved.
"""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).resolve().parents[1] / "web" / "templates"


@pytest.fixture(scope="module")
def env():
    return Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True)


def render(env, source, **ctx):
    return env.from_string(
        '{% from "_macros.html" import amount, pagination, chip %}' + source
    ).render(**ctx)


# ── amount ────────────────────────────────────────────────────────────────────

def test_amount_kinds(env):
    assert render(env, "{{ amount(12.5, 'pos') }}") == \
        '<span class="amount amount--pos">+12.50</span>'
    assert render(env, "{{ amount(-12.5, 'neg') }}") == \
        '<span class="amount amount--neg">-12.50</span>'
    assert render(env, "{{ amount(7, 'save') }}") == \
        '<span class="amount amount--save">7.00</span>'
    assert render(env, "{{ amount(7) }}") == \
        '<span class="amount amount--neutral">7.00</span>'


# ── pagination ────────────────────────────────────────────────────────────────

def test_pagination_middle_page(env):
    html = render(env, "{{ pagination(2, 3, '/transactions?year=2024', '#txn-list', 50) }}")
    assert 'href="/transactions?year=2024&amp;offset=0"' in html
    assert 'href="/transactions?year=2024&amp;offset=100"' in html
    assert 'hx-get="/transactions?year=2024&amp;offset=0"' in html
    assert 'hx-target="#txn-list"' in html
    assert 'hx-push-url="true"' in html
    assert "Page 2 of 3" in html
    assert 'class="pagination"' in html


def test_pagination_first_page_disables_prev(env):
    html = render(env, "{{ pagination(1, 3, '/transactions') }}")
    assert '<span class="page-link disabled" aria-disabled="true">&laquo; Prev</span>' in html
    assert 'href="/transactions?offset=50"' in html  # default per_page, no '?' in base


def test_pagination_last_page_disables_next(env):
    html = render(env, "{{ pagination(3, 3, '/x?a=1') }}")
    assert 'Next &raquo;</span>' in html
    assert html.count("<a ") == 1  # only prev is a link


# ── chip ──────────────────────────────────────────────────────────────────────

def test_chip_plain(env):
    assert render(env, "{{ chip('Groceries') }}") == \
        '<span class="chip">Groceries</span>'


def test_chip_filter_with_clear_link(env):
    html = render(env, "{{ chip('person: Alice', '/transactions?year=2024') }}")
    assert 'class="chip chip--filter"' in html
    assert '<a class="chip-clear" href="/transactions?year=2024"' in html
    assert "&times;" in html


def test_chip_escapes_user_text(env):
    html = render(env, "{{ chip(t) }}", t='<script>alert(1)</script>')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
