"""Development OAuth connection service; not deployed or integrated with jobs."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from flask import Flask, abort, make_response, redirect, render_template_string, request

app = Flask(__name__)
BASE = os.environ.get('PUBLIC_BASE_URL', 'http://localhost:5000').rstrip('/')
REDIRECT = BASE + '/oauth/callback'


def database():
    db = sqlite3.connect(os.environ.get('ACCESS_DB', 'access.sqlite3'))
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE IF NOT EXISTS invitations(id TEXT PRIMARY KEY,email TEXT,expires INTEGER,status TEXT);
      CREATE TABLE IF NOT EXISTS states(id TEXT PRIMARY KEY,invite TEXT,browser TEXT,expires INTEGER);
      CREATE TABLE IF NOT EXISTS accounts(email TEXT PRIMARY KEY,token BLOB,approved_until TEXT);
    ''')
    return db


def google(url, data=None, token=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    with urlopen(Request(url, urlencode(data).encode() if data else None, headers), timeout=20) as response:
        return json.load(response)


def quarter_end():
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    month = ((now.month-1)//3+1)*3+1
    return datetime(now.year+(month > 12), 1 if month > 12 else month, 1,
                    tzinfo=ZoneInfo('Asia/Seoul')).astimezone(timezone.utc).isoformat()


def invite(email):
    identifier = secrets.token_urlsafe(32)
    with database() as db:
        db.execute('INSERT INTO invitations VALUES (?,?,?,?)',
                   (identifier, email.lower(), int(time.time())+7*86400, 'pending'))
    return BASE + '/invite?' + urlencode({'id': identifier})


def active_token(email):
    with database() as db:
        account = db.execute('SELECT * FROM accounts WHERE email=?', (email.lower(),)).fetchone()
    if not account or account['approved_until'] <= datetime.now(timezone.utc).isoformat():
        raise ValueError('Current quarterly consent required')
    refresh = Fernet(os.environ['TOKEN_ENCRYPTION_KEY']).decrypt(account['token']).decode()
    return google('https://oauth2.googleapis.com/token', {
        'client_id': os.environ['GOOGLE_CLIENT_ID'], 'client_secret': os.environ['GOOGLE_CLIENT_SECRET'],
        'refresh_token': refresh, 'grant_type': 'refresh_token'})['access_token']


@app.after_request
def privacy(response):
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                             'X-Content-Type-Options': 'nosniff'})
    return response


@app.get('/invite')
def consent():
    identifier = request.args.get('id', '')
    with database() as db:
        row = db.execute('SELECT * FROM invitations WHERE id=?', (identifier,)).fetchone()
    if not row or row['expires'] < time.time() or row['status'] != 'pending':
        abort(410)
    csrf = secrets.token_urlsafe(32)
    response = make_response(render_template_string('''<!doctype html><html lang="ko"><meta charset="utf-8">
      <h1>교육훈련이력카드 자동화 연결</h1><p>연결 계정: {{email}}</p>
      <p>유로인사이트 공유 캘린더와 제목이 같은 메일의 교육명·시간·장소·비고 및 참석/수료 정보를 이용합니다.
      작성 문서는 담당자에게 전달됩니다. 실제 수신자와 보존기간은 운영자가 연결 전 안내해야 합니다.</p>
      <p>Google의 권한은 메일함 전체 읽기입니다. 제목 일치 제한은 프로그램에서 적용해야 합니다.
      동의는 이번 분기까지이며, Google 계정의 타사 연결 관리에서 철회할 수 있습니다.</p>
      <form method="post" action="/decision"><input type="hidden" name="id" value="{{id}}">
      <input type="hidden" name="csrf" value="{{csrf}}">
      <button name="choice" value="approve">승인하고 Gmail 연결</button>
      <button name="choice" value="decline">미승인</button></form></html>''',
      email=row['email'], id=identifier, csrf=csrf))
    response.set_cookie('consent', csrf, secure=BASE.startswith('https:'), httponly=True, samesite='Lax')
    return response


@app.post('/decision')
def decision():
    if not request.cookies.get('consent') or not hmac.compare_digest(
            request.cookies['consent'], request.form.get('csrf', '')):
        abort(400)
    identifier = request.form.get('id', '')
    with database() as db:
        row = db.execute('SELECT * FROM invitations WHERE id=?', (identifier,)).fetchone()
        if not row or row['status'] != 'pending' or row['expires'] < time.time():
            abort(410)
        if request.form.get('choice') == 'decline':
            db.execute("UPDATE invitations SET status='declined' WHERE id=?", (identifier,))
            return '미승인으로 처리했습니다. 계정을 연결하지 않습니다.'
        if request.form.get('choice') != 'approve':
            abort(400)
        # Require configuration before redirecting to Google.
        client = os.environ['GOOGLE_CLIENT_ID']
        Fernet(os.environ['TOKEN_ENCRYPTION_KEY'])
        if not os.environ.get('GOOGLE_CLIENT_SECRET'):
            abort(503)
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute('INSERT INTO states VALUES (?,?,?,?)',
                   (state, identifier, hashlib.sha256(browser.encode()).hexdigest(), int(time.time())+600))
    response = redirect('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': client, 'redirect_uri': REDIRECT, 'response_type': 'code',
        'scope': 'openid email https://www.googleapis.com/auth/gmail.readonly',
        'access_type': 'offline', 'prompt': 'consent', 'state': state, 'login_hint': row['email']}))
    response.set_cookie('oauth_browser', browser, max_age=600, secure=BASE.startswith('https:'),
                        httponly=True, samesite='Lax')
    return response


@app.get('/oauth/callback')
def callback():
    state = request.args.get('state', '')
    with database() as db:
        row = db.execute('SELECT * FROM states WHERE id=?', (state,)).fetchone()
        browser = hashlib.sha256(request.cookies.get('oauth_browser', '').encode()).hexdigest()
        if not row or row['expires'] < time.time() or not hmac.compare_digest(row['browser'], browser):
            abort(400)
        db.execute('DELETE FROM states WHERE id=?', (state,))
        invitation = db.execute('SELECT * FROM invitations WHERE id=?', (row['invite'],)).fetchone()
    if not invitation or invitation['status'] != 'pending' or invitation['expires'] < time.time():
        abort(410)
    if request.args.get('error'):
        return 'Google 계정 연결을 취소했습니다.'
    result = google('https://oauth2.googleapis.com/token', {
        'client_id': os.environ['GOOGLE_CLIENT_ID'], 'client_secret': os.environ['GOOGLE_CLIENT_SECRET'],
        'redirect_uri': REDIRECT, 'grant_type': 'authorization_code', 'code': request.args['code']})
    try:
        profile = google('https://www.googleapis.com/oauth2/v2/userinfo', token=result['access_token'])
        if not profile.get('verified_email') or profile['email'].lower() != invitation['email']:
            raise ValueError('Wrong account')
        if 'https://www.googleapis.com/auth/gmail.readonly' not in result.get('scope', '').split():
            raise ValueError('Gmail permission missing')
        encrypted = Fernet(os.environ['TOKEN_ENCRYPTION_KEY']).encrypt(result['refresh_token'].encode())
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT status FROM invitations WHERE id=?', (row['invite'],)).fetchone()
            if current['status'] != 'pending':
                raise ValueError('Invitation already handled')
            db.execute('INSERT OR REPLACE INTO accounts VALUES (?,?,?)',
                       (invitation['email'], encrypted, quarter_end()))
            db.execute("UPDATE invitations SET status='approved' WHERE id=?", (row['invite'],))
    except Exception:
        try:
            google('https://oauth2.googleapis.com/revoke', {'token': result['access_token']})
        except Exception:
            pass
        raise
    return 'Gmail 연결 완료. 이번 분기까지 유효합니다.'


@app.errorhandler(Exception)
def error(exc):
    # No OAuth codes or tokens in response bodies.
    return '연결을 완료하지 못했습니다. 담당자에게 문의해 주세요.', getattr(exc, 'code', 400) or 400


if __name__ == '__main__':
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == 'invite':
        print(invite(sys.argv[2]))
    else:
        raise SystemExit('Use: python mail_access.py invite EMAIL; serve with a WSGI server')
