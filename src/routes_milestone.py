from flask import Response, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from src.app import (
    MILESTONE_MEDIA_DIR,
    app,
    build_auth_context,
    build_milestone_board,
    get_branding,
    load_milestone_condolence_items,
    login_required,
    milestone_image_url,
    milestone_month_options,
    permission_config_service,
    require_feature,
    save_milestone_condolence_image,
)


@app.route('/picture/milestone_condolence/<path:filename>')
@login_required
def milestone_condolence_image_route(filename):
    safe_name = secure_filename(filename)
    if not safe_name:
        return Response('图片不存在', status=404)
    current_path = MILESTONE_MEDIA_DIR / safe_name
    if current_path.exists():
        return send_from_directory(MILESTONE_MEDIA_DIR, safe_name)
    return Response('图片不存在', status=404)


@app.route('/milestone-condolence')
@login_required
def milestone_condolence_page():
    return render_template(
        'milestone_condolence.html',
        branding=get_branding(),
        month_options=milestone_month_options(),
        board=build_milestone_board(load_milestone_condolence_items()),
        milestone_image_url=milestone_image_url,
        user_features=build_auth_context().get('user_features', permission_config_service.default_feature_flags('user')),
        **build_auth_context(),
    )


@app.route('/admin/milestone-condolence/new', methods=['GET', 'POST'])
@login_required
def admin_milestone_condolence_new():
    denied = require_feature('manage_features', '当前账号不能维护关键突破&战地激励')
    if denied:
        return denied
    from src.app import get_conn, get_milestone_departments
    items = load_milestone_condolence_items()
    form_data = {
        'five_level_department': (request.form.get('five_level_department') or '').strip(),
        'month_index': (request.form.get('month_index') or '').strip(),
        'activity_date': (request.form.get('activity_date') or '').strip(),
        'participant_names': (request.form.get('participant_names') or '').strip(),
        'breakthrough_text': (request.form.get('breakthrough_text') or '').strip(),
        'condolence_region': (request.form.get('condolence_region') or '').strip(),
    }
    if request.method == 'POST':
        image_path = save_milestone_condolence_image(request.files.get('image_file'))
        month_index = int(form_data['month_index'] or '0')
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO milestone_condolence (
                    five_level_department, month_index, activity_date, participant_names, breakthrough_text, condolence_region, image_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                [form_data['five_level_department'], month_index, form_data['activity_date'], form_data['participant_names'], form_data['breakthrough_text'], form_data['condolence_region'], image_path],
            )
            conn.commit()
        flash('已新增关键突破&战地激励')
        return redirect(url_for('milestone_condolence_page'))
    return render_template(
        'milestone_condolence_form.html',
        branding=get_branding(),
        mode='new',
        form_data=form_data,
        months=milestone_month_options(),
        departments=get_milestone_departments(items),
        image_url='',
        current_image_path='',
        **build_auth_context(),
    )


@app.route('/admin/milestone-condolence/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_milestone_condolence_edit(item_id):
    denied = require_feature('manage_features', '当前账号不能维护关键突破&战地激励')
    if denied:
        return denied
    from src.app import get_conn, get_milestone_departments
    items = load_milestone_condolence_items()
    with get_conn() as conn:
        current = conn.execute(
            """
            SELECT id, five_level_department, month_index, activity_date, participant_names, breakthrough_text, condolence_region, image_path
            FROM milestone_condolence
            WHERE id = ?
            """,
            [item_id],
        ).fetchone()
        if not current:
            flash('记录不存在')
            return redirect(url_for('milestone_condolence_page'))
        current = dict(current)
        if request.method == 'POST':
            form_data = {
                'five_level_department': (request.form.get('five_level_department') or current.get('five_level_department') or '').strip(),
                'month_index': (request.form.get('month_index') or current.get('month_index') or '').strip(),
                'activity_date': (request.form.get('activity_date') or current.get('activity_date') or '').strip(),
                'participant_names': (request.form.get('participant_names') or current.get('participant_names') or '').strip(),
                'breakthrough_text': (request.form.get('breakthrough_text') or current.get('breakthrough_text') or '').strip(),
                'condolence_region': (request.form.get('condolence_region') or current.get('condolence_region') or '').strip(),
            }
            image_path = current.get('image_path') or ''
            new_image_path = save_milestone_condolence_image(request.files.get('image_file'))
            if new_image_path:
                image_path = new_image_path
            month_index = int(form_data['month_index'] or '0')
            conn.execute(
                """
                UPDATE milestone_condolence
                SET five_level_department = ?,
                    month_index = ?,
                    activity_date = ?,
                    participant_names = ?,
                    breakthrough_text = ?,
                    condolence_region = ?,
                    image_path = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [form_data['five_level_department'], month_index, form_data['activity_date'], form_data['participant_names'], form_data['breakthrough_text'], form_data['condolence_region'], image_path, item_id],
            )
            conn.commit()
            flash('已更新关键突破&战地激励')
            return redirect(url_for('milestone_condolence_page'))
    return render_template(
        'milestone_condolence_form.html',
        branding=get_branding(),
        mode='edit',
        form_data=current,
        months=milestone_month_options(),
        departments=get_milestone_departments(items),
        image_url=milestone_image_url(current.get('image_path') or ''),
        current_image_path=current.get('image_path') or '',
        **build_auth_context(),
    )


@app.route('/admin/milestone-condolence/<int:item_id>/delete', methods=['POST'])
@login_required
def admin_milestone_condolence_delete(item_id):
    denied = require_feature('manage_features', '当前账号不能维护关键突破&战地激励')
    if denied:
        return denied
    from src.app import get_conn
    with get_conn() as conn:
        conn.execute('DELETE FROM milestone_condolence WHERE id = ?', [item_id])
        conn.commit()
    flash('已删除关键突破&战地激励')
    return redirect(url_for('milestone_condolence_page'))
