import csv
from io import StringIO
from urllib.parse import quote

from flask import Response, flash, jsonify, redirect, render_template, request, url_for

from src.app import (
    FEATURE_ALL_COLUMNS,
    MILESTONE_COLUMNS,
    PROJECT_ALL_COLUMNS,
    app,
    build_timestamped_export_filename,
    build_auth_context,
    feature_row_to_db_tuple,
    form_to_feature_data,
    form_to_project_data,
    get_branding,
    get_conn,
    get_project_options,
    import_project_csv_file,
    import_roadmap_csv_content,
    load_project,
    load_project_feature,
    load_project_features,
    load_projects,
    login_required,
    normalize_feature_row,
    normalize_project_row,
    project_row_to_db_tuple,
    preview_roadmap_csv_content,
    require_feature,
    save_feature_csv_content,
)


@app.route('/admin/projects/new', methods=['GET', 'POST'])
@login_required
def admin_project_new():
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    form_data = form_to_project_data(request.form)
    if request.method == 'POST':
        data = form_to_project_data(request.form)
        sql_columns = [
            "project_status", "control_gate", "investment_subject", "project_code", "project_name", "project_description",
            "project_category", "project_subcategory", "project_complexity", "project_role", "project_manager", "planned_start_date", "planned_end_date",
            "workload_person_month", "rd_budget_w", "headcount_budget_self_owned", "headcount_budget_od", "headcount_budget_tm"
        ]
        values = [data[key] for key in sql_columns]
        placeholders = ", ".join(["?"] * len(values))
        with get_conn() as conn:
            conn.execute(
                f"INSERT INTO projects ({', '.join(sql_columns)}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
        return redirect(url_for('view_placeholder', view_key='department-pipeline-load'))
    return render_template('project_form.html', project=form_data, mode='new', **build_auth_context())


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
        data = form_to_project_data(request.form)
        set_clause = [
            "project_status = ?",
            "control_gate = ?",
            "investment_subject = ?",
            "project_code = ?",
            "project_name = ?",
            "project_description = ?",
            "project_category = ?",
            "project_subcategory = ?",
            "project_complexity = ?",
            "project_role = ?",
            "project_manager = ?",
            "planned_start_date = ?",
            "planned_end_date = ?",
            "workload_person_month = ?",
            "rd_budget_w = ?",
            "headcount_budget_self_owned = ?",
            "headcount_budget_od = ?",
            "headcount_budget_tm = ?",
            "updated_at = CURRENT_TIMESTAMP"
        ]
        values = [data[key] for key in [
            "project_status", "control_gate", "investment_subject", "project_code", "project_name", "project_description",
            "project_category", "project_subcategory", "project_complexity", "project_role", "project_manager", "planned_start_date", "planned_end_date",
            "workload_person_month", "rd_budget_w", "headcount_budget_self_owned", "headcount_budget_od", "headcount_budget_tm"
        ]] + [project_id]
        with get_conn() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(set_clause)} WHERE id = ?",
                values,
            )
            conn.commit()
        return redirect(url_for('view_placeholder', view_key='department-pipeline-load'))
    return render_template('project_form.html', project=form_data, mode='edit', **build_auth_context())


@app.route('/admin/projects/<int:project_id>/delete', methods=['POST'])
@login_required
def admin_project_delete(project_id):
    denied = require_feature('manage_projects', '当前账号不能管理项目')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute('DELETE FROM projects WHERE id = ?', [project_id])
        conn.commit()
    return redirect(url_for('view_placeholder', view_key='department-pipeline-load'))


@app.route('/admin/features/new', methods=['GET', 'POST'])
@login_required
def admin_feature_new():
    denied = require_feature('manage_features', '当前账号不能管理关键特性')
    if denied:
        return denied
    form_data = form_to_feature_data(request.form)
    project_options = get_project_options()
    if request.method == 'POST':
        data = form_to_feature_data(request.form)
        with get_conn() as conn:
            project_row = conn.execute("SELECT id, project_name, project_code FROM projects WHERE project_name = ? ORDER BY id LIMIT 1", (data['project_name'],)).fetchone()
            if not project_row:
                flash('请选择项目表中已有的项目名称')
                return render_template('feature_form.html', feature=data, months=MILESTONE_COLUMNS, mode='new', project_options=project_options, **build_auth_context())
            project_id = project_row['id']
            feature_month_columns = ', '.join([f'\"{m}\"' for m in MILESTONE_COLUMNS])
            feature_month_placeholders = ', '.join(['?'] * len(MILESTONE_COLUMNS))
            conn.execute(
                f"INSERT INTO project_features (project_id, project_name, five_level_department, focus_work, feature_name, service_group, delivery_pm, {feature_month_columns}) VALUES (?, ?, ?, ?, ?, ?, ?, {feature_month_placeholders})",
                [project_id, project_row['project_name'], data['five_level_department'], data['focus_work'], data['feature_name'], data['service_group'], data['delivery_pm'], *[data[m] for m in MILESTONE_COLUMNS]],
            )
            conn.commit()
        return redirect(url_for('roadmap'))
    return render_template('feature_form.html', feature={}, months=MILESTONE_COLUMNS, mode='new', project_options=project_options, **build_auth_context())


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
    project_options = get_project_options()
    if request.method == 'POST':
        data = form_to_feature_data(request.form)
        with get_conn() as conn:
            project_row = conn.execute("SELECT id, project_name, project_code FROM projects WHERE project_name = ? ORDER BY id LIMIT 1", (data['project_name'],)).fetchone()
            if not project_row:
                flash('请选择项目表中已有的项目名称')
                return render_template('feature_form.html', feature=data, months=MILESTONE_COLUMNS, mode='edit', project_options=project_options, **build_auth_context())
            project_id = project_row['id']
            set_clause = [
                "project_id = ?",
                "project_name = ?",
                "five_level_department = ?",
                "focus_work = ?",
                "feature_name = ?",
                "service_group = ?",
                "delivery_pm = ?",
            ] + [f'\"{month}\" = ?' for month in MILESTONE_COLUMNS] + ["updated_at = CURRENT_TIMESTAMP"]
            values = [project_id, project_row['project_name'], data['five_level_department'], data['focus_work'], data['feature_name'], data['service_group'], data['delivery_pm'], *[data[m] for m in MILESTONE_COLUMNS], feature_id]
            conn.execute(f"UPDATE project_features SET {', '.join(set_clause)} WHERE id = ?", values)
            conn.commit()
        return redirect(url_for('roadmap'))
    feature = dict(current)
    selected_project = next((item for item in project_options if item['project_name'] == feature.get('project_name')), None)
    feature['project_code'] = selected_project['project_code'] if selected_project else ''
    return render_template('feature_form.html', feature=feature, months=MILESTONE_COLUMNS, mode='edit', project_options=project_options, **build_auth_context())


@app.route('/admin/features/<int:feature_id>/delete', methods=['POST'])
@login_required
def admin_feature_delete(feature_id):
    denied = require_feature('manage_features', '当前账号不能管理关键特性')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute('DELETE FROM project_features WHERE id = ?', (feature_id,))
        conn.execute('DELETE FROM user_feature_orders WHERE feature_id = ?', (feature_id,))
        conn.commit()
    flash('已删除关键特性')
    return redirect(url_for('roadmap'))


@app.route('/admin/projects/import-csv', methods=['POST'])
@login_required
def admin_projects_import_csv():
    denied = require_feature('import_export_data', '当前账号不能导入项目数据')
    if denied:
        return denied
    file = request.files.get('csv_file')
    if file and file.filename:
        import_project_csv_file(file, replace=False)
    return redirect(url_for('roadmap'))


@app.route('/admin/roadmap/import-preview-csv', methods=['POST'])
@login_required
def admin_roadmap_import_preview_csv():
    denied = require_feature('import_export_data', '当前账号不能导入关键特性视图数据')
    if denied:
        return jsonify({'ok': False, 'message': '当前账号不能导入关键特性视图数据'}), 403
    file = request.files.get('csv_file')
    if not file or not file.filename:
        return jsonify({'ok': False, 'message': '请选择 CSV 文件'}), 400
    raw = file.read()
    content = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
    try:
        summary = preview_roadmap_csv_content(content)
    except Exception as exc:
        return jsonify({'ok': False, 'message': f'预检查失败：{exc}'}), 400
    summary['ok'] = True
    return jsonify(summary)


@app.route('/admin/roadmap/import-csv', methods=['POST'])
@login_required
def admin_roadmap_import_csv():
    denied = require_feature('import_export_data', '当前账号不能导入关键特性视图数据')
    if denied:
        return denied
    file = request.files.get('csv_file')
    if file and file.filename:
        raw = file.read()
        content = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
        summary = import_roadmap_csv_content(content, replace=False)
        flash(
            f"导入完成：{summary['type_label']}，共 {summary['total']} 行，"
            f"更新 {summary['updates']}，新增 {summary['creates']}，"
            f"缺少关键字段 {summary['invalid']}，未知项目 {summary['unknown_projects']}"
        )
    return redirect(url_for('roadmap'))


@app.route('/admin/projects/template-csv')
@login_required
def admin_projects_template_csv():
    content = '\ufeff' + ','.join(PROJECT_ALL_COLUMNS) + '\n'
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('关键特性描述_导出模板.csv')}"
    return response


@app.route('/admin/projects/export-csv')
@login_required
def admin_projects_export_csv():
    rows = load_projects()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(PROJECT_ALL_COLUMNS)
    for row in rows:
        writer.writerow([
            row.get('project_status', ''),
            row.get('control_gate', ''),
            row.get('investment_subject', ''),
            row.get('project_code', ''),
            row.get('project_name', ''),
            row.get('project_description', ''),
            row.get('project_category', ''),
            row.get('project_subcategory', ''),
            row.get('project_complexity', ''),
            row.get('project_role', ''),
            row.get('project_manager', ''),
            row.get('planned_start_date', ''),
            row.get('planned_end_date', ''),
            row.get('workload_person_month', ''),
            row.get('rd_budget_w', ''),
            row.get('headcount_budget_self_owned', ''),
            row.get('headcount_budget_od', ''),
            row.get('headcount_budget_tm', ''),
        ])
    response = Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(build_timestamped_export_filename('项目数据_导出数据'))}"
    return response


@app.route('/admin/features/import-csv', methods=['POST'])
@login_required
def admin_features_import_csv():
    denied = require_feature('import_export_data', '当前账号不能导入关键特性数据')
    if denied:
        return denied
    file = request.files.get('csv_file')
    if file and file.filename:
        raw = file.read()
        content = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
        save_feature_csv_content(content, replace=False)
    return redirect(url_for('roadmap'))


@app.route('/admin/features/export-csv')
@login_required
def admin_features_export_csv():
    rows = load_project_features()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(FEATURE_ALL_COLUMNS)
    for row in rows:
        writer.writerow([
            row.get('project_name', ''),
            row.get('five_level_department', ''),
            row.get('focus_work', ''),
            row.get('feature_name', ''),
            row.get('service_group', ''),
            row.get('delivery_pm', ''),
            *[row.get(month, '') for month in MILESTONE_COLUMNS],
        ])
    response = Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(build_timestamped_export_filename('关键特性数据_导出数据'))}"
    return response
