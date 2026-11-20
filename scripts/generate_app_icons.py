#!/usr/bin/env python3
"""Regenerate PETIT app icons from the approved pear-and-Saturn illustration."""
from __future__ import annotations
from base64 import b64encode
import hashlib
from io import BytesIO
from pathlib import Path
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'frontend' / 'branding' / 'petit-app-icon-source.png'
FRONTEND = ROOT / 'frontend'
IOS = ROOT / 'ios' / 'PETITMobile' / 'PETITMobile' / 'Assets.xcassets' / 'AppIcon.appiconset'
DARK = (34, 36, 51)

def save_png(image: Image.Image, path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((size, size), Image.Resampling.LANCZOS).convert('RGB').save(path, format='PNG', optimize=True)

def run() -> None:
    # Restore the exact transfer tail and verify against the original Git blob SHA.
    # The initial transfer lost one base64 character near the tail; the
    # first 5600 encoded characters were transferred intact.
    from base64 import b64encode, b64decode
    expected = 'e361a8144bf651dd352935747f24f35a53ee0e66'
    raw = SOURCE.read_bytes()
    prefix = b'blob 4462\\x00'
    if hashlib.sha1(prefix + raw).hexdigest() != expected:
        tail = (
            'joLD9yZP7eXGH0RAwkPSEzZ7CG9qdn46l/uEKchLwJ+4X4h7SmLNN5CUUf++BnjW'
            'e85LAbDFuFHd04sl1G+0CRxPTX76JEg+J/BuNXmDRCH1E1lA2v4kH82S7VpkjNDY'
            '+fOc8DX6sGjLKngxhhf9CLTME8J3je5G5Xw678UY+EChmUskcsEn+Fty7Wdfy0B/'
            'FDcaxxnojXZ72Klwtwq1gkWdaHX0zBMm0KyndWVtv/eoGSy8MO0j+47RNloXSvbj'
            'CrIPQNCmyLKU9ooe1TOPhN5o/c35sIVcR1Cwp0K8Xvzpdlvtldks+naLYF9YuR93'
            '8X+EU3RySY+SggAAAABJRU5ErkJggg=='
        )
        restored = b64decode(b64encode(raw).decode('ascii')[:5600] + tail)
        if hashlib.sha1(prefix + restored).hexdigest() != expected:
            encoded = b64encode(raw).decode('ascii')
            for i in range(0, 5600, 800):
                print('ICON CHUNK', i // 800, hashlib.sha256(encoded[i:i+800].encode()).hexdigest())
            print('restored length', len(restored), 'sha', hashlib.sha1(prefix + restored).hexdigest())
            raise ValueError('icon source transfer checksum mismatch')
        SOURCE.write_bytes(restored)
    src = Image.open(SOURCE).convert('RGB')
    if src.width != src.height:
        raise ValueError('icon source must be square')
    for size in (192, 512):
        save_png(src, FRONTEND / f'icon-{size}.png', size)
    save_png(src, FRONTEND / 'favicon-64.png', 64)
    save_png(src, FRONTEND / 'apple-touch-icon.png', 180)
    save_png(src, FRONTEND / 'branding' / 'icon_logo.png', 256)
    for size in (192, 512):
        canvas = Image.new('RGB', (size, size), DARK)
        inner = round(size * .76)
        artwork = src.resize((inner, inner), Image.Resampling.LANCZOS)
        canvas.paste(artwork, ((size - inner) // 2, (size - inner) // 2))
        canvas.save(FRONTEND / f'icon-maskable-{size}.png', optimize=True)
    b = BytesIO()
    src.save(b, 'PNG', optimize=True)
    data_uri = 'data:image/png;base64,' + b64encode(b.getvalue()).decode('ascii')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" '
           'role="img" aria-label="PETIT pear mascot">'
           f'<image width="512" height="512" href="{data_uri}"/>'
           '</svg>\n')
    for name in ('icon.svg', 'icon-desktop.svg'):
        (FRONTEND / name).write_text(svg, encoding='utf-8')
    IOS.mkdir(parents=True, exist_ok=True)
    save_png(src, IOS / 'AppIcon.png', 1024)
    (IOS / 'Contents.json').write_text(json.dumps({'images': [
        {'filename': 'AppIcon.png', 'idiom': 'universal', 'platform': 'ios', 'size': '1024x1024'}
    ], 'info': {'author': 'xcode', 'version': 1}}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    src.resize((256, 256), Image.Resampling.LANCZOS).save(
        FRONTEND / 'petit-app.ico', format='ICO',
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    manifest_file = FRONTEND / 'manifest.webmanifest'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    manifest['background_color'] = '#222433'
    for icon in manifest['icons']:
        icon['src'] = icon['src'].split('?', 1)[0] + '?v=petit-pear-1'
    for shortcut in manifest.get('shortcuts', []):
        for icon in shortcut.get('icons', []):
            icon['src'] = icon['src'].split('?', 1)[0] + '?v=petit-pear-1'
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    project = ROOT / 'ios' / 'PETITMobile' / 'project.yml'
    yml = project.read_text(encoding='utf-8')
    needle = '        PRODUCT_BUNDLE_IDENTIFIER: com.soso.PETITMobile\n'
    if 'ASSETCATALOG_COMPILER_APPICON_NAME' not in yml:
        assert needle in yml
        yml = yml.replace(needle, needle + '        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon\n', 1)
        project.write_text(yml, encoding='utf-8')
    for html in FRONTEND.glob('*.html'):
        text = html.read_text(encoding='utf-8')
        for name in ('favicon-64.png', 'apple-touch-icon.png', 'branding/icon_logo.png'):
            text = text.replace(f'/static/{name}"', f'/static/{name}?v=petit-pear-1"')
        html.write_text(text, encoding='utf-8')
    desktop = ROOT / 'desktop' / 'package.json'
    package = json.loads(desktop.read_text(encoding='utf-8'))
    package['build'].setdefault('win', {})['icon'] = '../frontend/petit-app.ico'
    desktop.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Generated PETIT icons for Web/PWA/Desktop/iOS.')

if __name__ == '__main__':
    run()
