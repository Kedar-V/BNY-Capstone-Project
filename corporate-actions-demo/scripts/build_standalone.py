"""Packs the demo into one HTML file that opens with a double click: no server, no install, no network.

    python corporate-actions-demo/scripts/build_standalone.py
    python corporate-actions-demo/scripts/build_standalone.py --out "some folder/demo.html"

The file opens on the client's brief. Links to SEC.gov still need internet access.
"""
import argparse
import base64
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = DEMO / 'standalone' / 'client_briefing_demo.html'
OPEN_ON_BRIEF = "<script>if(!location.hash)location.replace('#/client/brief')</script>"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([shutil.which('node'), str(DEMO / 'node_modules' / 'vite' / 'bin' / 'vite.js'), 'build', '--outDir', tmp, '--emptyOutDir'],
                       cwd=DEMO, check=True)
        html = (Path(tmp) / 'index.html').read_text(encoding='utf-8')
        js_tag = re.search(r'<script type="module"[^>]*src="/(assets/[^"]+\.js)"[^>]*></script>', html)
        css_tag = re.search(r'<link rel="stylesheet"[^>]*href="/(assets/[^"]+\.css)"[^>]*>', html)
        js = (Path(tmp) / js_tag[1]).read_text(encoding='utf-8')
        css = (Path(tmp) / css_tag[1]).read_text(encoding='utf-8')

    html = html.replace(js_tag[0], '').replace(css_tag[0], '')
    # A web font must not hold up the page on a slow or blocked network; the page falls back to the system font
    html = re.sub(r'<link[^>]*fonts\.(?:googleapis|gstatic)[^>]*>\s*', '', html)
    # A closing tag inside the bundled text would end the inline block early
    js = js.replace('</script', '<\\/script')
    css = css.replace('</style', '<\\/style')
    html = html.replace('</head>', f'{OPEN_ON_BRIEF}<style>{css}</style></head>')
    html = html.replace('</body>', f'<script type="module">{js}</script></body>')

    logo = base64.b64encode((DEMO / 'public' / 'bny-logo.svg').read_bytes()).decode()
    html = html.replace('/bny-logo.svg', f'data:image/svg+xml;base64,{logo}')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding='utf-8')
    print(f'Wrote {args.out} ({args.out.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()
