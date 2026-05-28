from flask import jsonify, render_template, request

from src.app import (
    MONTH_LABELS,
    QUARTERS,
    app,
    build_auth_context,
    build_project_gantt,
    build_project_roadmap,
    get_branding,
    get_current_user,
    get_home_cards,
    get_conn,
    load_project_features,
    load_projects,
    load_user_feature_orders,
    login_required,
)


@app.route('/')
@login_required
def index():
    return render_template('home.html', branding=get_branding(), home_cards=get_home_cards(), **build_auth_context())


@app.route('/roadmap')
@login_required
def roadmap():
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
