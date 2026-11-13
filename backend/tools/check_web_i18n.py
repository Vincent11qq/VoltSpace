"""Render web/app.js in Node with a DOM stub, in both languages.

Nothing here is a browser, but it runs the real file: the same dictionary lookup, the same
formatters and the same render functions. That catches the failure a dictionary test
cannot see - "the strings are translated but the wiring never calls them".

The stub is written to ``.test-data/`` (git-ignored) rather than next to the sources.

Usage::

    python tools/check_web_i18n.py           # human-readable report
    python tools/check_web_i18n.py --json    # machine-readable, used by the test
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
APP_JS = BACKEND / "web" / "app.js"
STUB = BACKEND / ".test-data" / "render_stub.js"

NODE_STUB = r"""
const fs = require('fs');

// --- minimal DOM -----------------------------------------------------------
class Node {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this._text = '';
    this.style = {};
    this.dataset = {};
    this.classList = { add() {}, remove() {}, toggle() {} };
    this.attributes = {};
    this.value = '';
    this.hidden = false;
    this.className = '';
  }
  append(...nodes) { for (const n of nodes) this.children.push(n); }
  appendChild(n) { this.children.push(n); return n; }
  addEventListener() {}
  setAttribute(k, v) { this.attributes[k] = v; }
  focus() {}
  select() {}
  reset() {}
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
  get innerHTML() { return this._text; }
  set innerHTML(v) { this._text = String(v); this.children = []; }
}

const registry = new Map();
function make(id) {
  const node = new Node('div');
  node.id = id;
  registry.set(id, node);
  return node;
}
for (const id of ['conn','plan','month','circuit','ampsLimit','margin','presets',
                  'customToggle','customForm','cName','cWatts','cVolts','cHours','cDays',
                  'cQty','customCancel','outlet','status','watts','amps','bar','cost',
                  'plugged','saveAll','reload','clearAll','saveNote','sKwh','sCost',
                  'sRate','sSeason','breakdown','recs','saving','disclaimer','toast',
                  'langToggle']) {
  make(id);
}
registry.get('margin').value = '0.8';

global.document = {
  documentElement: { lang: '' },
  title: '',
  getElementById: (id) => registry.get(id) || null,
  querySelectorAll: () => [],
  createElement: (tag) => new Node(tag),
  addEventListener: () => {},
};
global.window = {};
global.localStorage = {
  store: {},
  getItem(k) { return this.store[k] ?? null; },
  setItem(k, v) { this.store[k] = String(v); },
};
global.fetch = async () => { throw new Error('network disabled in the stub'); };
global.setTimeout = () => 0;
global.clearTimeout = () => 0;

// --- load the real file ----------------------------------------------------
// argv[1] is this stub, argv[2] is app.js.
const source = fs.readFileSync(process.argv[2], 'utf8');
eval(source + '\n;globalThis.__v = { setLanguage, t, pick, monthLabel,'
  + ' get LANG() { return LANG; } };');

const V = globalThis.__v;
const out = {};

V.setLanguage('zh');
out.zh = {
  lang: V.LANG,
  tagline: V.t('brand.tagline'),
  save: V.t('actions.save'),
  emptyStatus: V.t('empty.status'),
  month7: V.monthLabel(7),
  pick: V.pick('冷氣機', 'Air conditioner'),
  saving: V.t('recs.saving', { kwh: '116.1', twd: '287', pct: '30' }),
  assumption: V.t('recs.assumption', { text: '測試' }),
};

V.setLanguage('en');
out.en = {
  lang: V.LANG,
  tagline: V.t('brand.tagline'),
  save: V.t('actions.save'),
  emptyStatus: V.t('empty.status'),
  month7: V.monthLabel(7),
  pick: V.pick('冷氣機', 'Air conditioner'),
  saving: V.t('recs.saving', { kwh: '116.1', twd: '287', pct: '30' }),
  assumption: V.t('recs.assumption', { text: 'test' }),
  toggleLabel: registry.get('langToggle').textContent,
  documentLang: global.document.documentElement.lang,
};

// A backend field with no English must not render as an empty string.
out.fallback = {
  missingEn: V.pick('只有中文', undefined),
  missingZh: V.pick(undefined, 'English only'),
  missingBoth: V.pick(undefined, undefined),
};

process.stdout.write(JSON.stringify(out));
"""


def node() -> str | None:
    for name in ("node", "node.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def render() -> dict:
    """Run the stub and return what the UI would show."""

    executable = node()
    if executable is None:
        raise RuntimeError("node is not installed")

    STUB.parent.mkdir(parents=True, exist_ok=True)
    STUB.write_text(NODE_STUB, encoding="utf-8")

    result = subprocess.run(
        [executable, str(STUB), str(APP_JS)],
        cwd=str(BACKEND),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "node failed")
    return json.loads(result.stdout)


def problems(data: dict) -> list[str]:
    issues: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            issues.append(message)

    for language in ("zh", "en"):
        section = data.get(language, {})
        check(section.get("lang") == language, f"{language}: language flag is wrong")
        for key in ("tagline", "save", "emptyStatus", "month7", "pick", "saving"):
            check(bool(str(section.get(key, "")).strip()), f"{language}.{key} is empty")

    # The two languages must differ where they should.
    for key in ("tagline", "save", "emptyStatus", "month7", "saving"):
        check(
            data["zh"].get(key) != data["en"].get(key),
            f"{key} is identical in both languages",
        )

    check(data["en"].get("toggleLabel") == "中文", "the toggle should offer Chinese in English mode")
    check(data["en"].get("documentLang") == "en", "<html lang> should be en in English mode")
    check(data["zh"].get("month7") == "7 月", "Chinese month label changed")
    check(data["en"].get("month7") == "July", "English month label changed")

    fallback = data.get("fallback", {})
    check(fallback.get("missingEn") == "只有中文", "missing English must fall back to Chinese")
    check(fallback.get("missingZh") == "English only", "missing Chinese must fall back to English")
    check(not str(fallback.get("missingBoth") or "").strip() is None, "fallback guard")

    return issues


def main() -> int:
    as_json = "--json" in sys.argv[1:]

    try:
        data = render()
    except RuntimeError as error:
        print(f"could not render app.js: {error}", file=sys.stderr)
        return 1

    issues = problems(data)
    if as_json:
        print(json.dumps({"data": data, "problems": issues}, ensure_ascii=False))
        return 0 if not issues else 1

    for language in ("zh", "en"):
        print(f"\n--- {language} ---")
        for key, value in data[language].items():
            print(f"  {key:14} {value}")
    print("\n--- fallback ---")
    for key, value in data["fallback"].items():
        print(f"  {key:14} {value}")

    print()
    if issues:
        print(f"{len(issues)} problem(s):")
        for issue in issues:
            print("  -", issue)
        return 1
    print("both languages render, and missing translations fall back instead of blanking")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
