from flask import jsonify, redirect, render_template, request, url_for

from src.app import (
    app,
    build_auth_context,
    build_project_gantt,
    build_project_roadmap,
    get_branding,
    get_current_user,
    get_home_cards,
    load_project_features,
    load_projects,
    load_user_feature_orders,
    login_required,
    require_feature,
)


@app.route('/')
@login_required
def index():
    user = get_current_user() or {}
    user_id = user.get('user_id') or ''
    project_rows = load_projects()
    feature_rows = load_project_features()
    user_feature_orders = load_user_feature_orders(user_id) if user_id else {}
    project_groups = build_project_roadmap(project_rows, feature_rows, user_feature_orders=user_feature_orders)
    return render_template(
        'index.html',
        branding=get_branding(),
        home_cards=get_home_cards(),
        project_groups=project_groups,
        user_feature_orders=user_feature_orders,
        **build_auth_context(),
    )


@app.route('/roadmap')
@login_required
def roadmap():
    project_rows = load_projects()
    display_year = request.args.get('year', type=int)
    gantt = build_project_gantt(project_rows, display_year)
    return render_template(
        'project_view.html',
        branding=get_branding(),
        gantt=gantt,
        **build_auth_context(),
    )


@app.route('/roadmap/feature-pin', methods=['POST'])
@login_required
def save_roadmap_feature_pin():
    denied = require_feature('manage_features', '当前账号不能管理关键特性')
    if denied:
        return denied
    from src.app import get_conn
    payload = request.get_json(silent=True) or {}
    project_id = int(payload.get('project_id') or 0)
    feature_id = int(payload.get('feature_id') or 0)
    pin = 1 if payload.get('pin') else 0
    if not project_id or not feature_id:
        return jsonify({'ok': False, 'message': '参数不完整'}), 400
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_feature_orders (user_id, project_id, feature_id, pinned, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, project_id, feature_id)
            DO UPDATE SET pinned = excluded.pinned, updated_at = CURRENT_TIMESTAMP
            """,
            [str((get_current_user() or {}).get('user_id') or ''), project_id, feature_id, pin],
        )
        conn.commit()
    return jsonify({'ok': True})
