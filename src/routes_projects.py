import csv
from io import StringIO
from urllib.parse import quote

from flask import Response, flash, redirect, render_template, request, url_for

from src.app import (
    FEATURE_COLUMNS,
    PROJECT_COLUMNS,
    app,
    build_auth_context,
    feature_row_to_db_tuple,
    form_to_feature_data,
    form_to_project_data,
    get_branding,
    get_conn,
    get_project_options,
    import_project_csv_file,
    load_project,
    load_project_feature,
    load_project_options,
    login_required,
    normalize_feature_row,
    normalize_project_row,
    project_row_to_db_tuple,
    require_feature,
    save_feature_csv_content,
    save_project_csv_content,
)


@app.route('/admin/projects/new', methods=['GET', 'POST'])
@login_required
def admin_project_new():
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    form_data = form_to_project_data(request.form)
    if request.method == 'POST':
        row = normalize_project_row(form_data)
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    status, control_stove, investment_subject, project_code, project_name, project_description,
                    project_category, project_subcategory, project_complexity, project_role, project_manager,
                    planned_start_date, planned_end_date, workload_person_month, rd_budget_wan,
                    budget_self_owned, budget_od, budget_tm, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                project_row_to_db_tuple(row),
            )
            conn.commit()
        flash('已新增项目')
        return redirect(url_for('index'))
    return render_template('project_form.html', branding=get_branding(), mode='new', form_data=form_data, **build_auth_context())


@app.route('/admin/projects/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_project_edit(project_id):
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    current = load_project(project_id)
    if not current:
        flash('项目不存在')
        return redirect(url_for('index'))
    form_data = form_to_project_data(request.form) if request.method == 'POST' else current
    if request.method == 'POST':
        row = normalize_project_row(form_data)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE projects
                SET status = ?, control_stove = ?, investment_subject = ?, project_code = ?, project_name = ?,
                    project_description = ?, project_category = ?, project_subcategory = ?, project_complexity = ?,
                    project_role = ?, project_manager = ?, planned_start_date = ?, planned_end_date = ?,
                    workload_person_month = ?, rd_budget_wan = ?, budget_self_owned = ?, budget_od = ?, budget_tm = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*project_row_to_db_tuple(row), project_id),
            )
            conn.commit()
        flash('已更新项目')
        return redirect(url_for('index'))
    return render_template('project_form.html', branding=get_branding(), mode='edit', form_data=form_data, **build_auth_context())


@app.route('/admin/projects/<int:project_id>/delete', methods=['POST'])
@login_required
def admin_project_delete(project_id):
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute('DELETE FROM projects WHERE id = ?', [project_id])
        conn.commit()
    flash('已删除项目')
    return redirect(url_for('index'))


@app.route('/admin/features/new', methods=['GET', 'POST'])
@login_required
def admin_feature_new():
    denied = require_feature('manage_features', '当前账号不能管理关键特性')
    if denied:
        return denied
    form_data = form_to_feature_data(request.form)
    if request.method == 'POST':
        row = normalize_feature_row(form_data)
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO features (
                    project_id, project_name, five_level_department, focus_work, feature_name,
                    service_group, delivery_pm,
                    month_1, month_2, month_3, month_4, month_5, month_6,
                    month_7, month_8, month_9, month_10, month_11, month_12,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                feature_row_to_db_tuple(row, project_id=row.get('project_id')),
            )
            conn.commit()
        flash('已新增关键特性')
        return redirect(url_for('index'))
    return render_template('feature_form.html', branding=get_branding(), mode='new', form_data=form_data, project_options=load_project_options(), **build_auth_context())


@app.route('/admin/features/<int:feature_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_feature_edit(feature_id):
    denied = require_feature('manage_features', '当前账号不能管理关键特性')
    if denied:
        return denied
    current = load_project_feature(feature_id)
    if not current:
        flash('关键特性不存在')
        return redirect(url_for('index'))
    form_data = form_to_feature_data(request.form) if request.method == 'POST' else current
    if request.method == 'POST':
        row = normalize_feature_row(form_data)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE features
                SET project_id = ?, project_name = ?, five_level_department = ?, focus_work = ?, feature_name = ?,
                    service_group = ?, delivery_pm = ?, month_1 = ?, month_2 = ?, month_3 = ?, month_4 = ?,
                    month_5 = ?, month_6 = ?, month_7 = ?, month_8 = ?, month_9 = ?, month_10 = ?, month_11 = ?, month_12 = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*feature_row_to_db_tuple(row, project_id=row.get('project_id')), feature_id),
            )
            conn.commit()
        flash('已更新关键特性')
        return redirect(url_for('index'))
    return render_template('feature_form.html', branding=get_branding(), mode='edit', form_data=form_data, project_options=get_project_options(), **build_auth_context())


@app.route('/admin/features/<int:feature_id>/delete', methods=['POST'])
@login_required
def admin_feature_delete(feature_id):
    denied = require_feature('manage_features', '当前账号不能管理关键特性')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute('DELETE FROM features WHERE id = ?', [feature_id])
        conn.commit()
    flash('已删除关键特性')
    return redirect(url_for('index'))


@app.route('/admin/projects/import-csv', methods=['POST'])
@login_required
def admin_projects_import_csv():
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    file = request.files.get('file')
    import_project_csv_file(file, replace=True)
    flash('项目 CSV 导入完成')
    return redirect(url_for('index'))


@app.route('/admin/projects/template-csv')
@login_required
def admin_projects_template_csv():
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=PROJECT_COLUMNS)
    writer.writeheader()
    content = sio.getvalue()
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('项目导入模板.csv')}"
    return response


@app.route('/admin/projects/export-csv')
@login_required
def admin_projects_export_csv():
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    rows = load_project_options()
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=PROJECT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    content = sio.getvalue()
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('项目数据_导出数据.csv')}"
    return response


@app.route('/admin/features/export-csv')
@login_required
def admin_features_export_csv():
    denied = require_feature('manage_features', '当前账号不能管理关键特性')
    if denied:
        return denied
    from src.app import load_project_features
    rows = load_project_features()
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=FEATURE_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    content = sio.getvalue()
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('关键特性数据_导出数据.csv')}"
    return response
