"""Fill the supplied private UIT-F601-03 template without inventing personnel data."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


def exact_subject(calendar_title, mail_subject):
    return bool(calendar_title) and calendar_title == mail_subject


def write_card(template, destination, employee, records):
    """records: confirmed category/date/title/time/location/remarks dictionaries.

    Does not infer completion from an invitation. Does not merge existing cards.
    Rejects overflows rather than silently discarding records.
    """
    if len(records) > 13:
        raise ValueError('Template supports at most 13 education rows')
    doc = Document(template)
    table = doc.tables[0]
    if len(table.rows) != 32 or '교육 / 훈련명' not in table.cell(12, 3).text:
        raise ValueError('Unexpected template layout')

    def put(row, col, text, size=8):
        cell = table.cell(row, col)
        paragraph = cell.paragraphs[0]
        for child in list(cell._tc):
            if child.tag == qn('w:p') and child is not paragraph._p:
                cell._tc.remove(child)
        for run in paragraph.runs:
            run.text = ''
        run = paragraph.add_run(str(text))
        run.font.size = Pt(size)
        run.font.name = '맑은 고딕'
        run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), '맑은 고딕')

    put(2, 2, employee)
    # Template's example role/date/approver must not become an employee fact.
    for col in (0, 3, 6, 9, 12):
        put(28, col, '')
    columns = ((0, 'category'), (1, 'date'), (3, 'title'), (6, 'time'),
               (9, 'location'), (13, 'remarks'))
    for row in range(13, 26):
        for col, key in columns:
            put(row, col, records[row-13].get(key, '확인 필요') if row-13 < len(records) else '')
    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    put(31, 3, f'생성일: {today} / 미확인 인사정보는 공란. 참석 및 수료는 증빙에 따라 구분.')
    folder = Path(destination) / employee
    if not employee or Path(employee).name != employee or employee in ('.', '..'):
        raise ValueError('Invalid employee folder name')
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'({today})UIT-F601-03_교육훈련이력카드.docx'
    if path.exists():
        raise FileExistsError('Existing card requires explicit review before replacement')
    doc.save(path)
    return path
