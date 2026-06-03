from datetime import datetime

from flask import jsonify, render_template, request, url_for

from src.app import (
    MILESTONE_COLUMNS,
    MONTH_LABELS,
    QUARTERS,
    app,
    build_auth_context,
    build_project_gantt,
    build_roadmap_feature_list,
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


ROADMAP_STATUS_LABELS = {
    'in_progress': '进行中',
    'not_started': '未开始',
    'completed': '已完成',
    'risk': '风险',
    'unscheduled': '未排期',
    'due_this_month': '本月到期',
}


def get_roadmap_feature_active_indexes(row):
    return [index for index, month in enumerate(MILESTONE_COLUMNS) if (row.get(month) or '').strip()]


def get_roadmap_feature_status_key(row):
    active_indexes = get_roadmap_feature_active_indexes(row)
    if not active_indexes:
        return 'unscheduled'
    searchable_text = ' '.join([
        row.get('focus_work') or '',
        row.get('feature_name') or '',
        *[(row.get(month) or '') for month in MILESTONE_COLUMNS],
    ])
    if any(keyword in searchable_text for keyword in ('延期', '风险', '阻塞', '延迟')):
        return 'risk'
    current_index = max(0, min(11, datetime.now().month - 1))
    if active_indexes[-1] < current_index:
        return 'completed'
    if active_indexes[0] > current_index:
        return 'not_started'
    return 'in_progress'


def is_roadmap_due_this_month(row):
    active_indexes = get_roadmap_feature_active_indexes(row)
    current_index = max(0, min(11, datetime.now().month - 1))
    return bool(active_indexes and active_indexes[-1] == current_index)


def get_roadmap_filters():
    return {
        'project_name': (request.args.get('project_name') or '').strip(),
        'department': (request.args.get('department') or '').strip(),
        'service_group': (request.args.get('service_group') or '').strip(),
        'delivery_pm': (request.args.get('delivery_pm') or '').strip(),
        'focus_work': (request.args.get('focus_work') or '').strip(),
        'keyword': (request.args.get('keyword') or '').strip(),
        'status': (request.args.get('status') or '').strip(),
        'sort_by': (request.args.get('sort_by') or '').strip() or 'manual',
        'density': (request.args.get('density') or '').strip() or 'comfortable',
    }


def build_roadmap_filter_options(project_rows, feature_rows):
    def unique_values(rows, key):
        return sorted({(row.get(key) or '').strip() for row in rows if (row.get(key) or '').strip()})

    return {
        'projects': unique_values(project_rows, 'project_name'),
        'departments': unique_values(feature_rows, 'five_level_department'),
        'services': unique_values(feature_rows, 'service_group'),
        'pms': unique_values(feature_rows, 'delivery_pm'),
        'statuses': [{'key': key, 'label': label} for key, label in ROADMAP_STATUS_LABELS.items()],
        'sorts': [
            {'key': 'manual', 'label': '手动/置顶'},
            {'key': 'start_month', 'label': '开始月份'},
            {'key': 'end_month', 'label': '结束月份'},
            {'key': 'department', 'label': '五层部门'},
            {'key': 'service', 'label': 'L4服务'},
            {'key': 'pm', 'label': '交付PM'},
        ],
    }


def filter_roadmap_features(feature_rows, filters):
    keyword = (filters.get('keyword') or '').lower()
    focus_work_filter = (filters.get('focus_work') or '').lower()
    status_filter = filters.get('status') or ''

    def matched(row):
        text = ' '.join([
            row.get('project_name') or '',
            row.get('five_level_department') or '',
            row.get('focus_work') or '',
            row.get('feature_name') or '',
            row.get('service_group') or '',
            row.get('delivery_pm') or '',
            *[(row.get(month) or '') for month in MILESTONE_COLUMNS],
        ]).lower()
        if filters.get('project_name') and (row.get('project_name') or '').strip() != filters['project_name']:
            return False
        if filters.get('department') and (row.get('five_level_department') or '').strip() != filters['department']:
            return False
        if filters.get('service_group') and (row.get('service_group') or '').strip() != filters['service_group']:
            return False
        if filters.get('delivery_pm') and (row.get('delivery_pm') or '').strip() != filters['delivery_pm']:
            return False
        if focus_work_filter and focus_work_filter not in (row.get('focus_work') or '').lower():
            return False
        if keyword and keyword not in text:
            return False
        if status_filter == 'due_this_month':
            return is_roadmap_due_this_month(row)
        if status_filter and get_roadmap_feature_status_key(row) != status_filter:
            return False
        return True

    return [row for row in feature_rows if matched(row)]


def sort_roadmap_features(feature_rows, sort_by):
    if sort_by == 'manual':
        return feature_rows

    def sort_key(row):
        indexes = get_roadmap_feature_active_indexes(row)
        if sort_by == 'start_month':
            return (indexes[0] if indexes else 99, row.get('feature_name') or '')
        if sort_by == 'end_month':
            return (indexes[-1] if indexes else 99, row.get('feature_name') or '')
        if sort_by == 'department':
            return (row.get('five_level_department') or '', row.get('feature_name') or '')
        if sort_by == 'service':
            return (row.get('service_group') or '', row.get('feature_name') or '')
        if sort_by == 'pm':
            return (row.get('delivery_pm') or '', row.get('feature_name') or '')
        return (row.get('id') or 0,)

    sorted_rows = []
    for index, row in enumerate(sorted(feature_rows, key=sort_key)):
        item = dict(row)
        item['__roadmap_order'] = index
        sorted_rows.append(item)
    return sorted_rows


def build_roadmap_summary(project_rows, feature_rows):
    project_names = {(row.get('project_name') or '').strip() for row in feature_rows if (row.get('project_name') or '').strip()}
    status_counts = {key: 0 for key in ROADMAP_STATUS_LABELS}
    for row in feature_rows:
        status_counts[get_roadmap_feature_status_key(row)] += 1
        if is_roadmap_due_this_month(row):
            status_counts['due_this_month'] += 1
    return {
        'project_count': len(project_names) or len(project_rows),
        'feature_count': len(feature_rows),
        'current_month': MONTH_LABELS[max(0, min(11, datetime.now().month - 1))],
        'metrics': [
            {'label': '项目数', 'value': len(project_names) or len(project_rows), 'href': url_for('roadmap')},
            {'label': '关键特性', 'value': len(feature_rows), 'href': url_for('roadmap')},
            {'label': '进行中', 'value': status_counts['in_progress'], 'href': url_for('roadmap', status='in_progress')},
            {'label': '本月到期', 'value': status_counts['due_this_month'], 'href': url_for('roadmap', status='due_this_month')},
            {'label': '风险', 'value': status_counts['risk'], 'href': url_for('roadmap', status='risk')},
            {'label': '未排期', 'value': status_counts['unscheduled'], 'href': url_for('roadmap', status='unscheduled')},
        ],
    }


def has_roadmap_filters(filters):
    return any(filters.get(key) for key in ('project_name', 'department', 'service_group', 'delivery_pm', 'focus_work', 'keyword', 'status')) or filters.get('sort_by') not in ('', 'manual') or filters.get('density') == 'compact'


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
    filters = get_roadmap_filters()
    filter_options = build_roadmap_filter_options(project_rows, feature_rows)
    filtered_features = filter_roadmap_features(feature_rows, filters)
    filtered_features = sort_roadmap_features(filtered_features, filters.get('sort_by'))
    current_user = get_current_user() or {}
    user_feature_orders = load_user_feature_orders(current_user.get('user_id'))
    roadmap_features = build_roadmap_feature_list(
        project_rows,
        filtered_features,
        user_feature_orders,
        filters.get('sort_by'),
    )
    return render_template(
        'index.html',
        roadmap_features=roadmap_features,
        roadmap_summary=build_roadmap_summary(project_rows, feature_rows),
        filtered_summary=build_roadmap_summary(project_rows, filtered_features),
        filters=filters,
        filter_options=filter_options,
        has_active_filter=has_roadmap_filters(filters),
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
