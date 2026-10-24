#!/usr/bin/env python3
"""Auditor independiente y de solo lectura de un catálogo ArcanaCart y su lote ZIP.

No necesita ROM, AIR, red ni código del repositorio. Usa Pillow para decodificar PNG.
Todos los SHA-256 se calculan sobre los bytes originales, sin normalizar texto.
"""
from __future__ import annotations
import argparse
import base64
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile
from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--catalogo', type=Path, required=True)
    ap.add_argument('--original', type=Path, required=True)
    ap.add_argument('--salida', type=Path, required=True)
    args = ap.parse_args()
    report = {'format': 'independent-arcanacart-catalog-audit-1',
              'hash_policy': 'SHA-256 sobre bytes exactos; ninguna normalización LF/CRLF',
              'checks': {}, 'errors': [], 'archives': {}, 'variants': []}
    checks = Counter()

    def check(group, condition, detail):
        checks[group] += 1
        if not condition:
            report['errors'].append({'group': group, 'detail': detail})

    def archive(path, label):
        z = zipfile.ZipFile(path)
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        check('zip_paths', len(names) == len(set(names)), label + ': nombres repetidos')
        check('zip_paths', len(names) == len({n.casefold() for n in names}), label + ': colisiones Windows')
        digests = {}
        for n in names:
            pp = PurePosixPath(n)
            check('zip_paths', not pp.is_absolute() and '..' not in pp.parts and '\\' not in n and ':' not in n,
                  label + ': ruta ' + n)
            with z.open(n) as f:
                h = hashlib.sha256()
                while chunk := f.read(1024 * 1024):
                    h.update(chunk)
                digests[n] = h.hexdigest()
            checks['zip_crc_read'] += 1  # ZipFile verifies each CRC when the member is fully read.
        report['archives'][label] = {'name': path.name, 'sha256': sha(path.read_bytes()),
                                   'zip_bytes': path.stat().st_size, 'files': len(names),
                                   'uncompressed_bytes': sum(i.file_size for i in z.infolist()),
                                   'crc_all_members': True}
        return z, digests

    cat, ch = archive(args.catalogo, 'catalogo')
    src, sh = archive(args.original, 'lote_original')
    read_json = lambda z, n: json.loads(z.read(n))
    catalog = read_json(cat, 'catalogo.json')
    summary = read_json(cat, 'resumen.json')
    state = read_json(cat, 'catalog-state.json')
    plan = read_json(src, 'planes-usados.json')
    source_summary = read_json(src, 'resumen.json')
    source_state = read_json(src, 'run-state.json')

    check('catalog_manifest', state['status'] == 'completed', 'estado catálogo')
    check('catalog_manifest', set(state['artifacts']) == set(ch) - {'catalog-state.json'}, 'cobertura manifest')
    for n, h in state['artifacts'].items():
        check('catalog_manifest', ch.get(n) == h, n)
    check('summaries', catalog['summary'] == summary, 'resumen embebido frente a resumen.json')
    for n, h in summary['source_root_hashes'].items():
        check('source_roots', sh.get(n) == h, n)
    check('source_roots', summary['source_plan_sha256'] == sh['planes-usados.json'], 'plan exacto')
    check('source_roots', source_summary['plan_sha256'] == sh['planes-usados.json'], 'plan del resumen')
    check('source_roots', source_state['plan_sha256'] == sh['planes-usados.json'], 'plan del checkpoint')

    jobs = {j['id']: j for j in plan['jobs']}
    check('variants', len(jobs) == 43 and Counter(j['game'] for j in jobs.values()) == {'fe7': 8, 'fe8': 35}, '8 FE7 + 35 FE8')
    expected = {}
    validations = {}
    source_manifest_count = 0
    consolidation_input_count = len(summary['source_root_hashes'])
    local_raw_resources = 0
    source_origin_counts = Counter()
    source_summary_by_id = {v['Carpeta']: v for v in source_summary['variants']}
    for vid, job in sorted(jobs.items()):
        root = vid + '/galeria/'
        result = read_json(src, vid + '/resultado.json')
        validation = read_json(src, vid + '/validacion.json')
        faces = read_json(src, root + 'catalog.json')
        fs = read_json(src, root + 'faces-state.json')
        check('source_status', source_state['jobs'][vid]['status'] == result['status'] == 'completed', vid + ': lote/rango')
        expected_gallery_status = 'partial' if job['expected_empty_ids'] else 'completed'
        check('source_status', fs['status'] == faces['summary']['status'] == expected_gallery_status,
              vid + ': estado galería genérica según vacíos previstos')
        check('source_status', faces['summary']['entries_without_observed_graphics'] == job['expected_empty_ids']
              and faces['summary']['pending_component_total'] == 0 and faces['summary']['errors'] == 0,
              vid + ': sin componentes pendientes ni errores')
        check('source_manifest', source_state['jobs'][vid]['report_sha256'] == sh[vid + '/resultado.json'], vid + ': resultado')
        check('source_manifest', result['validation_sha256'] == sh[vid + '/validacion.json'], vid + ': validacion')
        check('source_manifest', result['faces_state_sha256'] == sh[root + 'faces-state.json'], vid + ': faces-state')
        check('source_manifest', set(fs['artifacts']) == {n[len(root):] for n in sh if n.startswith(root)} - {'faces-state.json'}, vid + ': cobertura manifest')
        for n, h in fs['artifacts'].items():
            check('source_manifest', sh.get(root + n) == h, root + n)
            source_manifest_count += 1
            if not n.startswith('raw-resources/') and not (n.startswith('paletas/') and n.endswith('.png')):
                consolidation_input_count += 1
        for k in ['air_sha256', 'rom_sha256', 'layout_sha256']:
            check('variant_hash_metadata', result[k] == job[k], vid + ': ' + k)
        check('variant_hash_metadata', result['plan_sha256'] == sh['planes-usados.json'], vid + ': plan')
        check('variant_hash_metadata', validation['rom_sha256'] == job['rom_sha256'], vid + ': validacion ROM')
        check('variant_hash_metadata', faces['summary']['rom_sha256'] == job['rom_sha256'] and faces['summary']['source_manifest_sha256'] == job['air_sha256'], vid + ': catalog ROM/AIR')
        check('ranges', job['first_id'] == 1 and job['last_id'] == (228 if job['game'] == 'fe7' else 254), vid + ': rango')
        entries = {e['face_id']: e for e in validation['entries']}
        check('ranges', len(entries) == len(validation['entries']) and set(entries) == set(range(job['first_id'], job['last_id'] + 1)), vid + ': validacion IDs')
        empty_ids = sorted(e['face_id'] for e in entries.values() if not e['components'])
        check('empty_ids', empty_ids == job['expected_empty_ids'] == result['expected_empty_ids'], vid)
        check('source_validation', validation['range_components_validated'] and validation['rom_hash_matches_air'] and not validation['errors'] and not result['problems'], vid)
        validations[vid] = entries
        counts = Counter()
        for r in faces['resources']:
            check('source_resources', r['status'] == 'generated', vid + ': estado recurso')
            key = (vid, r['face_id'], r['kind'])
            check('source_resources', key not in expected, str(key) + ': duplicado')
            expected[key] = r
            counts[r['kind']] += 1
            source_origin_counts[r['data_origin']] += 1
            check('source_resources', root + r['png'] in sh, str(key) + ': PNG')
            check('source_resources', sh.get(root + 'paletas/' + r['palette_sha256'] + '.bin') == r['palette_sha256'], str(key) + ': paleta')
            if r.get('raw_blob'):
                check('source_raw_blobs', sh.get(root + r['raw_blob']) == r['source_sha256'], str(key))
                local_raw_resources += 1
        check('source_counts', dict(counts) == job['expected_counts'] == result['actual_counts'] == result['expected_counts'] == source_state['jobs'][vid]['counts'], vid)
        row = source_summary_by_id[vid]
        check('source_counts', [counts['portrait'], counts['miniature'], counts['classcard']] == [row['Retratos'], row['Miniaturas'], row['Tarjetas']], vid + ': resumen fila')
        report['variants'].append({'variant_id': vid, 'game': job['game'], 'variant': job['variant'],
                                   'first_id': job['first_id'], 'last_id': job['last_id'], 'empty_ids': empty_ids,
                                   'counts': dict(counts), 'pngs': sum(counts.values()),
                                   'rom_sha256': job['rom_sha256'], 'air_sha256': job['air_sha256'],
                                   'batch_status': result['status'], 'gallery_status': fs['status']})

    palettes = {}
    for n in ch:
        if n.startswith('paletas/'):
            b = cat.read(n)
            h = PurePosixPath(n).stem
            check('palettes', len(b) == 32 and len(h) == 64 and sha(b) == h, n)
            palettes[h] = b
    check('catalog_files', {n for n in ch if n.startswith('imagenes/')} == {a['file'] for a in catalog['images']}, 'imágenes referenciadas = imágenes incluidas')
    images = {}
    actual = {}
    palette_refs = set()
    invisible = []
    counts = Counter()
    by_game = defaultdict(Counter)
    by_dimensions = Counter()
    visible_occurrences = 0
    pixel_equivalence = defaultdict(list)
    for a in catalog['images']:
        h = a['png_sha256']
        check('image_keys', h not in images and a['file'] == 'imagenes/' + h + '.png', h)
        images[h] = a
        check('png_hash', ch.get(a['file']) == h, a['file'])
        b = cat.read(a['file'])
        with Image.open(io.BytesIO(b)) as im:
            check('png_decode', im.format == 'PNG' and im.mode == 'RGBA' and im.size == (a['width'], a['height']), h)
            im.verify()
        with Image.open(io.BytesIO(b)) as im:
            rgba = im.convert('RGBA')
            rgba.load()
            visible = rgba.getchannel('A').getbbox() is not None
            pixels = rgba.tobytes()
            colors = {(pixels[i], pixels[i+1], pixels[i+2]) for i in range(0, len(pixels), 4) if pixels[i+3]}
            alpha = set(pixels[3::4])
            check('png_alpha', alpha <= {0, 255}, h)
            check('png_visibility', visible == a['visible'], h)
            pixel_equivalence[(im.size, sha(rgba.tobytes()))].append(h)
        by_dimensions[f"{a['width']}x{a['height']}"] += 1
        if not visible:
            invisible.append({'png_sha256': h, 'width': a['width'], 'height': a['height'], 'occurrences': len(a['origins'])})
        else:
            visible_occurrences += len(a['origins'])
        check('image_aggregates', sorted({o['kind'] for o in a['origins']}) == a['kinds'] and sorted({o['game'] for o in a['origins']}) == a['games'] and bool(a['origins']), h)
        for o in a['origins']:
            vid = o['variant_id']
            key = (vid, o['face_id'], o['kind'])
            check('occurrence_keys', key not in actual and key in expected, str(key))
            actual[key] = (h, o)
            counts[o['kind']] += 1
            by_game[o['game']][o['kind']] += 1
            if key not in expected or vid not in jobs:
                continue
            j = jobs[vid]
            r = expected[key]
            check('occurrence_metadata', o['game'] == j['game'] and o['variant'] == j['variant'] and o['rom_sha256'] == j['rom_sha256'] and o['air_sha256'] == j['air_sha256'], str(key) + ': variante/hash')
            for k in ['face_id_hex', 'source_offset', 'source_sha256', 'palette_sha256', 'data_origin']:
                check('occurrence_metadata', o[k] == r[k], str(key) + ': ' + k)
            check('occurrence_metadata', o['face_id_hex'] == f"0x{o['face_id']:03X}" and j['first_id'] <= o['face_id'] <= j['last_id'] and o['face_id'] not in j['expected_empty_ids'], str(key) + ': ID')
            source_png = vid + '/galeria/' + r['png']
            check('png_original', o['source_png'] == source_png and sh.get(source_png) == h and src.read(source_png) == b, str(key))
            if o['kind'] == 'classcard':
                # Class cards are 10 tiles wide; their height comes from the
                # actual 4bpp byte count. FE8 ID 0x0AF has 3200 bytes (80x80).
                expected_dimensions = (80, ((r['size_bytes'] + 319) // 320) * 8)
            else:
                expected_dimensions = {'portrait': (96, 80), 'miniature': (32, 32)}[o['kind']]
            check('png_dimensions_kind', (a['width'], a['height']) == (r['width'], r['height']) == expected_dimensions, str(key))
            ph = o['palette_sha256']
            palette_refs.add(ph)
            check('palette_original', palettes.get(ph) == src.read(vid + '/galeria/paletas/' + ph + '.bin'), str(key))
            entry = validations[vid][o['face_id']]
            comps = [c for c in entry['components'] if c['kind'] == o['kind']]
            check('validation_provenance', len(comps) == 1 and comps[0]['source_offset'] == o['source_offset'] and comps[0]['source_sha256'] == o['source_sha256'] and entry['palette_sha256'] == ph, str(key))
            pb = palettes[ph]
            check('palette_validation_hex', pb.hex() == entry['palette_hex'], str(key))
            # Accept the common RGB555 expansion conventions. The observed
            # convention is recorded independently below, without changing data.
            words = struct.unpack('<16H', pb)
            conventions = {
                'scale_floor_255': lambda v: v * 255 // 31,
                'bit_replication': lambda v: (v << 3) | (v >> 2),
                'shift_only': lambda v: v << 3,
                'scale_round_255': lambda v: round(v * 255 / 31),
            }
            matching = []
            for name, expand in conventions.items():
                allowed = {(expand(w & 31), expand((w >> 5) & 31), expand((w >> 10) & 31)) for w in words[1:]}
                if colors <= allowed:
                    matching.append(name)
            check('palette_png_colors', bool(matching), str(key))

    check('occurrence_coverage', set(actual) == set(expected), 'cada recurso original tiene exactamente una aparición')
    check('palette_coverage', set(palettes) == palette_refs, 'paletas utilizadas = paletas incluidas')
    for k, v in {'variants': len(jobs), 'component_occurrences': len(actual), 'component_counts': dict(counts),
                 'unique_images': len(images), 'visible_images': len(images) - len(invisible),
                 'transparent_images': len(invisible), 'transparent_occurrences': len(actual) - visible_occurrences,
                 'duplicate_png_copies_avoided': len(actual) - len(images), 'unique_palettes': len(palettes)}.items():
        check('summary_recomputed', summary.get(k) == v, k)
    check('source_summary_totals', source_summary['generated_counts'] == dict(counts) == plan['expected_total_counts'] and source_summary['generated_component_pngs'] == len(actual) == plan['expected_total_pngs'], 'conteos lote/plan')
    check('source_summary_totals', source_summary['found_variants'] == source_summary['completed_variants'] == 43 and source_summary['pending_variants'] == 0 and source_state['run_status'] == source_summary['run_status'] == 'completed', 'estado lote completo')
    check('source_verified_input_count', summary['verified_input_files'] == consolidation_input_count,
          'archivos del manifest utilizados por consolidación más metadatos raíz')

    def csv_rows(n):
        text = cat.read(n).decode('utf-8-sig')
        return list(csv.DictReader(io.StringIO(text, newline=''), strict=True))
    rows = csv_rows('imagenes.csv')
    check('csv_images', len(rows) == len(images) and len({r['png_sha256'] for r in rows}) == len(rows), 'filas y claves')
    for row in rows:
        a = images.get(row['png_sha256'])
        if a is None:
            check('csv_images', False, row['png_sha256'])
            continue
        expected_row = {k: str(a[k]) for k in ['png_sha256', 'file', 'visible', 'width', 'height']}
        expected_row.update(kinds=';'.join(a['kinds']), games=';'.join(a['games']), occurrences=str(len(a['origins'])))
        check('csv_images', row == expected_row, a['png_sha256'])
    rows = csv_rows('ocurrencias.csv')
    check('csv_occurrences', len(rows) == len(actual), 'filas')
    seen = set()
    for row in rows:
        key = (row['variant_id'], int(row['face_id']), row['kind'])
        check('csv_occurrences', key not in seen and key in actual, str(key))
        seen.add(key)
        if key in actual:
            h, o = actual[key]
            a = images[h]
            expected_row = {k: str(v) for k, v in o.items()}
            expected_row.update(png_sha256=h, file=a['file'], visible=str(a['visible']))
            check('csv_occurrences', row == expected_row, str(key))
    check('csv_occurrences', seen == set(actual), 'cobertura')

    html = cat.read('index.html').decode('utf-8')
    embed = re.search(r'<script type="application/json" id="catalog-data">(.*?)</script>', html, re.S)
    check('html_embedded_catalog', embed is not None and json.loads(embed[1]) == {'images': catalog['images']}, 'datos HTML = catálogo JSON')
    script = re.findall(r'<script>(.*?)</script>', html, re.S)
    check('html_script_hash', len(script) == 1 and base64.b64encode(hashlib.sha256(script[0].encode()).digest()).decode() in html[:1500], 'script autorizado por CSP')
    links = re.findall(r'href="([^"#]+)"', html[:html.index('<script')])
    for link in links:
        check('html_static_links', link in ch, link)

    report['checks'] = dict(checks)
    report['status'] = 'passed' if not report['errors'] else 'failed'
    report['counts'] = {'variants': len(jobs), 'unique_pngs': len(images), 'visible_pngs': len(images) - len(invisible),
                        'transparent_pngs': len(invisible), 'occurrences': len(actual), 'components': dict(counts),
                        'per_game': {g: dict(c) for g, c in by_game.items()}, 'unique_palettes': len(palettes),
                        'duplicate_png_copies_avoided': len(actual) - len(images), 'dimensions': dict(by_dimensions),
                        'transparent_occurrences': len(actual) - visible_occurrences,
                        'source_manifest_artifacts': source_manifest_count,
                        'consolidation_verified_input_files': consolidation_input_count,
                        'local_raw_occurrences_rehashed': local_raw_resources, 'data_origins': dict(source_origin_counts)}
    report['transparent_images'] = invisible
    report['same_decoded_rgba_different_png'] = [v for v in pixel_equivalence.values() if len(v) > 1]
    report['limitations'] = [
        'No se proporcionaron ROM ni AIR completos: sus hashes se cotejaron entre metadatos, no se recalcularon desde esos archivos.',
        'Los hashes de bloques AIR comprimidos/descomprimidos no incluidos en el lote no pueden recalcularse desde este ZIP.',
        'La concordancia de PNG con el lote y sus paletas no demuestra que cada retrato reproduzca fielmente la pantalla del juego.',
        'El alcance se limita a los IDs del plan y no certifica extracción total de recursos.',
        'La presentación en un navegador real se documenta por separado; esta auditoría sólo comprueba datos y enlaces HTML.'
    ]
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': sum(checks.values()), 'errors': len(report['errors']),
                      'counts': report['counts'], 'error_examples': report['errors'][:12], 'report': str(args.salida)}, ensure_ascii=False))
    cat.close()
    src.close()
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
