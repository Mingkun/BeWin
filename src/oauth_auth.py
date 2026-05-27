import inspect
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import requests
from flask import Response, redirect, request, session, url_for


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / 'data' / 'releaseplan.db'
DEFAULT_OAUTH_DEBUG_LOG_PATH = BASE_DIR / 'logs' / 'oauth_callback_debug.log'
_OAUTH_CODE_TTL_SECONDS = 600


def get_oauth_debug_log_path():
    configured = (os.getenv('RELEASEPLAN_OAUTH_DEBUG_LOG_PATH') or '').strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_OAUTH_DEBUG_LOG_PATH


def _mask_sensitive_value(key, value):
    key_text = str(key or '').strip().lower()
    if value is None:
        return value
    if key_text in {'client_secret', 'access_token', 'authorization', 'id_token', 'refresh_token', 'token'}:
        value_text = str(value)
        if len(value_text) <= 8:
            return '***'
        return f"{value_text[:4]}***{value_text[-4:]}"
    return value


def _sanitize_payload(payload):
    if isinstance(payload, dict):
        return {key: _sanitize_payload(_mask_sensitive_value(key, value)) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return [_sanitize_payload(item) for item in payload]
    return payload


def _log_oauth_debug(event, **payload):
    caller = inspect.currentframe().f_back
    source = {}
    try:
        if caller is not None:
            source = {
                'source_file': Path(caller.f_code.co_filename).name,
                'source_line': caller.f_lineno,
                'source_func': caller.f_code.co_name,
            }
    finally:
        del caller

    record = {
        'time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'event': event,
        **source,
        **_sanitize_payload(payload),
    }
    text = json.dumps(record, ensure_ascii=False) + '\n'
    primary_path = get_oauth_debug_log_path()
    try:
        primary_path.parent.mkdir(parents=True, exist_ok=True)
        with primary_path.open('a', encoding='utf-8') as fh:
            fh.write(text)
    except Exception:
        fallback_path = Path('/tmp/releaseplan_oauth_callback_debug.log')
        try:
            with fallback_path.open('a', encoding='utf-8') as fh:
                fh.write(text)
        except Exception:
            pass

    if (os.getenv('RELEASEPLAN_OAUTH_DEBUG_STDOUT') or 'true').strip().lower() == 'true':
        try:
            print(f'[releaseplan-oauth-debug] {text.rstrip()}', flush=True)
        except Exception:
            pass


def _cleanup_oauth_code_cache(conn):
    cutoff = (datetime.utcnow() - timedelta(seconds=_OAUTH_CODE_TTL_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute('DELETE FROM oauth_code_consumption WHERE created_at < ?', (cutoff,))


def _mark_oauth_code_used(code):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS oauth_code_consumption (
                code TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            '''
        )
        _cleanup_oauth_code_cache(conn)
        conn.execute(
            'INSERT INTO oauth_code_consumption (code, created_at) VALUES (?, ?)',
            (code, datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _release_oauth_code(code):
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute('DELETE FROM oauth_code_consumption WHERE code = ?', (code,))
        conn.commit()
    finally:
        conn.close()


def oauth_authorize_url():
    return os.getenv('RELEASEPLAN_OAUTH_AUTHORIZE_URL', '').strip()


def oauth_token_url():
    return os.getenv('RELEASEPLAN_OAUTH_TOKEN_URL', '').strip()


def oauth_userinfo_url():
    return os.getenv('RELEASEPLAN_OAUTH_USERINFO_URL', '').strip()


def oauth_client_id():
    return os.getenv('RELEASEPLAN_OAUTH_CLIENT_ID', '').strip()


def oauth_client_secret():
    return os.getenv('RELEASEPLAN_OAUTH_CLIENT_SECRET', '').strip()


def oauth_scope():
    return os.getenv('RELEASEPLAN_OAUTH_SCOPE', 'openid profile email').strip()


def oauth_userinfo_token_mode():
    return (os.getenv('RELEASEPLAN_OAUTH_USERINFO_TOKEN_MODE') or 'auto').strip().lower()


def oauth_redirect_uri():
    configured = os.getenv('RELEASEPLAN_OAUTH_REDIRECT_URI', '').strip()
    if configured:
        return configured
    prefix = (request.headers.get('X-Forwarded-Prefix') or '').strip()
    callback_path = '/auth/callback'
    if prefix:
        callback_path = f"{prefix.rstrip('/')}/auth/callback"
    return url_for('oauth_callback', _external=True, _scheme=request.headers.get('X-Forwarded-Proto', request.scheme)).replace('/auth/callback', callback_path, 1)


def build_oauth_user(userinfo, *, match_permission_rule, default_feature_flags, normalize_feature_flags):
    roles = userinfo.get('roles') or userinfo.get('role') or []
    if isinstance(roles, str):
        roles = [roles]
    normalized_roles = [str(role).strip().lower() for role in roles if str(role).strip()]
    email = (userinfo.get('email') or '').strip().lower()
    username = (userinfo.get('preferred_username') or userinfo.get('login') or userinfo.get('name') or '').strip().lower()
    employee_number = str(userinfo.get('employeeNumber') or userinfo.get('employee_number') or '').strip().lower()

    matched_rule = match_permission_rule(source='sso', username=username, email=email, employee_number=employee_number)
    if matched_rule:
        matched_role = str(matched_rule.get('role') or 'user').strip().lower()
        final_roles = ['admin'] if matched_role == 'admin' else ['user']
    else:
        admin_roles = {
            role.strip().lower()
            for role in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_ROLES', 'admin,administrator,releaseplan-admin').split(','))
            if role.strip()
        }
        user_roles = {
            role.strip().lower()
            for role in (os.getenv('RELEASEPLAN_OAUTH_USER_ROLES') or os.getenv('RELEASEPLAN_OAUTH_GUEST_ROLES') or 'user,guest,viewer,readonly,releaseplan-user,releaseplan-guest').split(',')
            if role.strip()
        }
        admin_emails = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_EMAILS', '').split(','))
            if item.strip()
        }
        user_emails = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_USER_EMAILS') or os.getenv('RELEASEPLAN_OAUTH_GUEST_EMAILS') or '').split(',')
            if item.strip()
        }
        admin_usernames = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_USERNAMES', '').split(','))
            if item.strip()
        }
        user_usernames = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_USER_USERNAMES') or os.getenv('RELEASEPLAN_OAUTH_GUEST_USERNAMES') or '').split(',')
            if item.strip()
        }

        if set(normalized_roles) & admin_roles or (email and email in admin_emails) or (username and username in admin_usernames):
            final_roles = ['admin']
        elif set(normalized_roles) & user_roles or (email and email in user_emails) or (username and username in user_usernames):
            final_roles = ['user']
        else:
            default_role = (os.getenv('RELEASEPLAN_OAUTH_DEFAULT_ROLE') or 'user').strip().lower()
            final_roles = ['admin'] if default_role == 'admin' else ['user']

    features = default_feature_flags(final_roles[0] if final_roles else 'user')
    if matched_rule:
        features = matched_rule.get('features') or features

    return {
        'user_id': userinfo.get('sub') or userinfo.get('id') or userinfo.get('user_id') or '',
        'name': userinfo.get('name') or userinfo.get('preferred_username') or userinfo.get('login') or '',
        'email': userinfo.get('email') or '',
        'username': userinfo.get('preferred_username') or userinfo.get('login') or userinfo.get('name') or '',
        'employee_number': userinfo.get('employeeNumber') or userinfo.get('employee_number') or '',
        'roles': final_roles,
        'features': normalize_feature_flags(features, final_roles[0] if final_roles else 'user'),
        'raw': userinfo,
        'auth_type': 'oauth2',
    }


def extract_access_token(token_resp):
    content_type = (token_resp.headers.get('Content-Type') or '').lower()
    body_text = token_resp.text or ''

    if 'application/json' in content_type:
        try:
            token_data = token_resp.json()
        except ValueError:
            token_data = {}
    else:
        token_data = {}
        try:
            token_data = token_resp.json()
        except ValueError:
            parsed = parse_qs(body_text, keep_blank_values=True)
            token_data = {key: values[0] if values else '' for key, values in parsed.items()}

    access_token = (
        token_data.get('access_token')
        or token_data.get('accessToken')
        or token_data.get('token')
        or token_data.get('id_token')
    )
    return access_token, token_data, body_text


def register_oauth_routes(app, *, oauth_enabled, normalize_next_url, match_permission_rule, default_feature_flags, normalize_feature_flags):
    @app.route('/auth/login')
    def oauth_login():
        if not oauth_enabled():
            return redirect(url_for('index'))
        state = secrets.token_urlsafe(24)
        next_url = normalize_next_url(request.args.get('next') or '/')
        session['oauth_state'] = state
        session['oauth_next'] = next_url
        query = {
            'client_id': oauth_client_id(),
            'redirect_uri': oauth_redirect_uri(),
            'response_type': 'code',
            'scope': oauth_scope(),
            'state': state,
        }
        _log_oauth_debug(
            'authorize_redirect',
            authorize_url=oauth_authorize_url(),
            query=query,
        )
        return redirect(oauth_authorize_url() + ('&' if '?' in oauth_authorize_url() else '?') + urlencode(query))

    @app.route('/auth/callback')
    def oauth_callback():
        if not oauth_enabled():
            return redirect(url_for('index'))
        code = request.args.get('code', '').strip()
        state = request.args.get('state', '').strip()
        _log_oauth_debug(
            'callback_received',
            path=request.path,
            full_path=request.full_path,
            host=request.host,
            url=request.url,
            forwarded_prefix=request.headers.get('X-Forwarded-Prefix', ''),
            forwarded_proto=request.headers.get('X-Forwarded-Proto', ''),
            has_code=bool(code),
            code_preview=code[:12],
            state=state,
            session_oauth_state=session.get('oauth_state'),
            has_oauth_user=bool(session.get('oauth_user')),
            session_oauth_next=session.get('oauth_next'),
            remote_addr=request.headers.get('X-Forwarded-For', request.remote_addr),
        )
        if not code:
            _log_oauth_debug('callback_missing_code')
            return Response('OAuth2 登录失败: 缺少 code', status=400)
        if not state or state != session.get('oauth_state'):
            _log_oauth_debug('callback_state_mismatch', state=state, session_oauth_state=session.get('oauth_state'))
            return Response('OAuth2 登录失败: state 校验失败', status=400)
        if not _mark_oauth_code_used(code):
            existing_user = session.get('oauth_user')
            next_url = normalize_next_url(session.get('oauth_next') or '/')
            _log_oauth_debug('callback_duplicate_code', code_preview=code[:12], has_oauth_user=bool(existing_user), next_url=next_url)
            if existing_user:
                session.pop('oauth_state', None)
                session.pop('oauth_next', None)
                return redirect(next_url)
            return redirect(next_url)

        try:
            token_request_data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': oauth_redirect_uri(),
                'client_id': oauth_client_id(),
                'client_secret': oauth_client_secret(),
            }
            token_request_headers = {
                'Accept': 'application/json, application/x-www-form-urlencoded;q=0.9, text/plain;q=0.8',
            }
            _log_oauth_debug(
                'token_request',
                token_url=oauth_token_url(),
                data=token_request_data,
                headers=token_request_headers,
            )
            token_resp = requests.post(
                oauth_token_url(),
                data=token_request_data,
                headers=token_request_headers,
                timeout=15,
            )
            if token_resp.status_code >= 400:
                detail = token_resp.text.strip()
                if len(detail) > 300:
                    detail = detail[:300] + '...'
                return Response(f'OAuth2 登录失败: token 交换失败，响应为 {detail or token_resp.status_code}', status=400)
            access_token, token_data, body_text = extract_access_token(token_resp)
            if not access_token:
                detail = ''
                try:
                    detail = json.dumps(token_data, ensure_ascii=False)
                except Exception:
                    detail = body_text.strip()
                if len(detail) > 300:
                    detail = detail[:300] + '...'
                return Response(f'OAuth2 登录失败: 缺少 access_token，响应为 {detail or token_resp.text[:300]}', status=400)

            userinfo_modes = []
            configured_mode = oauth_userinfo_token_mode()
            if configured_mode and configured_mode != 'auto':
                userinfo_modes.append(configured_mode)
            userinfo_modes.extend([mode for mode in ['json_access_token', 'bearer', 'query_access_token', 'query_token'] if mode not in userinfo_modes])

            userinfo = None
            last_userinfo_resp = None
            for mode in userinfo_modes:
                headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
                params = {}
                json_data = None
                if mode == 'json_access_token':
                    json_data = {
                            "client_id": oauth_client_id(),
                            "access_token": access_token,
                            "scope": oauth_scope()
                    }
                elif mode == 'bearer':
                    headers['Authorization'] = f'Bearer {access_token}'
                    json_data = {}
                elif mode == 'query_access_token':
                    params['access_token'] = access_token
                elif mode == 'query_token':
                    params['token'] = access_token
                else:
                    continue

                _log_oauth_debug(
                    'userinfo_request',
                    userinfo_url=oauth_userinfo_url(),
                    mode=mode,
                    headers=headers,
                    params=params,
                    json_data=json_data,
                )
                if mode in {'json_access_token', 'bearer'}:
                    userinfo_resp = requests.post(
                        oauth_userinfo_url(),
                        headers=headers,
                        json=json_data,
                        timeout=15,
                    )
                else:
                    userinfo_resp = requests.get(
                        oauth_userinfo_url(),
                        headers=headers,
                        params=params,
                        timeout=15,
                    )
                last_userinfo_resp = userinfo_resp
                response_preview = (userinfo_resp.text or '').strip()
                if len(response_preview) > 300:
                    response_preview = response_preview[:300] + '...'
                _log_oauth_debug(
                    'userinfo_attempt',
                    mode=mode,
                    status_code=userinfo_resp.status_code,
                    response_preview=response_preview,
                )

                if userinfo_resp.status_code >= 400:
                    continue
                try:
                    candidate = userinfo_resp.json()
                except ValueError:
                    continue
                if isinstance(candidate, dict) and (candidate.get('errorCode') or candidate.get('error') or candidate.get('code')):
                    continue
                userinfo = candidate
                break

            if userinfo is None:
                detail = ''
                if last_userinfo_resp is not None:
                    detail = (last_userinfo_resp.text or '').strip()
                if len(detail) > 300:
                    detail = detail[:300] + '...'
                return Response(f'OAuth2 登录失败: 获取用户信息失败，响应为 {detail or "未知错误"}', status=400)
            session.pop('oauth_state', None)
            session['oauth_user'] = build_oauth_user(
                userinfo,
                match_permission_rule=match_permission_rule,
                default_feature_flags=default_feature_flags,
                normalize_feature_flags=normalize_feature_flags,
            )
            try:
                from src.app import record_login_audit
                record_login_audit(session['oauth_user'])
            except Exception:
                pass
            next_url = normalize_next_url(session.pop('oauth_next', None) or '/')
            return redirect(next_url)
        except Exception:
            _release_oauth_code(code)
            raise

    @app.route('/auth/logout')
    def oauth_logout():
        session.pop('oauth_user', None)
        session.pop('local_user', None)
        session.pop('oauth_state', None)
        session.pop('oauth_next', None)
        logout_url = os.getenv('RELEASEPLAN_OAUTH_LOGOUT_URL', '').strip()
        if logout_url and oauth_enabled():
            return redirect(logout_url)
        return redirect(url_for('index'))
