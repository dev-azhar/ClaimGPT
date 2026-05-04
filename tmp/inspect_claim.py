from sqlalchemy import create_engine, text
from libs.shared.config import settings

claim_id = '7af7a36a-8d4b-4540-b70d-cefe8d9d185f'
engine = create_engine(settings.database_url)

with engine.begin() as conn:
    docs = conn.execute(text('''
        select d.id, d.file_name, d.file_type, d.uploaded_at
        from documents d
        where d.claim_id = :cid
        order by d.uploaded_at
    '''), {'cid': claim_id}).fetchall()
    doc_ids = [str(d.id) for d in docs]
    print('Documents:', len(docs))
    for d in docs:
        print('-', d.id, d.file_name, d.file_type)

    if doc_ids:
        ocr = conn.execute(text('''
            select o.document_id, count(*) as pages, sum(length(coalesce(o.text,''))) as chars,
                   min(o.confidence) as min_conf, max(o.confidence) as max_conf
            from ocr_results o
            where o.document_id in (
                select d.id from documents d where d.claim_id = :cid
            )
            group by o.document_id
            order by pages desc
        '''), {'cid': claim_id}).fetchall()
        print('\nOCR groups:', len(ocr))
        for r in ocr:
            print('-', r.document_id, 'pages=', r.pages, 'chars=', r.chars, 'conf=', r.min_conf, '->', r.max_conf)

        snippets = conn.execute(text('''
            select o.document_id, o.page_number, left(replace(replace(coalesce(o.text,''), chr(10), ' '), chr(13), ' '), 240) as snippet
            from ocr_results o
            where o.document_id in (
                select d.id from documents d where d.claim_id = :cid
            )
            order by o.document_id, o.page_number
            limit 40
        '''), {'cid': claim_id}).fetchall()
        print('\nOCR snippets:')
        for s in snippets:
            print('-', s.document_id, 'p', s.page_number, ':', s.snippet)

    pf = conn.execute(text('''
        select field_name, field_value, model_version, source_page, document_id, doc_type, created_at
        from parsed_fields
        where claim_id = :cid
        order by created_at asc, field_name asc
    '''), {'cid': claim_id}).fetchall()
    print('\nParsed fields:', len(pf))
    for row in pf:
        print('-', row.field_name, '|', row.field_value, '|', row.model_version, '| page', row.source_page, '| doc', row.document_id, '|', row.doc_type)

    jobs = conn.execute(text('''
        select 'ocr' as kind, id, status, created_at, completed_at, error_message
        from ocr_jobs where claim_id=:cid
        union all
        select 'parse' as kind, id, status, created_at, completed_at, error_message
        from parse_jobs where claim_id=:cid
        order by created_at desc
        limit 20
    '''), {'cid': claim_id}).fetchall()
    print('\nJobs:')
    for j in jobs:
        print('-', j.kind, j.id, j.status, j.created_at, j.completed_at, j.error_message)
