from flask import jsonify, render_template, request, url_for

from src.app import (
    MONTH_LABELS,
    QUARTERS,
    app,
    build_auth_context,
    build_project_gantt,
    build_project_roadmap,
    can_access,
    get_branding,
    get_current_user,
    get_visible_home_cards,
    get_conn,
    load_project_features,
    load_projects,
    load_resource_people,
    load_service_resources,
    load_user_feature_orders,
    login_required,
    require_feature,
)


HOME_CARD_SECTION_META = {
    'milestone-condolence': ('项目作战', '关键突破与团队激励事项', '突破'),
    'department-pipeline-load': ('项目作战', '查看项目排期、阶段进展与交付节奏', '项目'),
    'roadmap': ('项目作战', '查看关键特性路标与交付节奏', '特性'),
    'project-budget-resource': ('资源经营', '查看部门人力、人员状态与项目投入', '资源'),
    'department-budget-resource': ('资源经营', '从投资主体、管控灶和预算维度看投入', '投资'),
    'cloud-service-view': ('服务运营', '查看服务归属、负责人和资源承载', '服务'),
}

HOME_SECTION_ORDER = ['项目作战', '资源经营', '服务运营']


def build_home_dashboard_summary(user=None):
    projects = load_projects()
    features = load_project_features()
    resource_people = load_resource_people()
    service_resources = load_service_resources()

    closed_statuses = {'完成', '已完成', '关闭', '已关闭', '终止', '已终止', '取消', '已取消'}
    active_projects = [
        row for row in projects
        if (row.get('project_status') or '').strip() not in closed_statuses
    ]
    feature_count = sum(1 for row in features if (row.get('feature_name') or '').strip())
    status_not_on_duty = sum(1 for row in resource_people if (row.get('status') or '').strip() != '在岗')
    missing_project = sum(1 for row in resource_people if not (row.get('project_name') or '').strip())
    service_count = sum(1 for row in service_resources if (row.get('l4_cloud_service') or '').strip())
    missing_service_leader = sum(1 for row in service_resources if not (row.get('service_leader') or '').strip())

    metrics = [
        {
            'feature': 'view_projects',
            'label': '进行中项目',
            'value': len(active_projects),
            'note': f'总项目 {len(projects)}',
            'href': url_for('view_placeholder', view_key='department-pipeline-load'),
        },
        {
            'feature': 'view_features',
            'label': '关键特性',
            'value': feature_count,
            'note': '路标规划项',
            'href': url_for('roadmap'),
        },
        {
            'feature': 'view_resource_people',
            'label': '资源人数',
            'value': len(resource_people),
            'note': f'非在岗 {status_not_on_duty}',
            'href': url_for('view_placeholder', view_key='project-budget-resource'),
        },
        {
            'feature': 'view_resource_people',
            'label': '未关联项目',
            'value': missing_project,
            'note': '需补齐投入归属',
            'href': url_for('view_placeholder', view_key='project-budget-resource', quick_filter='missing_project'),
        },
        {
            'feature': 'view_service_resources',
            'label': '云服务',
            'value': service_count,
            'note': f'缺负责人 {missing_service_leader}',
            'href': url_for('view_placeholder', view_key='cloud-service-view'),
        },
    ]
    return [metric for metric in metrics if can_access(metric['feature'], user)]


def build_home_sections(cards):
    grouped = {name: [] for name in HOME_SECTION_ORDER}
    for card in cards:
        section, desc, badge = HOME_CARD_SECTION_META.get(card.get('key'), ('其他', card.get('desc') or '', '入口'))
        item = dict(card)
        item['section_desc'] = desc
        item['badge'] = badge
        grouped.setdefault(section, []).append(item)
    return [
        {'title': title, 'cards': grouped.get(title, [])}
        for title in [*HOME_SECTION_ORDER, *[key for key in grouped if key not in HOME_SECTION_ORDER]]
        if grouped.get(title)
    ]


@app.route('/')
@login_required
def index():
    current_user = get_current_user()
    home_cards = get_visible_home_cards(current_user)
    return render_template(
        'home.html',
        branding=get_branding(),
        home_cards=home_cards,
        home_sections=build_home_sections(home_cards),
        dashboard_metrics=build_home_dashboard_summary(current_user),
        **build_auth_context(),
    )


@app.route('/roadmap')
@login_required
def roadmap():
    denied = require_feature('view_features', '当前账号不能查看关键特性视图')
    if denied:
        return denied
    project_rows = load_projects()
    feature_rows = load_project_features()
    current_user = get_current_user() or {}
    user_feature_orders = load_user_feature_orders(current_user.get('user_id'))
    project_groups = build_project_roadmap(project_rows, feature_rows, user_feature_orders)
    return render_template(
        'index.html',
        project_groups=project_groups,
        month_labels=MONTH_LABELS,
        quarters=QUARTERS,
        branding=get_branding(),
        **build_auth_context(),
    )


@app.route('/roadmap/feature-pin', methods=['POST'])
@login_required
def save_roadmap_feature_pin():
    denied = require_feature('view_features', '当前账号不能查看关键特性视图')
    if denied:
        return {'ok': False}, 403
    payload = request.get_json(silent=True) or {}
    project_id = payload.get('project_id')
    feature_id = payload.get('feature_id')
    pin = bool(payload.get('pin'))
    current_user = get_current_user() or {}
    user_id = (current_user.get('user_id') or '').strip()
    if not user_id or not project_id or not feature_id:
        return {'ok': False}, 400

    with get_conn() as conn:
        existing = conn.execute(
            """
            SELECT feature_id, sort_index
            FROM user_feature_orders
            WHERE user_id = ? AND project_id = ?
            ORDER BY sort_index ASC, id ASC
            """,
            (user_id, project_id),
        ).fetchall()

        if pin:
            for row in existing:
                if row['sort_index'] < 0:
                    conn.execute(
                        "UPDATE user_feature_orders SET sort_index = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND project_id = ? AND feature_id = ?",
                        (row['sort_index'] - 1, user_id, project_id, row['feature_id'])
                    )
            conn.execute(
                """
                INSERT INTO user_feature_orders (user_id, project_id, feature_id, sort_index, updated_at)
                VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, project_id, feature_id)
                DO UPDATE SET sort_index = 0, updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, project_id, feature_id),
            )
        else:
            current_row = next((row for row in existing if row['feature_id'] == feature_id), None)
            if current_row and current_row['sort_index'] <= 0:
                removed_index = current_row['sort_index']
                for row in existing:
                    if row['feature_id'] != feature_id and row['sort_index'] < removed_index:
                        conn.execute(
                            "UPDATE user_feature_orders SET sort_index = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND project_id = ? AND feature_id = ?",
                            (row['sort_index'] + 1, user_id, project_id, row['feature_id'])
                        )
                conn.execute(
                    "UPDATE user_feature_orders SET sort_index = 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND project_id = ? AND feature_id = ?",
                    (user_id, project_id, feature_id),
                )
            else:
                conn.execute(
                    "UPDATE user_feature_orders SET sort_index = 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND project_id = ? AND feature_id = ?",
                    (user_id, project_id, feature_id),
                )
        conn.commit()
    return {'ok': True}
