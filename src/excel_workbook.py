import csv
import re
import zipfile
from html import escape
from io import BytesIO, StringIO
from xml.etree import ElementTree as ET


XML_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RELS_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_RELS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'


def _column_name(index):
    name = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _safe_sheet_name(name):
    value = re.sub(r'[\[\]\:\*\?\/\\]', '', str(name or '').strip())[:31]
    return value or 'Sheet'


def _sheet_xml(rows):
    row_parts = []
    for row_index, row in enumerate(rows, start=1):
        cell_parts = []
        for column_index, value in enumerate(row, start=1):
            text = '' if value is None else str(value)
            cell_ref = f'{_column_name(column_index)}{row_index}'
            cell_parts.append(
                f'<c r="{cell_ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'
            )
        row_parts.append(f'<row r="{row_index}">{"".join(cell_parts)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{XML_NS}"><sheetData>{"".join(row_parts)}</sheetData></worksheet>'
    )


def build_xlsx_workbook(sheets):
    sheet_items = [
        (_safe_sheet_name(name), rows or [[]])
        for name, rows in sheets
    ]
    if not sheet_items:
        sheet_items = [('Sheet1', [[]])]

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    workbook_sheets = []
    workbook_rels = []

    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            '_rels/.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PACKAGE_RELS_NS}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            'docProps/core.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>BeWin</dc:creator></cp:coreProperties>',
        )
        archive.writestr(
            'docProps/app.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>BeWin</Application></Properties>',
        )

        for index, (sheet_name, rows) in enumerate(sheet_items, start=1):
            sheet_path = f'xl/worksheets/sheet{index}.xml'
            archive.writestr(sheet_path, _sheet_xml(rows))
            content_types.append(
                f'<Override PartName="/{sheet_path}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            workbook_sheets.append(
                f'<sheet name="{escape(sheet_name)}" sheetId="{index}" r:id="rId{index}"/>'
            )
            workbook_rels.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )

        content_types.append('</Types>')
        archive.writestr('[Content_Types].xml', ''.join(content_types))
        archive.writestr(
            'xl/workbook.xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{XML_NS}" xmlns:r="{RELS_NS}"><sheets>{"".join(workbook_sheets)}</sheets></workbook>',
        )
        archive.writestr(
            'xl/_rels/workbook.xml.rels',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{PACKAGE_RELS_NS}">{"".join(workbook_rels)}</Relationships>',
        )

    return output.getvalue()


def _cell_text(cell, shared_strings):
    cell_type = cell.attrib.get('t')
    if cell_type == 's':
        value = cell.find(f'{{{XML_NS}}}v')
        try:
            return shared_strings[int(value.text or '0')] if value is not None else ''
        except (ValueError, IndexError):
            return ''
    if cell_type == 'inlineStr':
        text_node = cell.find(f'{{{XML_NS}}}is/{{{XML_NS}}}t')
        return text_node.text if text_node is not None and text_node.text is not None else ''
    value = cell.find(f'{{{XML_NS}}}v')
    return value.text if value is not None and value.text is not None else ''


def _column_index(cell_ref):
    letters = ''.join(ch for ch in str(cell_ref or '') if ch.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + ord(char) - 64
    return max(index, 1)


def _read_shared_strings(archive):
    if 'xl/sharedStrings.xml' not in archive.namelist():
        return []
    root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
    values = []
    for item in root.findall(f'{{{XML_NS}}}si'):
        parts = [node.text or '' for node in item.findall(f'.//{{{XML_NS}}}t')]
        values.append(''.join(parts))
    return values


def read_xlsx_sheets(raw):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        shared_strings = _read_shared_strings(archive)
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        rels_root = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        rel_targets = {
            rel.attrib.get('Id'): rel.attrib.get('Target')
            for rel in rels_root.findall(f'{{{PACKAGE_RELS_NS}}}Relationship')
        }
        result = {}
        for sheet in workbook.findall(f'{{{XML_NS}}}sheets/{{{XML_NS}}}sheet'):
            name = sheet.attrib.get('name') or ''
            rel_id = sheet.attrib.get(f'{{{RELS_NS}}}id')
            target = rel_targets.get(rel_id)
            if not target:
                continue
            if target.startswith('/'):
                sheet_path = target.lstrip('/')
            elif target.startswith('xl/'):
                sheet_path = target
            else:
                sheet_path = f'xl/{target}'
            root = ET.fromstring(archive.read(sheet_path))
            rows = []
            for row in root.findall(f'.//{{{XML_NS}}}row'):
                values = []
                for cell in row.findall(f'{{{XML_NS}}}c'):
                    column_index = _column_index(cell.attrib.get('r'))
                    while len(values) < column_index - 1:
                        values.append('')
                    values.append(_cell_text(cell, shared_strings))
                rows.append(values)
            result[name] = rows
        return result


def rows_to_csv_content(rows):
    normalized_rows = [list(row or []) for row in rows or []]
    while normalized_rows and not any(str(cell or '').strip() for cell in normalized_rows[0]):
        normalized_rows.pop(0)
    if not normalized_rows:
        return ''
    width = max(len(row) for row in normalized_rows)
    output = StringIO()
    writer = csv.writer(output)
    for row in normalized_rows:
        padded = row + [''] * (width - len(row))
        writer.writerow(padded)
    return output.getvalue()
