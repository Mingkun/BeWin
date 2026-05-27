from flask import flash, redirect, render_template, request, url_for

from src.app import (
    _build_default_home_cards,
    app,
    build_auth_context,
    get_branding,
    get_conn,
    get_current_user_features,
    get_home_cards,
    home_card_definitions,
    load_service_resource,
    login_required,
    require_feature,
)


@app.route('/requirements', methods=['GET', 'POST'])
@login_required
def requirements_page():
    denied = require_feature('submit_requirement', '当前账号不能提交需求')
    if denied and request.method == 'GET':
        return denied
    if request.method == 'POST':
        content = (request.form.get('content') or '').strip()
        if not content:
            flash('需求内容不能为空')
            return redirect(url_for('requirements_page'))
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO requirements_requests (content, status, created_at, updated_at)
                VALUES (?, 'new', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                [content],
            )
            conn.commit()
        flash('需求已提交')
        return redirect(url_for('requirements_page'))
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, content, status, created_at, updated_at
            FROM requirements_requests
            ORDER BY id DESC
            """
        ).fetchall()
    return render_template('requirements.html', branding=get_branding(), requirements=rows, **build_auth_context())


@app.route('/requirements/<int:requirement_id>/status', methods=['POST'])
@login_required
def requirement_status_update(requirement_id):
    denied = require_feature('manage_requirement_status', '当前账号不能管理需求状态')
    if denied:
        return denied
    status = (request.form.get('status') or '').strip()
    with get_conn() as conn:
        conn.execute(
            'UPDATE requirements_requests SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            [status, requirement_id],
        )
        conn.commit()
    flash('需求状态已更新')
    return redirect(url_for('requirements_page'))


@app.route('/views/<view_key>')
@login_required
def view_placeholder(view_key):
    card_defs = home_card_definitions()
    card = next((item for item in card_defs if item['key'] == view_key), None)
    if not card:
        flash('页面不存在')
        return redirect(url_for('index'))
    if view_key == 'cloud-service-view':
        record_id = request.args.get('record_id', type=int)
        record = load_service_resource(record_id) if record_id else None
        return render_template(
            'cloud_service_view.html',
            branding=get_branding(),
            record=record,
            title=card['title'],
            description=card['desc'],
            **build_auth_context(),
        )
    return render_template(
        'view_placeholder.html',
        branding=get_branding(),
        title=card['title'],
        description=card['desc'],
        **build_auth_context(),
    )
