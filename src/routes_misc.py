from flask import flash, redirect, render_template, request, url_for

from src.app import (
    HOME_CARD_SPECS,
    MONTH_LABELS,
    QUARTERS,
    app,
    build_auth_context,
    build_project_gantt,
    build_resource_group_summary,
    build_resource_people_summary,
    build_service_resource_summary,
    filter_resource_people,
    filter_service_resources,
    get_branding,
    get_conn,
    get_resource_people_filter_options,
    get_service_resource_filter_options,
    load_projects,
    load_resource_people,
    load_service_resources,
    login_required,
    parse_workload_value,
    require_feature,
)


@app.route('/requirements', methods=['GET', 'POST'])
@login_required
def requirements_page():
    denied = require_feature('view_requirements', '当前账号不能查看需求')
    if denied:
        return denied
    denied = require_feature('submit_requirement', '当前账号不能提交需求') if request.method == 'POST' else None
    if denied:
        return denied
    if request.method == 'POST':
        requirement_text = (request.form.get('requirement_text') or '').strip()
        if not requirement_text:
            flash('请输入需求内容')
            return redirect(url_for('requirements_page'))
        from datetime import datetime
        submit_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        from src.app import get_current_user
        current_user = get_current_user()
        submitter = current_user.get('name') if isinstance(current_user, dict) else None
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO requirements (requirement_content, submit_date, status, submitter) VALUES (?, ?, 'open', ?)",
                (requirement_text, submit_date, submitter)
            )
            requirement_id = cursor.lastrowid
            requirement_code = f"REQ{requirement_id:04d}"
            conn.execute("UPDATE requirements SET requirement_code = ? WHERE id = ?", (requirement_code, requirement_id))
            conn.commit()
        flash('需求已提交')
        return redirect(url_for('requirements_page'))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, requirement_code, requirement_content, submit_date, close_date, status, submitter FROM requirements ORDER BY id DESC"
        ).fetchall()
    requirements = [dict(row) for row in rows]
    return render_template(
        'requirements.html',
        branding=get_branding(),
        requirements=requirements,
        **build_auth_context(),
    )


@app.route('/requirements/<int:requirement_id>/status', methods=['POST'])
@login_required
def requirement_status_update(requirement_id):
    denied = require_feature('manage_requirement_status', '当前账号不能管理需求状态')
    if denied:
        return denied
    from datetime import datetime
    status = (request.form.get('status') or 'open').strip().lower()
    if status not in {'open', 'closed'}:
        status = 'open'
    close_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status == 'closed' else None
    with get_conn() as conn:
        conn.execute(
            "UPDATE requirements SET status = ?, close_date = ? WHERE id = ?",
            (status, close_date, requirement_id)
        )
        conn.commit()
    flash('需求状态已更新')
    return redirect(url_for('requirements_page'))


@app.route('/views/<view_key>')
@login_required
def view_placeholder(view_key):
    view_map = {
        'milestone-condolence': {
            'title': '关键突破&战地激励',
            'description': '查看关键突破与战地激励相关内容。',
            'feature': 'view_milestone',
        },
        'department-budget-resource': {
            'title': '投资视图',
            'description': '查看投资维度的整体情况、投入分布与汇总信息。',
            'feature': 'view_investment',
        },
        'department-pipeline-load': {
            'title': '项目视图',
            'description': '查看项目维度的整体情况、排期分布与重点内容。',
            'feature': 'view_projects',
        },
        'project-budget-resource': {
            'title': '资源视图',
            'description': '查看项目维度的预算与资源分布信息。',
            'feature': 'view_resource_people',
        },
        'cloud-service-view': {
            'title': '云服务视图',
            'description': '按云服务粒度查看资源投入情况。',
            'feature': 'view_service_resources',
        },
        'roadmap': next(({
            'title': spec['default_title'],
            'description': spec['desc'],
            'feature': 'view_features',
        } for spec in HOME_CARD_SPECS if spec['key'] == 'roadmap'), {
            'title': '关键特性视图',
            'description': '查看所规划关键特性的路标信息。',
            'feature': 'view_features',
        }),
    }
    view_config = view_map.get(view_key)
    if not view_config:
        flash('页面不存在')
        return redirect(url_for('index'))
    denied = require_feature(view_config.get('feature'), f"当前账号不能查看{view_config.get('title')}")
    if denied:
        return denied

    if view_key == 'cloud-service-view':
        department_keyword = (request.args.get('department') or '').strip()
        service_keyword = (request.args.get('service') or '').strip()
        rows = load_service_resources()
        filtered_rows = filter_service_resources(rows, department_keyword=department_keyword, service_keyword=service_keyword)
        return render_template(
            'cloud_service_view.html',
            records=filtered_rows,
            summary=build_service_resource_summary(filtered_rows),
            filters={'department': department_keyword, 'service': service_keyword},
            filter_options=get_service_resource_filter_options(rows),
            **build_auth_context(),
        )

    if view_key == 'department-pipeline-load':
        project_rows = load_projects()
        sorted_projects = sorted(
            project_rows,
            key=lambda row: (-parse_workload_value(row.get('workload_person_month')), (row.get('project_name') or '').strip(), row.get('id') or 0),
        )
        from datetime import datetime
        now = datetime.utcnow()
        display_year = now.year
        today_marker_percent = ((now.month - 1) + 0.5) / 12 * 100 if now.year == display_year else None
        return render_template(
            'project_view.html',
            projects=sorted_projects,
            gantt_projects=build_project_gantt(sorted_projects, display_year),
            month_labels=MONTH_LABELS,
            quarters=QUARTERS,
            display_year=display_year,
            today_marker_percent=today_marker_percent,
            **build_auth_context(),
        )

    if view_key == 'project-budget-resource':
        rows = load_resource_people()
        person_type = (request.args.get('person_type') or '').strip()
        department_name = (request.args.get('department_name') or '').strip()
        project_name = (request.args.get('project_name') or '').strip()
        keyword = (request.args.get('keyword') or '').strip()
        filtered_rows = filter_resource_people(rows, person_type=person_type, department_name=department_name, project_name=project_name, keyword=keyword)
        return render_template(
            'resource_view.html',
            records=filtered_rows,
            summary=build_resource_people_summary(filtered_rows),
            department_summary=build_resource_group_summary(filtered_rows, 'department_full_name', mode='project_bound_ratio'),
            project_summary=build_resource_group_summary(filtered_rows, 'project_name', mode='allocation_total'),
            filter_options=get_resource_people_filter_options(rows),
            filters={
                'person_type': person_type,
                'department_name': department_name,
                'project_name': project_name,
                'keyword': keyword,
            },
            **build_auth_context(),
        )

    return render_template('view_placeholder.html', **view_config, **build_auth_context())
