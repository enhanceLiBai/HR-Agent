"""工具注册与分发 —— 根据工具名分发到对应的执行函数。"""


def execute_tool(name: str, args: dict) -> str:
    """根据工具名分发到对应的执行函数。"""
    from tools.policy import search_policy
    from tools.leave import (
        query_leave_balance,
        create_leave_request,
        approve_leave,
        reject_leave,
        list_pending_approvals,
        cancel_leave_request,
        revoke_leave_request,
        check_auto_approval,
        check_department_conflict,
        adjust_leave_balance,
    )
    from tools.employee import get_employee, get_my_leave_history, search_employee
    from tools.attendance import query_my_attendance, get_attendance_stats
    from tools.dashboard import check_my_dashboard, get_company_dashboard
    from tools.overtime import (
        submit_overtime,
        approve_overtime,
        reject_overtime,
        query_overtime_balance,
        list_pending_overtime,
    )

    registry = {
        "search_policy":            lambda: search_policy(args["query"]),
        "query_leave_balance":      lambda: query_leave_balance(args["employee_id"], args["leave_type"]),
        "check_auto_approval":      lambda: check_auto_approval(args["employee_id"], args["leave_type"], args["start_date"], args["end_date"], args["days"]),
        "create_leave_request":     lambda: create_leave_request(args["employee_id"], args["leave_type"], args["start_date"], args["end_date"], args["reason"], args.get("auto_approve", False)),
        "approve_leave":            lambda: approve_leave(args["request_id"], args["approver_id"], args.get("comment", "")),
        "reject_leave":             lambda: reject_leave(args["request_id"], args["approver_id"], args["reason"]),
        "list_pending_approvals":   lambda: list_pending_approvals(args["manager_id"]),
        "get_employee":             lambda: get_employee(args["employee_id"]),
        "get_my_leave_history":     lambda: get_my_leave_history(args["employee_id"], args.get("limit", 10)),
        "search_employee":          lambda: search_employee(args["keyword"]),
        "cancel_leave_request":     lambda: cancel_leave_request(args["request_id"], args["employee_id"]),
        "revoke_leave_request":     lambda: revoke_leave_request(args["request_id"], args["approver_id"], args["reason"]),
        "query_my_attendance":      lambda: query_my_attendance(args["employee_id"], args.get("month", "2026-06")),
        "get_attendance_stats":     lambda: get_attendance_stats(args["employee_id"], args.get("month", "2026-06")),
        "check_my_dashboard":       lambda: check_my_dashboard(args["employee_id"]),
        "get_company_dashboard":    lambda: get_company_dashboard(args["manager_id"]),
        "check_department_conflict": lambda: check_department_conflict(args["employee_id"], args["start_date"], args["end_date"]),
        "submit_overtime":          lambda: submit_overtime(args["employee_id"], args["date"], args["hours"], args["overtime_type"], args["reason"]),
        "approve_overtime":         lambda: approve_overtime(args["request_id"], args["approver_id"], args.get("comment", "")),
        "reject_overtime":          lambda: reject_overtime(args["request_id"], args["approver_id"], args["reason"]),
        "query_overtime_balance":   lambda: query_overtime_balance(args["employee_id"]),
        "list_pending_overtime":   lambda: list_pending_overtime(args["manager_id"]),
        "adjust_leave_balance":     lambda: adjust_leave_balance(
            args["manager_id"], args["employee_id"], args["leave_type"],
            args["amount"], args["reason"]
        ),
    }

    func = registry.get(name)
    if not func:
        return f"❌ 未知工具: {name}"
    try:
        return func()
    except Exception as e:
        return f"❌ 工具执行错误 ({name}): {str(e)}"
