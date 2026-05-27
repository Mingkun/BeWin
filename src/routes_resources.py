from flask import flash, redirect, render_template, request, url_for, Response
from urllib.parse import quote
import csv
from io import StringIO

from src.app import (
    app,
    build_auth_context,
    build_resource_people_summary,
    build_service_resource_summary,
    filter_resource_people_admin,
    filter_service_resources,
    form_to_resource_person_data,
    form_to_service_resource_data,
    format_number,
    get_branding,
    get_conn,
    get_resource_people_admin_filter_options,
    get_service_resource_filter_options,
    import_resource_people_csv_file,
    import_service_resource_csv_file,
    load_departments,
    load_resource_people,
    load_resource_person,
    load_service_resource,
    load_service_resources,
    login_required,
    normalize_service_resource_row,
    require_feature,
    RESOURCE_PEOPLE_COLUMNS,
    SERVICE_RESOURCE_COLUMNS,
)


@app.route('/admin/service-resources')
@login_required
def admin_service_resources():
    denied = require_feature('manage_resources', '当前账号不能管理服务资源')
    if denied:
        return denied
    rows = load_service_resources()
    department_keyword = (request.args.get('department_keyword') or '').strip()
    service_keyword = (request.args.get('service_keyword') or '').strip()
    filtered_rows = filter_service_resources(rows, department_keyword=department_keyword, service_keyword=service_keyword)
    return render_template(
        'service_resource_list.html',
        branding=get_branding(),
        rows=filtered_rows,
        summary=build_service_resource_summary(filtered_rows),
        filter_options=get_service_resource_filter_options(rows),
        department_keyword=department_keyword,
        service_keyword=service_keyword,
        **build_auth_context(),
    )


@app.route('/admin/resource-people')
@login_required
def admin_resource_people():
    denied = require_feature('manage_resources', '当前账号不能管理人员资源')
    if denied:
        return denied
    rows = load_resource_people()
    keyword = (request.args.get('keyword') or '').strip()
    project_name = (request.args.get('project_name') or '').strip()
    department_name = (request.args.get('department_name') or '').strip()
    role_name = (request.args.get('role_name') or '').strip()
    status = (request.args.get('status') or '').strip()
    filtered_rows = filter_resource_people_admin(
        rows,
        keyword=keyword,
        project_name=project_name,
        department_name=department_name,
        role_name=role_name,
        status=status,
    )
    return render_template(
        'resource_person_list.html',
        branding=get_branding(),
        rows=filtered_rows,
        summary=build_resource_people_summary(filtered_rows),
        filter_options=get_resource_people_admin_filter_options(rows),
        keyword=keyword,
        project_name=project_name,
        department_name=department_name,
        role_name=role_name,
        status=status,
        **build_auth_context(),
    )


@app.route('/admin/resource-people/new', methods=['GET', 'POST'])
@login_required
def admin_resource_person_new():
    denied = require_feature('manage_resources', '当前账号不能管理人员资源')
    if denied:
        return denied
    form_data = form_to_resource_person_data(request.form)
    if request.method == 'POST':
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO resource_people (
                    person_name, person_type, project_name, five_level_department, role_name, service_group, status,
                    workload_percent, start_date, end_date, remarks, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    form_data['person_name'], form_data['person_type'], form_data['project_name'], form_data['five_level_department'],
                    form_data['role_name'], form_data['service_group'], form_data['status'], form_data['workload_percent'],
                    form_data['start_date'], form_data['end_date'], form_data['remarks'],
                ),
            )
            conn.commit()
        flash('已新增人员资源')
        return redirect(url_for('admin_resource_people'))
    return render_template('resource_person_form.html', branding=get_branding(), mode='new', form_data=form_data, departments=load_departments(), **build_auth_context())


@app.route('/admin/resource-people/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_resource_person_edit(record_id):
    denied = require_feature('manage_resources', '当前账号不能管理人员资源')
    if denied:
        return denied
    current = load_resource_person(record_id)
    if not current:
        flash('记录不存在')
        return redirect(url_for('admin_resource_people'))
    form_data = form_to_resource_person_data(request.form) if request.method == 'POST' else current
    if request.method == 'POST':
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE resource_people
                SET person_name = ?, person_type = ?, project_name = ?, five_level_department = ?, role_name = ?,
                    service_group = ?, status = ?, workload_percent = ?, start_date = ?, end_date = ?, remarks = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    form_data['person_name'], form_data['person_type'], form_data['project_name'], form_data['five_level_department'],
                    form_data['role_name'], form_data['service_group'], form_data['status'], form_data['workload_percent'],
                    form_data['start_date'], form_data['end_date'], form_data['remarks'], record_id,
                ),
            )
            conn.commit()
        flash('已更新人员资源')
        return redirect(url_for('admin_resource_people'))
    return render_template('resource_person_form.html', branding=get_branding(), mode='edit', form_data=form_data, departments=load_departments(), **build_auth_context())


@app.route('/admin/resource-people/<int:record_id>/delete', methods=['POST'])
@login_required
def admin_resource_person_delete(record_id):
    denied = require_feature('manage_resources', '当前账号不能管理人员资源')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute('DELETE FROM resource_people WHERE id = ?', [record_id])
        conn.commit()
    flash('已删除人员资源')
    return redirect(url_for('admin_resource_people'))


@app.route('/admin/service-resources/new', methods=['GET', 'POST'])
@login_required
def admin_service_resource_new():
    denied = require_feature('manage_resources', '当前账号不能管理服务资源')
    if denied:
        return denied
    form_data = form_to_service_resource_data(request.form)
    if request.method == 'POST':
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO service_resource_investment (
                    five_level_department, l4_cloud_service, function_description,
                    summary_self_owned, summary_od, summary_tm,
                    hc_self_owned, hc_od, hc_tm,
                    hcs_self_owned, hcs_od, hcs_tm, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    form_data['five_level_department'], form_data['l4_cloud_service'], form_data['function_description'],
                    form_data['summary_self_owned'], form_data['summary_od'], form_data['summary_tm'],
                    form_data['hc_self_owned'], form_data['hc_od'], form_data['hc_tm'],
                    form_data['hcs_self_owned'], form_data['hcs_od'], form_data['hcs_tm'],
                ),
            )
            conn.commit()
        flash('已新增服务资源')
        return redirect(url_for('admin_service_resources'))
    return render_template('service_resource_form.html', branding=get_branding(), mode='new', form_data=form_data, departments=load_departments(), **build_auth_context())


@app.route('/admin/service-resources/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_service_resource_edit(record_id):
    denied = require_feature('manage_resources', '当前账号不能管理服务资源')
    if denied:
        return denied
    current = load_service_resource(record_id)
    if not current:
        flash('记录不存在')
        return redirect(url_for('admin_service_resources'))
    form_data = form_to_service_resource_data(request.form) if request.method == 'POST' else current
    if request.method == 'POST':
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE service_resource_investment
                SET five_level_department = ?, l4_cloud_service = ?, function_description = ?,
                    summary_self_owned = ?, summary_od = ?, summary_tm = ?,
                    hc_self_owned = ?, hc_od = ?, hc_tm = ?,
                    hcs_self_owned = ?, hcs_od = ?, hcs_tm = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    form_data['five_level_department'], form_data['l4_cloud_service'], form_data['function_description'],
                    form_data['summary_self_owned'], form_data['summary_od'], form_data['summary_tm'],
                    form_data['hc_self_owned'], form_data['hc_od'], form_data['hc_tm'],
                    form_data['hcs_self_owned'], form_data['hcs_od'], form_data['hcs_tm'], record_id,
                ),
            )
            conn.commit()
        flash('已更新服务资源')
        return redirect(url_for('admin_service_resources'))
    return render_template('service_resource_form.html', branding=get_branding(), mode='edit', form_data=form_data, departments=load_departments(), **build_auth_context())


@app.route('/admin/service-resources/<int:record_id>/delete', methods=['POST'])
@login_required
def admin_service_resource_delete(record_id):
    denied = require_feature('manage_resources', '当前账号不能管理服务资源')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute('DELETE FROM service_resource_investment WHERE id = ?', [record_id])
        conn.commit()
    flash('已删除服务资源')
    return redirect(url_for('admin_service_resources'))


@app.route('/admin/resource-people/import-csv', methods=['POST'])
@login_required
def admin_resource_people_import_csv():
    denied = require_feature('manage_resources', '当前账号不能管理人员资源')
    if denied:
        return denied
    file = request.files.get('file')
    import_resource_people_csv_file(file, replace=True)
    flash('人员资源 CSV 导入完成')
    return redirect(url_for('admin_resource_people'))


@app.route('/admin/service-resources/import-csv', methods=['POST'])
@login_required
def admin_service_resources_import_csv():
    denied = require_feature('manage_resources', '当前账号不能管理服务资源')
    if denied:
        return denied
    file = request.files.get('file')
    import_service_resource_csv_file(file, replace=True)
    flash('服务资源 CSV 导入完成')
    return redirect(url_for('admin_service_resources'))


@app.route('/admin/resource-people/template-csv')
@login_required
def admin_resource_people_template_csv():
    denied = require_feature('manage_resources', '当前账号不能管理人员资源')
    if denied:
        return denied
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=RESOURCE_PEOPLE_COLUMNS)
    writer.writeheader()
    content = sio.getvalue()
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('人员资源导入模板.csv')}"
    return response


@app.route('/admin/service-resources/template-csv')
@login_required
def admin_service_resources_template_csv():
    denied = require_feature('manage_resources', '当前账号不能管理服务资源')
    if denied:
        return denied
    sio = StringIO()
    writer = csv.DictWriter(sio, fieldnames=SERVICE_RESOURCE_COLUMNS)
    writer.writeheader()
    content = sio.getvalue()
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('服务资源导入模板.csv')}"
    return response
