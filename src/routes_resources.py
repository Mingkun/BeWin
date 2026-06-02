from flask import Response, redirect, render_template, request, url_for
from urllib.parse import quote
import csv
from io import StringIO

from src.app import (
    app,
    build_timestamped_export_filename,
    build_auth_context,
    build_resource_people_summary,
    build_service_resource_summary,
    filter_resource_people_admin,
    filter_service_resources,
    form_to_department_data,
    form_to_resource_person_data,
    form_to_service_resource_data,
    get_branding,
    get_conn,
    get_resource_people_admin_filter_options,
    get_service_resource_filter_options,
    import_resource_people_csv_file,
    import_service_resource_csv_file,
    load_department,
    load_departments,
    load_project_options,
    load_resource_people,
    load_resource_person,
    load_service_resource,
    load_service_resources,
    login_required,
    require_feature,
)


@app.route('/admin/service-resources')
@login_required
def admin_service_resources():
    denied = require_feature('manage_service_resources', '当前账号不能管理云服务数据')
    if denied:
        return denied
    rows = load_service_resources()
    department_keyword = (request.args.get('department_keyword') or '').strip()
    service_keyword = (request.args.get('service_keyword') or '').strip()
    leader_keyword = (request.args.get('leader_keyword') or '').strip()
    filtered_rows = filter_service_resources(
        rows,
        department_keyword=department_keyword,
        service_keyword=service_keyword,
        leader_keyword=leader_keyword,
    )
    return render_template(
        'service_resource_list.html',
        branding=get_branding(),
        records=filtered_rows,
        summary=build_service_resource_summary(filtered_rows),
        filter_options=get_service_resource_filter_options(rows),
        department_keyword=department_keyword,
        service_keyword=service_keyword,
        leader_keyword=leader_keyword,
        **build_auth_context(),
    )


@app.route('/admin/departments')
@login_required
def admin_departments():
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    rows = load_departments()
    edit_id = (request.args.get('edit_id') or '').strip()
    return render_template('department_list.html', records=rows, edit_id=edit_id, **build_auth_context())


@app.route('/admin/departments/new', methods=['GET', 'POST'])
@login_required
def admin_department_new():
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    if request.method == 'POST':
        data = form_to_department_data(request.form)
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO departments (
                    level_1_department, level_2_department
                ) VALUES (?, ?)
                """,
                (
                    data['level_1_department'], data['level_2_department'],
                ),
            )
            conn.commit()
        return redirect(url_for('admin_departments'))
    return render_template('department_form.html', record={}, mode='new', **build_auth_context())


@app.route('/admin/departments/<int:department_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_department_edit(department_id):
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    record = load_department(department_id)
    if not record:
        return redirect(url_for('admin_departments'))
    if request.method == 'POST':
        data = form_to_department_data(request.form)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE departments
                SET level_1_department = ?,
                    level_2_department = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    data['level_1_department'], data['level_2_department'],
                    department_id,
                ),
            )
            conn.commit()
        return redirect(url_for('admin_departments'))
    return render_template('department_form.html', record=record, mode='edit', **build_auth_context())


@app.route('/admin/departments/<int:department_id>/delete', methods=['POST'])
@login_required
def admin_department_delete(department_id):
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute("DELETE FROM departments WHERE id = ?", (department_id,))
        conn.commit()
    return redirect(url_for('admin_departments'))


@app.route('/admin/resource-people')
@login_required
def admin_resource_people():
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    rows = load_resource_people()
    department_options = load_departments()
    project_options = load_project_options()
    keyword = (request.args.get('keyword') or '').strip()
    project_name = (request.args.get('project_name') or '').strip()
    department_name = (request.args.get('department_name') or '').strip()
    upper_department = (request.args.get('upper_department') or '').strip()
    smallest_department = (request.args.get('smallest_department') or '').strip()
    role_name = (request.args.get('role_name') or '').strip()
    status = (request.args.get('status') or '').strip()
    edit_id = (request.args.get('edit_id') or '').strip()
    filtered_rows = filter_resource_people_admin(
        rows,
        keyword=keyword,
        project_name=project_name,
        department_name=department_name,
        upper_department=upper_department,
        smallest_department=smallest_department,
        role_name=role_name,
        status=status,
    )
    return render_template(
        'resource_person_list.html',
        records=filtered_rows,
        filter_options=get_resource_people_admin_filter_options(rows),
        filters={
            'keyword': keyword,
            'project_name': project_name,
            'department_name': department_name,
            'upper_department': upper_department,
            'smallest_department': smallest_department,
            'role_name': role_name,
            'status': status,
        },
        edit_id=edit_id,
        department_options=department_options,
        project_options=project_options,
        **build_auth_context(),
    )


@app.route('/admin/resource-people/new', methods=['GET', 'POST'])
@login_required
def admin_resource_person_new():
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    department_options = load_departments()
    project_options = load_project_options()
    if request.method == 'POST':
        data = form_to_resource_person_data(request.form)
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO resource_people (
                    employee_id, employee_name, person_type, department_id, project_id,
                    allocation_ratio, role_name, status, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data['employee_id'], data['employee_name'], data['person_type'], data['department_id'], data['project_id'],
                    data['allocation_ratio'], data['role_name'], data['status'], data['remarks'],
                ),
            )
            conn.commit()
        return redirect(url_for('admin_resource_people'))
    return render_template('resource_person_form.html', record={}, mode='new', department_options=department_options, project_options=project_options, **build_auth_context())


@app.route('/admin/resource-people/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_resource_person_edit(record_id):
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    record = load_resource_person(record_id)
    if not record:
        return redirect(url_for('admin_resource_people'))
    department_options = load_departments()
    project_options = load_project_options()
    if request.method == 'POST':
        data = form_to_resource_person_data(request.form)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE resource_people
                SET employee_id = ?,
                    employee_name = ?,
                    person_type = ?,
                    department_id = ?,
                    project_id = ?,
                    allocation_ratio = ?,
                    role_name = ?,
                    status = ?,
                    remarks = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    data['employee_id'], data['employee_name'], data['person_type'], data['department_id'], data['project_id'],
                    data['allocation_ratio'], data['role_name'], data['status'], data['remarks'], record_id,
                ),
            )
            conn.commit()
        return redirect(url_for('admin_resource_people'))
    return render_template('resource_person_form.html', record=record, mode='edit', department_options=department_options, project_options=project_options, **build_auth_context())


@app.route('/admin/resource-people/<int:record_id>/delete', methods=['POST'])
@login_required
def admin_resource_person_delete(record_id):
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute("DELETE FROM resource_people WHERE id = ?", (record_id,))
        conn.commit()
    return redirect(url_for('admin_resource_people'))


@app.route('/admin/service-resources/new', methods=['GET', 'POST'])
@login_required
def admin_service_resource_new():
    denied = require_feature('manage_service_resources', '当前账号不能管理云服务数据')
    if denied:
        return denied
    if request.method == 'POST':
        data = form_to_service_resource_data(request.form)
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO service_resource_investment (
                    five_level_department,
                    l4_cloud_service,
                    function_description,
                    service_leader,
                    summary_self_owned,
                    summary_od,
                    summary_tm,
                    hc_self_owned,
                    hc_od,
                    hc_tm,
                    hcs_self_owned,
                    hcs_od,
                    hcs_tm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data['five_level_department'], data['l4_cloud_service'], data['function_description'], data['service_leader'],
                    data['summary_self_owned'], data['summary_od'], data['summary_tm'],
                    data['hc_self_owned'], data['hc_od'], data['hc_tm'],
                    data['hcs_self_owned'], data['hcs_od'], data['hcs_tm'],
                ),
            )
            conn.commit()
        return redirect(url_for('admin_service_resources'))
    return render_template('service_resource_form.html', record={}, mode='new', **build_auth_context())


@app.route('/admin/service-resources/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_service_resource_edit(record_id):
    denied = require_feature('manage_service_resources', '当前账号不能管理云服务数据')
    if denied:
        return denied
    record = load_service_resource(record_id)
    return_to = request.args.get('return_to') or url_for('view_placeholder', view_key='cloud-service-view')
    if not record:
        return redirect(return_to)
    if request.method == 'POST':
        data = form_to_service_resource_data(request.form)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE service_resource_investment
                SET five_level_department = ?,
                    l4_cloud_service = ?,
                    function_description = ?,
                    service_leader = ?,
                    summary_self_owned = ?,
                    summary_od = ?,
                    summary_tm = ?,
                    hc_self_owned = ?,
                    hc_od = ?,
                    hc_tm = ?,
                    hcs_self_owned = ?,
                    hcs_od = ?,
                    hcs_tm = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    data['five_level_department'], data['l4_cloud_service'], data['function_description'], data['service_leader'],
                    data['summary_self_owned'], data['summary_od'], data['summary_tm'],
                    data['hc_self_owned'], data['hc_od'], data['hc_tm'],
                    data['hcs_self_owned'], data['hcs_od'], data['hcs_tm'], record_id,
                ),
            )
            conn.commit()
        return redirect(return_to)
    return render_template('service_resource_form.html', record=record, mode='edit', return_to=return_to, **build_auth_context())


@app.route('/admin/service-resources/<int:record_id>/delete', methods=['POST'])
@login_required
def admin_service_resource_delete(record_id):
    denied = require_feature('manage_service_resources', '当前账号不能管理云服务数据')
    if denied:
        return denied
    return_to = request.form.get('return_to') or request.args.get('return_to') or url_for('view_placeholder', view_key='cloud-service-view')
    with get_conn() as conn:
        conn.execute("DELETE FROM service_resource_investment WHERE id = ?", (record_id,))
        conn.commit()
    return redirect(return_to)


@app.route('/admin/resource-people/import-csv', methods=['POST'])
@login_required
def admin_resource_people_import_csv():
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    file = request.files.get('csv_file')
    if file and file.filename:
        import_resource_people_csv_file(file, replace=True)
    return redirect(url_for('admin_resource_people'))


@app.route('/admin/service-resources/import-csv', methods=['POST'])
@login_required
def admin_service_resources_import_csv():
    denied = require_feature('import_export_data', '当前账号不能导入云服务数据')
    if denied:
        return denied
    file = request.files.get('csv_file')
    if file and file.filename:
        import_service_resource_csv_file(file, replace=True)
    return redirect(url_for('view_placeholder', view_key='cloud-service-view'))


@app.route('/admin/resource-people/template-csv')
@login_required
def admin_resource_people_template_csv():
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(['工号', '姓名', '人员类型', '上层部门', '最小部门', '所属项目', '投入比例', '角色', '状态', '备注'])
    content = '\ufeff' + sio.getvalue()
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('人员资源导入模板.csv')}"
    return response


@app.route('/admin/resource-people/export-csv')
@login_required
def admin_resource_people_export_csv():
    denied = require_feature('manage_service_resources', '当前账号不能管理资源视图基础数据')
    if denied:
        return denied
    rows = load_resource_people()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['工号', '姓名', '人员类型', '上层部门', '最小部门', '所属项目', '投入比例', '角色', '状态', '备注'])
    for row in rows:
        writer.writerow([
            row.get('employee_id') or '',
            row.get('employee_name') or '',
            row.get('person_type') or '',
            row.get('upper_department_name') or '',
            row.get('smallest_department_name') or '',
            row.get('project_name') or '',
            row.get('allocation_ratio') or '',
            row.get('role_name') or '',
            row.get('status') or '',
            row.get('remarks') or '',
        ])
    response = Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(build_timestamped_export_filename('人员资源库_导出数据'))}"
    return response


@app.route('/admin/service-resources/template-csv')
@login_required
def admin_service_resources_template_csv():
    denied = require_feature('import_export_data', '当前账号不能导入云服务数据')
    if denied:
        return denied
    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(['五层部门', 'L4云服务', '功能和用途简介', '服务Leader', 'HC（自有）', 'HC（OD）', 'HC（TM）', 'HCS（自有）', 'HCS（OD）', 'HCS（TM）', '汇总（自有）', '汇总（OD）', '汇总（TM）'])
    content = '\ufeff' + sio.getvalue()
    response = Response(content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('服务资源导入模板.csv')}"
    return response


@app.route('/admin/service-resources/export-csv')
@login_required
def admin_service_resources_export_csv():
    rows = load_service_resources()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['五层部门', 'L4云服务', '功能和用途简介', '服务Leader', 'HC（自有）', 'HC（OD）', 'HC（TM）', 'HCS（自有）', 'HCS（OD）', 'HCS（TM）', '汇总（自有）', '汇总（OD）', '汇总（TM）'])
    for row in rows:
        writer.writerow([
            row.get('five_level_department', ''),
            row.get('l4_cloud_service', ''),
            row.get('function_description', ''),
            row.get('service_leader', ''),
            row.get('hc_self_owned', ''),
            row.get('hc_od', ''),
            row.get('hc_tm', ''),
            row.get('hcs_self_owned', ''),
            row.get('hcs_od', ''),
            row.get('hcs_tm', ''),
            row.get('summary_self_owned', ''),
            row.get('summary_od', ''),
            row.get('summary_tm', ''),
        ])
    response = Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(build_timestamped_export_filename('服务资源数据_导出数据'))}"
    return response
