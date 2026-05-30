import json

from flask import render_template, request, redirect, session, url_for

from src.app import (
    app,
    auth_mode,
    build_auth_context,
    can_access,
    get_branding,
    get_current_user,
    get_current_user_features,
    get_current_user_roles,
    get_request_client_ip,
    list_recent_active_logins,
    local_admin_enabled,
    login_required,
    match_permission_rule,
    milestone_image_url,
    normalize_feature_flags,
    normalize_next_url,
    oauth_enabled,
    record_login_audit,
    verify_local_admin,
    verify_local_user,
    default_feature_flags,
)
from src.oauth_auth import DEFAULT_OAUTH_DEBUG_LOG_PATH, get_oauth_debug_log_path


@app.route('/login')
def login_entry():
    next_url = normalize_next_url(request.args.get('next') or '/')
    mode = auth_mode()
    if mode == 'local':
        return redirect(url_for('local_login_form', next=next_url))
    if mode == 'oauth':
        return redirect(url_for('oauth_login', next=next_url))
    return render_template(
        'login_choice.html',
        next=next_url,
        oauth_enabled=oauth_enabled(),
        local_enabled=local_admin_enabled(),
        branding=get_branding(),
        **build_auth_context(),
    )


@app.route('/login/local', methods=['GET', 'POST'])
def local_login_form():
    next_url = normalize_next_url((request.form.get('next') if request.method == 'POST' else request.args.get('next')) or '/')
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if verify_local_admin(username, password):
            session['local_user'] = {
                'user_id': username,
                'name': username,
                'email': '',
                'roles': ['admin'],
                'features': default_feature_flags('admin'),
                'auth_type': 'local',
            }
            record_login_audit(session['local_user'])
            return redirect(next_url)
        if verify_local_user(username, password):
            matched_rule = match_permission_rule(source='local', username=username, email='')
            role = (matched_rule or {}).get('role') or 'user'
            session['local_user'] = {
                'user_id': username,
                'name': username,
                'email': '',
                'roles': [role],
                'features': normalize_feature_flags((matched_rule or {}).get('features'), role),
                'auth_type': 'local',
            }
            record_login_audit(session['local_user'])
            return redirect(next_url)
        return redirect(url_for('local_login_form', next=next_url))
    return render_template('local_login.html', next=next_url, branding=get_branding(), **build_auth_context())


@app.route('/logout')
def logout():
    session.pop('local_user', None)
    session.pop('oauth_user', None)
    session.pop('login_audit_token', None)
    return redirect(url_for('login_entry'))


@app.route('/settings/auth-debug')
@login_required
def settings_auth_debug_page():
    current_user = get_current_user() or {}
    can_view_system_debug = can_access('view_system')
    oauth_raw = current_user.get('raw') if isinstance(current_user.get('raw'), dict) else {}
    oauth_log_path_obj = get_oauth_debug_log_path()
    oauth_log_exists = oauth_log_path_obj.exists()
    oauth_log_size = oauth_log_path_obj.stat().st_size if oauth_log_exists else 0
    oauth_log_mtime = oauth_log_path_obj.stat().st_mtime if oauth_log_exists else None
    oauth_log_mtime_text = ''
    if oauth_log_mtime:
        from datetime import datetime
        oauth_log_mtime_text = datetime.fromtimestamp(oauth_log_mtime).strftime('%Y-%m-%d %H:%M:%S')
    oauth_debug_summary = {
        'display_name': current_user.get('name') or '',
        'username': current_user.get('username') or oauth_raw.get('preferred_username') or oauth_raw.get('login') or oauth_raw.get('name') or '',
        'email': current_user.get('email') or oauth_raw.get('email') or '',
        'employee_number': oauth_raw.get('employeeNumber') or oauth_raw.get('employee_number') or '',
        'user_id': current_user.get('user_id') or '',
        'auth_type': current_user.get('auth_type') or '',
        'roles': current_user.get('roles') or [],
    }
    return render_template(
        'settings_auth_debug.html',
        branding=get_branding(),
        page_title='系统调试',
        page_desc='查看当前登录会话。系统管理员可查看 OAuth 调试日志和最近活跃登录记录。',
        can_view_system_debug=can_view_system_debug,
        current_roles=get_current_user_roles(),
        current_features=get_current_user_features(),
        oauth_debug_summary=oauth_debug_summary,
        current_user_pretty=json.dumps(current_user, ensure_ascii=False, indent=2) if can_view_system_debug else '',
        oauth_raw_pretty=json.dumps(oauth_raw, ensure_ascii=False, indent=2) if can_view_system_debug else '',
        active_logins=list_recent_active_logins(24) if can_view_system_debug else [],
        oauth_log_path=str(oauth_log_path_obj),
        oauth_log_default_path=str(DEFAULT_OAUTH_DEBUG_LOG_PATH),
        oauth_log_exists=oauth_log_exists,
        oauth_log_size=oauth_log_size,
        oauth_log_mtime=oauth_log_mtime_text,
        milestone_image_url=milestone_image_url,
        request_client_ip=get_request_client_ip(),
        **build_auth_context(),
    )
