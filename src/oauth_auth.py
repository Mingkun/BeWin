import json
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode

import requests
from flask import Response, redirect, request, session, url_for


_OAUTH_CODE_LOCK = threading.Lock()
_OAUTH_CODE_CACHE = {}
_OAUTH_CODE_TTL_SECONDS = 120


def _cleanup_oauth_code_cache(now=None):
    now = now or time.time()
    expired = [code for code, ts in _OAUTH_CODE_CACHE.items() if now - ts > _OAUTH_CODE_TTL_SECONDS]
    for code in expired:
        _OAUTH_CODE_CACHE.pop(code, None)


def _mark_oauth_code_used(code):
    now = time.time()
    with _OAUTH_CODE_LOCK:
        _cleanup_oauth_code_cache(now)
        if code in _OAUTH_CODE_CACHE:
            return False
        _OAUTH_CODE_CACHE[code] = now
        return True


def _release_oauth_code(code):
    with _OAUTH_CODE_LOCK:
        _OAUTH_CODE_CACHE.pop(code, None)


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

    matched_rule = match_permission_rule(username=username, email=email)
    if matched_rule:
        final_roles = [matched_rule]
    else:
        admin_roles = {
            role.strip().lower()
            for role in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_ROLES', 'admin,administrator,releaseplan-admin').split(','))
            if role.strip()
        }
        guest_roles = {
            role.strip().lower()
            for role in (os.getenv('RELEASEPLAN_OAUTH_GUEST_ROLES', 'guest,viewer,readonly,releaseplan-guest').split(','))
            if role.strip()
        }
        admin_emails = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_EMAILS', '').split(','))
            if item.strip()
        }
        guest_emails = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_GUEST_EMAILS', '').split(','))
            if item.strip()
        }
        admin_usernames = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_USERNAMES', '').split(','))
            if item.strip()
        }
        guest_usernames = {
            item.strip().lower()
            for item in (os.getenv('RELEASEPLAN_OAUTH_GUEST_USERNAMES', '').split(','))
            if item.strip()
        }

        if set(normalized_roles) & admin_roles or (email and email in admin_emails) or (username and username in admin_usernames):
            final_roles = ['admin']
        elif set(normalized_roles) & guest_roles or (email and email in guest_emails) or (username and username in guest_usernames):
            final_roles = ['guest']
        else:
            default_role = (os.getenv('RELEASEPLAN_OAUTH_DEFAULT_ROLE') or 'guest').strip().lower()
            final_roles = ['admin'] if default_role == 'admin' else ['guest']

    features = default_feature_flags(final_roles[0] if final_roles else 'guest')
    if matched_rule:
        features = matched_rule.get('features') or features

    return {
        'user_id': userinfo.get('sub') or userinfo.get('id') or userinfo.get('user_id') or '',
        'name': userinfo.get('name') or userinfo.get('preferred_username') or userinfo.get('login') or '',
        'email': userinfo.get('email') or '',
        'roles': final_roles,
        'features': normalize_feature_flags(features, final_roles[0] if final_roles else 'guest'),
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
        return redirect(oauth_authorize_url() + ('&' if '?' in oauth_authorize_url() else '?') + urlencode(query))

    @app.route('/auth/callback')
    def oauth_callback():
        if not oauth_enabled():
            return redirect(url_for('index'))
        code = request.args.get('code', '').strip()
        state = request.args.get('state', '').strip()
        if not code:
            return Response('OAuth2 登录失败: 缺少 code', status=400)
        if not state or state != session.get('oauth_state'):
            return Response('OAuth2 登录失败: state 校验失败', status=400)
        if not _mark_oauth_code_used(code):
            existing_user = session.get('oauth_user')
            if existing_user:
                next_url = normalize_next_url(session.get('oauth_next') or '/')
                return redirect(next_url)
            return Response('OAuth2 登录失败: 授权码已被重复使用', status=400)

        try:
            token_resp = requests.post(
                oauth_token_url(),
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': oauth_redirect_uri(),
                    'client_id': oauth_client_id(),
                    'client_secret': oauth_client_secret(),
                },
                headers={
                    'Accept': 'application/json, application/x-www-form-urlencoded;q=0.9, text/plain;q=0.8',
                },
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

            userinfo_resp = requests.get(
                oauth_userinfo_url(),
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=15,
            )
            if userinfo_resp.status_code >= 400:
                return Response('OAuth2 登录失败: 获取用户信息失败', status=400)
            userinfo = userinfo_resp.json()
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
